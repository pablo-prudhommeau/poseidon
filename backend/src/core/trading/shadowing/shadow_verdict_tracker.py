from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.configuration.config import settings
from src.core.utils.date_utils import get_current_local_datetime, ensure_timezone_aware
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.db import get_database_session
from src.persistence.models import TradingShadowingVerdict, TradingShadowingProbe

logger = get_application_logger(__name__)


class ShadowVerdictTracker:
    def check_pending_verdicts(self) -> None:
        logger.debug("[TRADING][SHADOW][VERDICT] Starting shadow verdict check cycle")

        with get_database_session() as database_session:
            verdict_dao = TradingShadowingVerdictDao(database_session)

            pending_verdicts = verdict_dao.retrieve_pending_verdicts(limit_count=50000)
            if not pending_verdicts:
                logger.debug("[TRADING][SHADOW][VERDICT] No pending shadow verdicts to check")
                return

            logger.info("[TRADING][SHADOW][VERDICT] Checking %d pending shadow verdicts", len(pending_verdicts))

            probes = [verdict.probe for verdict in pending_verdicts]
            dexscreener_prices = self._fetch_dexscreener_prices(probes)

            if dexscreener_prices is None:
                logger.warning("[TRADING][SHADOW][VERDICT] Skipping verdict cycle — DexScreener price fetch failed entirely")
                return

            current_time = get_current_local_datetime()
            lethargic_cutoff_hours = settings.TRADING_SHADOWING_LETHARGIC_HOURS
            resolved_count = 0

            resolving_candidates: list[tuple[TradingShadowingVerdict, float]] = []
            lethargic_candidates: list[tuple[TradingShadowingVerdict, float]] = []

            for verdict in pending_verdicts:
                probe = verdict.probe
                current_price = dexscreener_prices.get(self._build_price_key(probe))

                if current_price is None:
                    self._attach_stale_verdict(verdict, probe, current_time)
                    resolved_count += 1
                    logger.info("[TRADING][SHADOW][VERDICT] %s marked as STALED — no DexScreener price (token delisted or dead)", probe.token_symbol)
                    continue

                if current_price >= verdict.take_profit_tier_1_price and verdict.take_profit_tier_1_hit_at is None:
                    verdict.take_profit_tier_1_hit_at = current_time
                    logger.debug("[TRADING][SHADOW][VERDICT] %s touched TP1 at %.4f", probe.token_symbol, current_price)

                if current_price >= verdict.take_profit_tier_2_price or current_price <= verdict.stop_loss_price:
                    resolving_candidates.append((verdict, current_price))
                else:
                    aware_probed_at = ensure_timezone_aware(probe.probed_at) or current_time
                    age_hours = (current_time - aware_probed_at).total_seconds() / 3600.0

                    if age_hours >= lethargic_cutoff_hours:
                        lethargic_candidates.append((verdict, current_price))

            if resolving_candidates:
                from src.core.structures.structures import Token
                from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens

                resolution_tokens = [
                    Token(
                        symbol=verdict.probe.token_symbol,
                        chain=verdict.probe.blockchain_network,
                        token_address=verdict.probe.token_address,
                        pair_address=verdict.probe.pair_address,
                        dex_id=verdict.probe.dex_id,
                    ) for verdict, _ in resolving_candidates
                ]

                onchain_prices = fetch_onchain_prices_for_tokens(resolution_tokens)
                all_onchain_failed = len(resolving_candidates) > 0 and not onchain_prices

                maximum_slippage = settings.TRADING_MAX_SLIPPAGE
                aberrant_price_tolerance = settings.TRADING_SHADOWING_DEXSCREENER_ABERRANT_PRICE_TOLERANCE

                for verdict, dex_price in resolving_candidates:
                    probe = verdict.probe
                    onchain_price = onchain_prices.get(probe.pair_address)

                    if onchain_price is None or onchain_price <= 0.0:
                        if all_onchain_failed:
                            logger.debug(
                                "[TRADING][SHADOW][VERDICT] Skipping %s — all onchain prices unavailable (RPC failure), will retry next cycle",
                                probe.token_symbol,
                            )
                            continue

                        logger.info("[TRADING][SHADOW][VERDICT] %s marked as STALED — onchain price unrecoverable", probe.token_symbol)
                        self._attach_stale_verdict(verdict, probe, current_time)
                        resolved_count += 1
                        continue

                    low_price, high_price = sorted([onchain_price, dex_price])
                    relative_deviation = (high_price / low_price) - 1.0

                    if relative_deviation > aberrant_price_tolerance:
                        logger.info(
                            "[TRADING][SHADOW][VERDICT] %s marked as STALED — aberrant DexScreener price deviation %.1f%% (onchain=%.12f dex=%.12f, tolerance=%.0f%%)",
                            probe.token_symbol, relative_deviation * 100.0, onchain_price, dex_price, aberrant_price_tolerance * 100.0,
                        )
                        self._attach_stale_verdict(verdict, probe, current_time)
                        resolved_count += 1
                        continue

                    if relative_deviation > maximum_slippage:
                        logger.debug(
                            "[TRADING][SHADOW][VERDICT] Skipping %s — transient slippage %.1f%% (onchain=%.12f dex=%.12f), will retry next cycle",
                            probe.token_symbol, relative_deviation * 100.0, onchain_price, dex_price,
                        )
                        continue

                    if self._evaluate_price_against_thresholds(verdict, probe, onchain_price, current_time):
                        resolved_count += 1
                        logger.debug(
                            "[TRADING][SHADOW][VERDICT] %s resolved — exit=%s pnl=%.2f%% (onchain verified)",
                            probe.token_symbol, verdict.exit_reason, verdict.realized_pnl_percentage,
                        )

            for verdict, dex_price in lethargic_candidates:
                self._attach_lethargic_verdict(verdict, verdict.probe, current_time, dex_price)
                resolved_count += 1
                logger.info("[TRADING][SHADOW][VERDICT] %s marked as LETHARGIC after %d hours", verdict.probe.token_symbol, lethargic_cutoff_hours)

            database_session.commit()
            logger.info("[TRADING][SHADOW][VERDICT] Resolved %d / %d shadow verdicts", resolved_count, len(pending_verdicts))

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
        from src.core.structures.structures import Token
        from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list_sync

        unique_tokens: list[Token] = []
        processed_keys: set[str] = set()

        for probe in probes:
            price_key = self._build_price_key(probe)
            if price_key in processed_keys:
                continue
            processed_keys.add(price_key)
            unique_tokens.append(Token(
                symbol=probe.token_symbol,
                chain=probe.blockchain_network,
                token_address=probe.token_address,
                pair_address=probe.pair_address,
                dex_id=probe.dex_id,
            ))

        if not unique_tokens:
            return {}

        try:
            token_information_list = fetch_dexscreener_token_information_list_sync(unique_tokens)
        except Exception:
            logger.exception("[TRADING][SHADOW][VERDICT] Failed to fetch DexScreener prices for shadow probes")
            return None

        price_map: dict[str, float] = {}
        for token_information in token_information_list:
            price_key = f"{token_information.chain_id}:{token_information.base_token.address}:{token_information.pair_address}"
            if token_information.price_usd is not None and token_information.price_usd > 0.0:
                price_map[price_key] = token_information.price_usd

        return price_map

    def _build_price_key(self, probe: TradingShadowingProbe) -> str:
        return f"{probe.blockchain_network}:{probe.token_address}:{probe.pair_address}"
