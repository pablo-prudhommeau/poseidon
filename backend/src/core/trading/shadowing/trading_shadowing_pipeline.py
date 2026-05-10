from __future__ import annotations

from datetime import datetime

from src.configuration.config import settings
from src.core.trading.evaluators.trading_quality_scorer import _evaluate_quality
from src.core.trading.trading_service import fetch_trading_candidates_sync
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.db import get_database_session
from src.persistence.models import TradingShadowingProbe, TradingShadowingVerdict

logger = get_application_logger(__name__)


class TradingShadowingPipeline:
    def __init__(self) -> None:
        pass

    def run_once(self) -> None:
        if not settings.TRADING_SHADOWING_ENABLED:
            logger.debug("[TRADING][SHADOW][PIPELINE] Shadow tracking is disabled, skipping")
            return

        logger.info("[TRADING][SHADOW][PIPELINE] Starting shadow tracking cycle")
        try:
            self._execute_shadow_pipeline()
        except Exception as exception:
            logger.exception("[TRADING][SHADOW][PIPELINE] Shadow tracking cycle failed — %s", exception)
        logger.info("[TRADING][SHADOW][PIPELINE] Shadow tracking cycle complete")

    def _execute_shadow_pipeline(self) -> None:
        candidates = fetch_trading_candidates_sync()
        if not candidates:
            logger.info("[TRADING][SHADOW][PIPELINE] No candidates fetched")
            return

        candidates = self._filter_allowed_chains(candidates)
        if not candidates:
            return

        current_time = get_current_local_datetime()

        fixed_notional = settings.TRADING_SHADOWING_FIXED_NOTIONAL_USD
        cooldown_minutes = settings.TRADING_SHADOWING_TOKEN_COOLDOWN_MINUTES
        shadow_probe_count = 0
        cooldown_skip_count = 0

        from datetime import timedelta
        from src.persistence.dao.trading.shadowing_probe_dao import TradingShadowingProbeDao

        cooldown_threshold = current_time - timedelta(minutes=cooldown_minutes)
        token_addresses = [c.dexscreener_token_information.base_token.address for c in candidates]

        with get_database_session() as database_session:
            probe_dao = TradingShadowingProbeDao(database_session)
            recent_probes = probe_dao.retrieve_recent_probes_by_tokens(token_addresses, cooldown_threshold)
            cooldown_addresses = {probe.token_address for probe in recent_probes}

        for rank, candidate in enumerate(candidates, start=1):
            token_address = candidate.dexscreener_token_information.base_token.address
            if token_address in cooldown_addresses:
                cooldown_skip_count += 1
                continue

            quality_result = _evaluate_quality(candidate)
            candidate.quality_score = quality_result.score
            candidate.ai_adjusted_quality_score = quality_result.score

            if not quality_result.is_admissible:
                continue

            entry_price = candidate.dexscreener_token_information.price_usd
            if not entry_price or entry_price <= 0.0:
                continue

            tp1_price = entry_price * (1.0 + settings.TRADING_TP1_EXIT_FRACTION)
            tp2_price = entry_price * (1.0 + settings.TRADING_TP2_EXIT_FRACTION)
            stop_loss_price = entry_price * (1.0 - settings.TRADING_STOP_LOSS_FRACTION)

            self._persist_shadow_probe(
                candidate=candidate,
                rank=rank,
                notional=fixed_notional,
                tp1_price=tp1_price,
                tp2_price=tp2_price,
                stop_loss_price=stop_loss_price,
                current_time=current_time,
            )
            cooldown_addresses.add(token_address)
            shadow_probe_count += 1

        logger.info(
            "[TRADING][SHADOW][PIPELINE] Recorded %d shadow probes from %d candidates (%d skipped by cooldown)",
            shadow_probe_count, len(candidates), cooldown_skip_count,
        )

    def _filter_allowed_chains(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        allowed_chains = set(settings.TRADING_ALLOWED_CHAINS)
        retained = [
            candidate for candidate in candidates
            if candidate.dexscreener_token_information.chain_id.value in allowed_chains
        ]
        if len(retained) < len(candidates):
            logger.debug("[TRADING][SHADOW][PIPELINE] Chain filter retained %d / %d", len(retained), len(candidates))
        return retained

    def _persist_shadow_probe(
            self,
            candidate: TradingCandidate,
            rank: int,
            notional: float,
            tp1_price: float,
            tp2_price: float,
            stop_loss_price: float,
            current_time: datetime,
    ) -> None:
        token_information = candidate.dexscreener_token_information
        base_token = token_information.base_token
        volume = token_information.volume
        liquidity = token_information.liquidity
        price_change = token_information.price_change
        transactions = token_information.transactions

        probe = TradingShadowingProbe(
            token_symbol=base_token.symbol.upper(),
            blockchain_network=token_information.chain_id.value,
            token_address=str(base_token.address),
            pair_address=str(token_information.pair_address),
            dex_id=str(token_information.dex_id),
            entry_price_usd=token_information.price_usd or 0.0,
            candidate_rank=rank,
            quality_score=candidate.quality_score,
            token_age_hours=token_information.age_hours,
            volume_m5_usd=volume.m5 if volume and volume.m5 is not None else 0.0,
            volume_h1_usd=volume.h1 if volume and volume.h1 is not None else 0.0,
            volume_h6_usd=volume.h6 if volume and volume.h6 is not None else 0.0,
            volume_h24_usd=volume.h24 if volume and volume.h24 is not None else 0.0,
            liquidity_usd=liquidity.usd if liquidity and liquidity.usd is not None else 0.0,
            price_change_percentage_m5=price_change.m5 if price_change and price_change.m5 is not None else 0.0,
            price_change_percentage_h1=price_change.h1 if price_change and price_change.h1 is not None else 0.0,
            price_change_percentage_h6=price_change.h6 if price_change and price_change.h6 is not None else 0.0,
            price_change_percentage_h24=price_change.h24 if price_change and price_change.h24 is not None else 0.0,
            transaction_count_m5=transactions.m5.total_transactions if transactions and transactions.m5 else 0,
            transaction_count_h1=transactions.h1.total_transactions if transactions and transactions.h1 else 0,
            transaction_count_h6=transactions.h6.total_transactions if transactions and transactions.h6 else 0,
            transaction_count_h24=transactions.h24.total_transactions if transactions and transactions.h24 else 0,
            buy_to_sell_ratio=self._compute_buy_to_sell_ratio(transactions),
            market_cap_usd=token_information.market_cap or 0.0,
            fully_diluted_valuation_usd=token_information.fully_diluted_valuation or 0.0,
            dexscreener_boost=token_information.boost or 0.0,
            order_notional_value_usd=notional,
            probed_at=current_time,
        )

        probe.verdict = TradingShadowingVerdict(
            take_profit_tier_1_price=tp1_price,
            take_profit_tier_2_price=tp2_price,
            stop_loss_price=stop_loss_price,
        )

        with get_database_session() as database_session:
            database_session.add(probe)

        logger.debug("[TRADING][SHADOW][PERSIST] Recorded shadow probe for %s at price %.10f", base_token.symbol, token_information.price_usd or 0.0)

    def _compute_buy_to_sell_ratio(self, transactions) -> float:
        if not transactions or not (transactions.h1 or transactions.h24):
            return 0.5
        reference_bucket = transactions.h1 if transactions.h1 else transactions.h24
        total_transaction_count = reference_bucket.buys + reference_bucket.sells
        if total_transaction_count <= 0:
            return 0.5
        return reference_bucket.buys / total_transaction_count
