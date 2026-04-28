from __future__ import annotations

from datetime import datetime

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
            current_prices = self._fetch_current_prices(probes)
            current_time = get_current_local_datetime()
            stale_cutoff_hours = settings.TRADING_SHADOWING_STALE_HOURS
            lethargic_cutoff_hours = settings.TRADING_SHADOWING_LETHARGIC_HOURS
            resolved_count = 0

            resolving_candidates: list[tuple[TradingShadowingVerdict, float]] = []
            lethargic_candidates: list[tuple[TradingShadowingVerdict, float]] = []

            for verdict in pending_verdicts:
                probe = verdict.probe
                current_price = current_prices.get(self._build_price_key(probe))

                if current_price is None:
                    aware_probed_at = ensure_timezone_aware(probe.probed_at) or current_time
                    age_hours = (current_time - aware_probed_at).total_seconds() / 3600.0
                    if age_hours >= stale_cutoff_hours:
                        self._attach_stale_verdict(verdict, probe, current_time)
                        resolved_count += 1
                        logger.info("[TRADING][SHADOW][VERDICT] %s marked as STALED after %d hours", probe.token_symbol, stale_cutoff_hours)
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
                from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_positions
                from src.persistence.models import TradingPosition
                
                transient_positions = [
                    TradingPosition(
                        token_symbol=v.probe.token_symbol,
                        blockchain_network=v.probe.blockchain_network,
                        token_address=v.probe.token_address,
                        pair_address=v.probe.pair_address,
                        dex_id=""
                    ) for v, _ in resolving_candidates
                ]
                
                onchain_prices = fetch_onchain_prices_for_positions(transient_positions)
                maximum_price_multiplier = settings.TRADING_MAX_PRICE_DEVIATION_MULTIPLIER

                for verdict, dex_price in resolving_candidates:
                    probe = verdict.probe
                    onchain_price = onchain_prices.get(probe.pair_address)

                    if onchain_price is None or onchain_price <= 0.0:
                        logger.warning("[TRADING][SHADOW][VERDICT] Skip: unable to verify onchain price for %s to confirm resolution. Marking as STALED.", probe.token_symbol)
                        self._attach_stale_verdict(verdict, probe, current_time)
                        resolved_count += 1
                        continue

                    low_price, high_price = sorted([onchain_price, dex_price])
                    if (high_price / low_price) > maximum_price_multiplier:
                        logger.warning(
                            "[TRADING][SHADOW][VERDICT] Skip: price mismatch glitch for %s — onchain=%.12f dexscreener=%.12f (>×%.1f). Marking as STALED.",
                            probe.token_symbol, onchain_price, dex_price, maximum_price_multiplier,
                        )
                        self._attach_stale_verdict(verdict, probe, current_time)
                        resolved_count += 1
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

    def _fetch_current_prices(self, probes: list[TradingShadowingProbe]) -> dict[str, float]:
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
                dex_id="",
            ))

        if not unique_tokens:
            return {}

        try:
            token_information_list = fetch_dexscreener_token_information_list_sync(unique_tokens)
        except Exception:
            logger.exception("[TRADING][SHADOW][VERDICT] Failed to fetch current prices for shadow probes")
            return {}

        price_map: dict[str, float] = {}
        for token_information in token_information_list:
            price_key = f"{token_information.chain_id}:{token_information.base_token.address}:{token_information.pair_address}"
            if token_information.price_usd is not None and token_information.price_usd > 0.0:
                price_map[price_key] = token_information.price_usd

        return price_map

    def _build_price_key(self, probe: TradingShadowingProbe) -> str:
        return f"{probe.blockchain_network}:{probe.token_address}:{probe.pair_address}"
