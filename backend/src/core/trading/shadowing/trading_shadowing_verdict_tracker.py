from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingVerdictCycleStatistics
from src.core.trading.trading_dex_capability_service import resolve_supported_trading_solana_dex_ids
from src.core.utils.date_utils import get_current_local_datetime, ensure_timezone_aware
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens_with_metadata
from src.integrations.blockchain.solana.solana_mint_freeze_authority_service import (
    is_solana_mint_blocked_by_active_freeze_authority_from_snapshots,
    resolve_solana_mint_freeze_authority_snapshots_batch,
)
from src.integrations.blockchain.solana.solana_structures import SolanaMintFreezeAuthoritySnapshot
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list_sync
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingShadowingVerdict, TradingShadowingProbe

logger = get_application_logger(__name__)


class TradingShadowingVerdictTracker:
    def check_pending_verdicts(self) -> None:
        logger.debug("[TRADING][SHADOWING][VERDICT] Starting shadowing verdict check cycle")

        with get_database_session() as database_session:
            verdict_dao = TradingShadowingVerdictDao(database_session)

            max_pending_per_cycle = settings.TRADING_SHADOWING_PENDING_VERDICTS_FETCH
            configured_batch_size = settings.TRADING_SHADOWING_PENDING_VERDICTS_BATCH_SIZE
            pending_batch_size = max(1, min(configured_batch_size, max_pending_per_cycle))

            cycle_statistics = TradingShadowingVerdictCycleStatistics()
            last_seen_id = 0

            while cycle_statistics.pending_verdict_count < max_pending_per_cycle:
                remaining_budget = max_pending_per_cycle - cycle_statistics.pending_verdict_count
                batch_limit = min(pending_batch_size, remaining_budget)

                pending_verdicts = verdict_dao.retrieve_pending_verdicts_after_id(
                    after_id_exclusive=last_seen_id,
                    limit_count=batch_limit,
                )
                if not pending_verdicts:
                    break

                last_batch_seen_id = pending_verdicts[-1].id
                batch_statistics = self._process_pending_verdict_batch(pending_verdicts)
                database_session.commit()
                database_session.expunge_all()

                cycle_statistics.merge(batch_statistics)
                last_seen_id = last_batch_seen_id

            if cycle_statistics.pending_verdict_count == 0:
                logger.debug("[TRADING][SHADOWING][VERDICT] No pending shadowing verdicts to check")
                return

            logger.info(
                "[TRADING][SHADOWING][VERDICT] Cycle complete — resolved=%d/%d pending (%s) batch_size=%d cap=%d",
                cycle_statistics.resolved_verdict_count,
                cycle_statistics.pending_verdict_count,
                cycle_statistics.format_non_zero_breakdown(),
                pending_batch_size,
                max_pending_per_cycle,
            )

    def _process_pending_verdict_batch(
            self,
            pending_verdicts: list[TradingShadowingVerdict],
    ) -> TradingShadowingVerdictCycleStatistics:
        batch_statistics = TradingShadowingVerdictCycleStatistics(
            pending_verdict_count=len(pending_verdicts),
        )
        logger.info("[TRADING][SHADOWING][VERDICT] Processing pending batch of %d verdicts", len(pending_verdicts))

        probes = [verdict.probe for verdict in pending_verdicts]
        dexscreener_prices = self._fetch_dexscreener_prices(probes)

        if dexscreener_prices is None:
            batch_statistics.skipped_batch_dexscreener_unavailable_verdict_count = len(pending_verdicts)
            logger.warning(
                "[TRADING][SHADOWING][VERDICT] Skipping pending batch — DexScreener price fetch failed entirely "
                "(skipped_verdict_count=%d)",
                batch_statistics.skipped_batch_dexscreener_unavailable_verdict_count,
            )
            return batch_statistics

        current_time = get_current_local_datetime()
        lethargic_cutoff_hours = settings.TRADING_SHADOWING_LETHARGIC_HOURS

        resolving_candidates: list[tuple[TradingShadowingVerdict, float]] = []
        lethargic_candidates: list[tuple[TradingShadowingVerdict, float]] = []

        for verdict in pending_verdicts:
            probe = verdict.probe
            current_price = dexscreener_prices.get(self._build_price_key(probe))

            if current_price is None:
                self._attach_stale_verdict(verdict, probe, current_time)
                batch_statistics.resolved_verdict_count += 1
                batch_statistics.resolved_staled_missing_dex_price_count += 1
                logger.info(
                    "[TRADING][SHADOWING][VERDICT] %s marked as STALED — no DexScreener price (token delisted or dead)",
                    probe.token_symbol,
                )
                continue

            if current_price >= verdict.take_profit_tier_1_price and verdict.take_profit_tier_1_hit_at is None:
                verdict.take_profit_tier_1_hit_at = current_time
                logger.debug("[TRADING][SHADOWING][VERDICT] %s touched TP1 at %.4f", probe.token_symbol, current_price)

            self._record_post_take_profit_tier_1_retrace(verdict, probe, current_price, current_time)

            if current_price >= verdict.take_profit_tier_2_price or current_price <= verdict.stop_loss_price:
                resolving_candidates.append((verdict, current_price))
            else:
                aware_probed_at = ensure_timezone_aware(probe.probed_at) or current_time
                age_hours = (current_time - aware_probed_at).total_seconds() / 3600.0

                if age_hours >= lethargic_cutoff_hours:
                    lethargic_candidates.append((verdict, current_price))

        freeze_authority_snapshots = self._resolve_solana_freeze_authority_snapshots_for_probes(
            probes=[verdict.probe for verdict, _ in resolving_candidates]
                   + [verdict.probe for verdict, _ in lethargic_candidates],
        )

        if resolving_candidates:
            if freeze_authority_snapshots is None:
                batch_statistics.deferred_threshold_resolution_freeze_authority_unavailable_count = len(resolving_candidates)
                logger.debug(
                    "[TRADING][SHADOWING][VERDICT] Skipping threshold resolution — Solana mint freeze authority lookup unavailable "
                    "(deferred_threshold_count=%d)",
                    batch_statistics.deferred_threshold_resolution_freeze_authority_unavailable_count,
                )
            else:
                resolving_candidates, honeypot_resolved_count = self._resolve_honeypot_shadowing_verdicts(
                    candidate_verdicts=resolving_candidates,
                    freeze_authority_snapshots=freeze_authority_snapshots,
                    current_time=current_time,
                )
                batch_statistics.resolved_verdict_count += honeypot_resolved_count
                batch_statistics.resolved_honeypot_count += honeypot_resolved_count

        if resolving_candidates and freeze_authority_snapshots is not None:
            supported_solana_dex_ids = resolve_supported_trading_solana_dex_ids()
            onchain_resolvable_candidates: list[tuple[TradingShadowingVerdict, float]] = []
            staled_unrecoverable_symbols_logged: set[str] = set()
            deferred_onchain_symbols_logged: set[str] = set()

            for verdict, dex_price in resolving_candidates:
                probe = verdict.probe
                blockchain_network = BlockchainNetwork(probe.blockchain_network.lower())
                if (
                        blockchain_network == BlockchainNetwork.SOLANA
                        and probe.dex_id.lower().strip() not in supported_solana_dex_ids
                ):
                    self._attach_stale_verdict(verdict, probe, current_time)
                    batch_statistics.resolved_verdict_count += 1
                    batch_statistics.resolved_staled_unrecoverable_onchain_price_count += 1
                    if probe.token_symbol not in staled_unrecoverable_symbols_logged:
                        staled_unrecoverable_symbols_logged.add(probe.token_symbol)
                        logger.info(
                            "[TRADING][SHADOWING][VERDICT] %s marked as STALED — dex %s unsupported for on-chain pricing, stopping retries",
                            probe.token_symbol,
                            probe.dex_id,
                        )
                    continue
                onchain_resolvable_candidates.append((verdict, dex_price))

            if onchain_resolvable_candidates:
                resolution_tokens = [
                    Token(
                        symbol=verdict.probe.token_symbol,
                        chain=BlockchainNetwork(verdict.probe.blockchain_network.lower()),
                        token_address=verdict.probe.token_address,
                        pair_address=verdict.probe.pair_address,
                        dex_id=verdict.probe.dex_id,
                    ) for verdict, _ in onchain_resolvable_candidates
                ]

                onchain_fetch_result = fetch_onchain_prices_for_tokens_with_metadata(
                    resolution_tokens,
                    require_all_prices=False,
                )
                onchain_prices = onchain_fetch_result.onchain_prices

                maximum_slippage = settings.TRADING_MAX_SLIPPAGE
                aberrant_price_tolerance = settings.TRADING_SHADOWING_DEXSCREENER_ABERRANT_PRICE_TOLERANCE

                for verdict, dex_price in onchain_resolvable_candidates:
                    probe = verdict.probe
                    onchain_price = onchain_prices.try_resolve_price_usd_for_pair_address(probe.pair_address)
                    if onchain_price is None:
                        if onchain_fetch_result.had_infrastructure_failure:
                            batch_statistics.deferred_onchain_price_unavailable_count += 1
                            if probe.token_symbol not in deferred_onchain_symbols_logged:
                                deferred_onchain_symbols_logged.add(probe.token_symbol)
                                logger.debug(
                                    "[TRADING][SHADOWING][VERDICT] Deferring %s — Solana RPC unavailable for on-chain price, retry next cycle",
                                    probe.token_symbol,
                                )
                        else:
                            self._attach_stale_verdict(verdict, probe, current_time)
                            batch_statistics.resolved_verdict_count += 1
                            batch_statistics.resolved_staled_unrecoverable_onchain_price_count += 1
                            if probe.token_symbol not in staled_unrecoverable_symbols_logged:
                                staled_unrecoverable_symbols_logged.add(probe.token_symbol)
                                logger.info(
                                    "[TRADING][SHADOWING][VERDICT] %s marked as STALED — on-chain price unrecoverable (dead pool / drained liquidity), stopping retries",
                                    probe.token_symbol,
                                )
                        continue

                    low_price, high_price = sorted([onchain_price, dex_price])
                    relative_deviation = (high_price / low_price) - 1.0

                    if relative_deviation > aberrant_price_tolerance:
                        logger.info(
                            "[TRADING][SHADOWING][VERDICT] %s marked as STALED — aberrant DexScreener price deviation %.1f%% (onchain=%.12f dex=%.12f, tolerance=%.0f%%)",
                            probe.token_symbol, relative_deviation * 100.0, onchain_price, dex_price, aberrant_price_tolerance * 100.0,
                        )
                        self._attach_stale_verdict(verdict, probe, current_time)
                        batch_statistics.resolved_verdict_count += 1
                        batch_statistics.resolved_staled_aberrant_onchain_dex_price_count += 1
                        continue

                    if relative_deviation > maximum_slippage:
                        batch_statistics.deferred_transient_slippage_count += 1
                        logger.debug(
                            "[TRADING][SHADOWING][VERDICT] Skipping %s — transient slippage %.1f%% (onchain=%.12f dex=%.12f), will retry next cycle",
                            probe.token_symbol, relative_deviation * 100.0, onchain_price, dex_price,
                        )
                        continue

                    if self._evaluate_price_against_thresholds(verdict, probe, onchain_price, current_time):
                        batch_statistics.resolved_verdict_count += 1
                        if verdict.exit_reason == "TAKE_PROFIT_2":
                            batch_statistics.resolved_take_profit_2_count += 1
                        elif verdict.exit_reason == "STOP_LOSS":
                            batch_statistics.resolved_stop_loss_count += 1
                        logger.debug(
                            "[TRADING][SHADOWING][VERDICT] %s resolved — exit=%s pnl=%.2f%% probe_id=%s verdict_id=%s (onchain verified)",
                            probe.token_symbol, verdict.exit_reason, verdict.realized_pnl_percentage, probe.id, verdict.id
                        )

        if freeze_authority_snapshots is None:
            if lethargic_candidates:
                batch_statistics.deferred_lethargic_resolution_freeze_authority_unavailable_count = len(lethargic_candidates)
            logger.debug(
                "[TRADING][SHADOWING][VERDICT] Skipping lethargic resolution — Solana mint freeze authority lookup unavailable "
                "(deferred_lethargic_count=%d)",
                batch_statistics.deferred_lethargic_resolution_freeze_authority_unavailable_count,
            )
        else:
            for verdict, dex_price in lethargic_candidates:
                probe = verdict.probe
                if self._is_probe_blocked_by_active_solana_freeze_authority(
                        probe=probe,
                        freeze_authority_snapshots=freeze_authority_snapshots,
                ):
                    self.attach_honeypot_shadowing_verdict(
                        verdict=verdict,
                        probe=probe,
                        current_time=current_time,
                    )
                    batch_statistics.resolved_verdict_count += 1
                    batch_statistics.resolved_honeypot_count += 1
                    logger.info(
                        "[TRADING][SHADOWING][VERDICT][HONEYPOT] %s marked as HONEYPOT — active mint freeze authority",
                        probe.token_symbol,
                    )
                    continue

                self._attach_lethargic_verdict(verdict, probe, current_time, dex_price)
                batch_statistics.resolved_verdict_count += 1
                batch_statistics.resolved_lethargic_count += 1
                logger.info(
                    "[TRADING][SHADOWING][VERDICT] %s marked as LETHARGIC after %d hours",
                    probe.token_symbol,
                    lethargic_cutoff_hours,
                )

        return batch_statistics

    def _record_post_take_profit_tier_1_retrace(
            self,
            verdict: TradingShadowingVerdict,
            probe: TradingShadowingProbe,
            current_price: float,
            current_time: datetime,
    ) -> None:
        if verdict.take_profit_tier_1_hit_at is None:
            return

        previous_lowest_price: Optional[float] = verdict.post_take_profit_tier_1_lowest_price
        if previous_lowest_price is None or current_price < previous_lowest_price:
            verdict.post_take_profit_tier_1_lowest_price = current_price

        entry_price: float = probe.entry_price_usd
        if entry_price <= 0.0 or verdict.post_take_profit_tier_1_breakeven_touched_at is not None:
            return

        if current_price <= entry_price:
            verdict.post_take_profit_tier_1_breakeven_touched_at = current_time
            logger.debug(
                "[TRADING][SHADOWING][VERDICT][RETRACE] %s fell back to entry after TP1 at %.12f (entry=%.12f)",
                probe.token_symbol,
                current_price,
                entry_price,
            )

    def _evaluate_price_against_thresholds(
            self,
            verdict: TradingShadowingVerdict,
            probe: TradingShadowingProbe,
            current_price: float,
            current_time: datetime,
    ) -> bool:
        entry_price = probe.entry_price_usd
        if entry_price <= 0.0:
            return False

        tp2_price = verdict.take_profit_tier_2_price
        stop_loss_price = verdict.stop_loss_price

        aware_probed_at = ensure_timezone_aware(probe.probed_at) or current_time
        holding_duration_minutes = (current_time - aware_probed_at).total_seconds() / 60.0
        notional = probe.order_notional_value_usd

        if current_price >= tp2_price:
            pnl_percentage = ((current_price - entry_price) / entry_price) * 100.0
            pnl_usd = notional * (pnl_percentage / 100.0)

            if verdict.take_profit_tier_1_hit_at is None:
                verdict.take_profit_tier_1_hit_at = current_time
            verdict.take_profit_tier_2_hit_at = current_time

            verdict.exit_reason = "TAKE_PROFIT_2"
            verdict.realized_pnl_percentage = pnl_percentage
            verdict.realized_pnl_usd = pnl_usd
            verdict.holding_duration_minutes = holding_duration_minutes
            verdict.is_profitable = True
            verdict.resolved_at = current_time
            return True

        if current_price <= stop_loss_price:
            pnl_percentage = ((current_price - entry_price) / entry_price) * 100.0
            pnl_usd = notional * (pnl_percentage / 100.0)

            verdict.stop_loss_hit_at = current_time

            verdict.exit_reason = "STOP_LOSS"
            verdict.realized_pnl_percentage = pnl_percentage
            verdict.realized_pnl_usd = pnl_usd
            verdict.holding_duration_minutes = holding_duration_minutes
            verdict.is_profitable = False
            verdict.resolved_at = current_time
            return True

        return False

    def _attach_stale_verdict(self, verdict: TradingShadowingVerdict, probe: TradingShadowingProbe, current_time: datetime) -> None:
        notional = probe.order_notional_value_usd
        aware_probed_at = ensure_timezone_aware(probe.probed_at) or current_time
        holding_duration_minutes = (current_time - aware_probed_at).total_seconds() / 60.0
        verdict.exit_reason = "STALED"
        verdict.realized_pnl_percentage = -100.0
        verdict.realized_pnl_usd = -notional
        verdict.holding_duration_minutes = holding_duration_minutes
        verdict.is_profitable = False
        verdict.resolved_at = current_time

    def attach_honeypot_shadowing_verdict(
            self,
            verdict: TradingShadowingVerdict,
            probe: TradingShadowingProbe,
            current_time: datetime,
    ) -> None:
        notional = probe.order_notional_value_usd
        aware_probed_at = ensure_timezone_aware(probe.probed_at) or current_time
        holding_duration_minutes = (current_time - aware_probed_at).total_seconds() / 60.0
        verdict.exit_reason = "HONEYPOT"
        verdict.realized_pnl_percentage = -100.0
        verdict.realized_pnl_usd = -notional
        verdict.holding_duration_minutes = holding_duration_minutes
        verdict.is_profitable = False
        verdict.resolved_at = current_time
        verdict.take_profit_tier_2_hit_at = None

    def _resolve_honeypot_shadowing_verdicts(
            self,
            candidate_verdicts: list[tuple[TradingShadowingVerdict, float]],
            freeze_authority_snapshots: list[SolanaMintFreezeAuthoritySnapshot],
            current_time: datetime,
    ) -> tuple[list[tuple[TradingShadowingVerdict, float]], int]:
        remaining_candidates: list[tuple[TradingShadowingVerdict, float]] = []
        honeypot_resolved_count = 0

        for verdict, dex_price in candidate_verdicts:
            probe = verdict.probe
            if self._is_probe_blocked_by_active_solana_freeze_authority(
                    probe=probe,
                    freeze_authority_snapshots=freeze_authority_snapshots,
            ):
                self.attach_honeypot_shadowing_verdict(
                    verdict=verdict,
                    probe=probe,
                    current_time=current_time,
                )
                honeypot_resolved_count += 1
                logger.info(
                    "[TRADING][SHADOWING][VERDICT][HONEYPOT] %s marked as HONEYPOT — active mint freeze authority",
                    probe.token_symbol,
                )
                continue

            remaining_candidates.append((verdict, dex_price))

        return remaining_candidates, honeypot_resolved_count

    def _resolve_solana_freeze_authority_snapshots_for_probes(
            self,
            probes: list[TradingShadowingProbe],
    ) -> Optional[list[SolanaMintFreezeAuthoritySnapshot]]:
        mint_addresses = self._collect_unique_solana_mint_addresses_from_probes(probes=probes)
        if not mint_addresses:
            return []

        try:
            return resolve_solana_mint_freeze_authority_snapshots_batch(mint_addresses=mint_addresses)
        except BlockchainRpcUnavailableError:
            logger.debug(
                "[TRADING][SHADOWING][VERDICT][HONEYPOT] Solana mint freeze authority batch lookup unavailable",
            )
            return None

    def _collect_unique_solana_mint_addresses_from_probes(
            self,
            probes: list[TradingShadowingProbe],
    ) -> list[str]:
        mint_addresses: list[str] = []
        seen_mint_addresses: set[str] = set()

        for probe in probes:
            if probe.blockchain_network.lower() != BlockchainNetwork.SOLANA.value:
                continue

            normalized_mint_address = probe.token_address.strip()
            if not normalized_mint_address or normalized_mint_address in seen_mint_addresses:
                continue

            seen_mint_addresses.add(normalized_mint_address)
            mint_addresses.append(normalized_mint_address)

        return mint_addresses

    def _is_probe_blocked_by_active_solana_freeze_authority(
            self,
            probe: TradingShadowingProbe,
            freeze_authority_snapshots: list[SolanaMintFreezeAuthoritySnapshot],
    ) -> bool:
        if probe.blockchain_network.lower() != BlockchainNetwork.SOLANA.value:
            return False

        return is_solana_mint_blocked_by_active_freeze_authority_from_snapshots(
            snapshots=freeze_authority_snapshots,
            mint_address=probe.token_address,
        )

    def _attach_lethargic_verdict(self, verdict: TradingShadowingVerdict, probe: TradingShadowingProbe, current_time: datetime, current_price: float) -> None:
        entry_price = probe.entry_price_usd
        notional = probe.order_notional_value_usd
        aware_probed_at = ensure_timezone_aware(probe.probed_at) or current_time
        holding_duration_minutes = (current_time - aware_probed_at).total_seconds() / 60.0

        pnl_percentage = ((current_price - entry_price) / entry_price) * 100.0 if entry_price > 0.0 else -100.0
        pnl_usd = notional * (pnl_percentage / 100.0)

        verdict.exit_reason = "LETHARGIC"
        verdict.realized_pnl_percentage = pnl_percentage
        verdict.realized_pnl_usd = pnl_usd
        verdict.holding_duration_minutes = holding_duration_minutes
        verdict.is_profitable = pnl_percentage > 0.0
        verdict.resolved_at = current_time

    def _fetch_dexscreener_prices(self, probes: list[TradingShadowingProbe]) -> Optional[dict[str, float]]:
        unique_tokens: list[Token] = []
        processed_keys: set[str] = set()

        for probe in probes:
            price_key = self._build_price_key(probe)
            if price_key in processed_keys:
                continue
            processed_keys.add(price_key)
            unique_tokens.append(Token(
                symbol=probe.token_symbol,
                chain=BlockchainNetwork(probe.blockchain_network.lower()),
                token_address=probe.token_address,
                pair_address=probe.pair_address,
                dex_id=probe.dex_id,
            ))

        if not unique_tokens:
            return {}

        try:
            token_information_list = fetch_dexscreener_token_information_list_sync(unique_tokens)
        except Exception:
            logger.exception("[TRADING][SHADOWING][VERDICT] Failed to fetch DexScreener prices for shadowing probes")
            return None

        price_map: dict[str, float] = {}
        for token_information in token_information_list:
            price_key = f"{token_information.chain_id.value}:{token_information.base_token.address}:{token_information.pair_address}"
            if token_information.price_usd is not None and token_information.price_usd > 0.0:
                price_map[price_key] = token_information.price_usd

        return price_map

    def _build_price_key(self, probe: TradingShadowingProbe) -> str:
        return f"{probe.blockchain_network}:{probe.token_address}:{probe.pair_address}"
