from __future__ import annotations

from src.core.trading.analytics.trading_analytics_recorder import TradingAnalyticsRecorder
from src.core.trading.execution.trading_executor import TradingExecutor
from src.core.trading.execution.trading_order_builder import build_lifi_route_for_live_execution
from src.core.trading.execution.trading_risk_manager import TradingRiskManager
from src.core.trading.filters.trading_age_filter import apply_age_filter
from src.core.trading.filters.trading_ai_scorer import apply_ai_scorer
from src.core.trading.filters.trading_contradictions_filter import apply_contradictions_filter
from src.core.trading.filters.trading_cooldown_filter import apply_cooldown_filter
from src.core.trading.filters.trading_deduplication_filter import apply_deduplication_filter
from src.core.trading.filters.trading_fundamentals_filter import apply_fundamentals_filter
from src.core.trading.filters.trading_liquidity_filter import apply_liquidity_filter
from src.core.trading.filters.trading_momentum_filter import apply_momentum_filter
from src.core.trading.filters.trading_price_deviation_filter import apply_price_deviation_filter
from src.core.trading.filters.trading_quality_scorer import apply_quality_scorer
from src.core.trading.filters.trading_risk_filter import apply_risk_filter
from src.core.trading.filters.trading_statistics_scorer import apply_statistics_scorer
from src.core.trading.filters.trading_volume_filter import apply_volume_filter
from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate, TradingOrderPayload, TradingPipelineContext
from src.core.trading.utils.trading_candidate_utils import (
    fetch_trading_candidates_sync,
    preload_best_prices,
)
from src.core.utils.format_utils import _tail
from src.core.utils.pnl_utils import compute_portfolio_free_cash
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingPipeline:
    def __init__(self) -> None:
        self._executor = TradingExecutor()
        self._risk_manager = TradingRiskManager()

    def run_once(self) -> None:
        logger.info("[TRADING][PIPELINE] Starting new trading cycle")
        try:
            self._execute_pipeline()
        except Exception as exception:
            logger.exception("[TRADING][PIPELINE] Pipeline cycle failed — %s", exception)
        logger.info("[TRADING][PIPELINE] Trading cycle complete")

    def _execute_pipeline(self) -> None:
        pipeline_context = TradingPipelineContext()

        candidates = self._step_fetch_candidates()
        if not candidates:
            return

        candidates = self._step_filter_volume(candidates)
        if not candidates:
            return

        candidates = self._step_filter_liquidity(candidates)
        if not candidates:
            return

        candidates = self._step_filter_fundamentals(candidates)
        if not candidates:
            return

        candidates = self._step_filter_momentum(candidates)
        if not candidates:
            return

        candidates = self._step_filter_age(candidates)
        if not candidates:
            return

        candidates = self._step_score_quality(candidates)
        if not candidates:
            return

        candidates = self._step_truncate_to_trending_top(candidates)
        if not candidates:
            return

        candidates = self._step_deduplication(candidates)
        if not candidates:
            return

        token_price_information_list = preload_best_prices(candidates)
        pipeline_context.token_price_information_list = token_price_information_list

        candidates = self._step_contradictions(candidates, token_price_information_list)
        if not candidates:
            return

        candidates = self._step_statistics_scorer(candidates, pipeline_context)
        if not candidates:
            return

        candidates = self._step_risk_filter(candidates)
        if not candidates:
            return

        candidates = self._step_cooldown(candidates)
        if not candidates:
            return

        candidates = self._step_price_deviation(candidates, token_price_information_list)
        if not candidates:
            return

        candidates = self._step_ai_scorer(candidates, pipeline_context)
        if not candidates:
            return

        self._step_execute(candidates, pipeline_context)

    def _step_fetch_candidates(self) -> list[TradingCandidate]:
        candidates = fetch_trading_candidates_sync()
        logger.info("[TRADING][PIPELINE][FETCH] Fetched %d raw candidates", len(candidates))
        if candidates:
            symbols = [candidate.token.symbol for candidate in candidates]
            logger.debug("[TRADING][PIPELINE][FETCH] Candidates: %s", ", ".join(symbols))
        return candidates

    def _step_filter_volume(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_volume_filter(candidates)

    def _step_filter_liquidity(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_liquidity_filter(candidates)

    def _step_filter_fundamentals(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_fundamentals_filter(candidates)

    def _step_filter_momentum(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_momentum_filter(candidates)

    def _step_filter_age(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_age_filter(candidates)

    def _step_score_quality(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_quality_scorer(candidates)

    def _step_truncate_to_trending_top(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        max_results = settings.TRADING_MAX_RESULTS

        if len(candidates) > max_results:
            candidates = candidates[:max_results]
            logger.info("[TRADING][PIPELINE][TRUNCATE] Truncated to top %d native trending candidates", max_results)

        return candidates

    def _step_deduplication(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_deduplication_filter(candidates)

    def _step_contradictions(self, candidates: list[TradingCandidate], token_price_information_list: list) -> list[TradingCandidate]:
        return apply_contradictions_filter(candidates, token_price_information_list)

    def _step_statistics_scorer(self, candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> list[TradingCandidate]:
        return apply_statistics_scorer(candidates, pipeline_context)

    def _step_risk_filter(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_risk_filter(candidates)

    def _step_cooldown(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_cooldown_filter(candidates)

    def _step_price_deviation(self, candidates: list[TradingCandidate], token_price_information_list: list) -> list[TradingCandidate]:
        return apply_price_deviation_filter(candidates, token_price_information_list)

    def _step_ai_scorer(self, candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> list[TradingCandidate]:
        return apply_ai_scorer(candidates, pipeline_context)

    def _step_execute(self, candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> None:
        free_cash_usd = compute_portfolio_free_cash()
        per_buy_fraction = settings.TRADING_PER_BUY_FRACTION
        min_free_cash = settings.TRADING_MIN_FREE_CASH_USD

        if free_cash_usd < min_free_cash:
            logger.info("[TRADING][PIPELINE][EXECUTE] Insufficient free cash: %.2f < %.2f", free_cash_usd, min_free_cash)
            for rank, candidate in enumerate(candidates, start=1):
                TradingAnalyticsRecorder.persist_and_broadcast_skip(candidate, rank, "NO_CASH")
            return

        executed_count = 0

        for rank, candidate in enumerate(candidates, start=1):
            if free_cash_usd < min_free_cash:
                TradingAnalyticsRecorder.persist_and_broadcast_skip(candidate, rank, "NO_CASH")
                continue

            sizing_multiplier = self._risk_manager.size_multiplier(candidate)
            order_notional = free_cash_usd * per_buy_fraction * sizing_multiplier
            dex_price = candidate.dex_price or candidate.dexscreener_token_information.price_usd or 0.0

            if dex_price <= 0.0:
                TradingAnalyticsRecorder.persist_and_broadcast_skip(candidate, rank, "NO_PRICE")
                continue

            lifi_route = build_lifi_route_for_live_execution(candidate, order_notional)

            candidate.final_computed_score = candidate.entry_score

            free_cash_before = free_cash_usd
            free_cash_after = free_cash_usd - order_notional

            TradingAnalyticsRecorder.persist_and_broadcast(
                candidate,
                rank=rank,
                decision="BUY",
                reason="EXECUTION",
                sizing_multiplier=sizing_multiplier,
                order_notional_usd=order_notional,
                free_cash_before_usd=free_cash_before,
                free_cash_after_usd=free_cash_after,
            )

            order_payload = TradingOrderPayload(
                target_token=candidate.token,
                execution_price=dex_price,
                order_notional=order_notional,
                original_candidate=candidate,
                lifi_routing_path=lifi_route,
            )

            logger.info(
                "[TRADING][PIPELINE][EXECUTE] BUY #%d %s (%s) — notional=%.2f entry=%.2f",
                rank, candidate.token.symbol, _tail(candidate.token.token_address), order_notional, candidate.entry_score,
            )

            buy_succeeded = self._executor.buy(order_payload)

            if buy_succeeded:
                free_cash_usd = free_cash_after
                executed_count += 1
            else:
                logger.warning("[TRADING][PIPELINE][EXECUTE] BUY #%d %s failed — free cash unchanged", rank, candidate.token.symbol)

        logger.info("[TRADING][PIPELINE][EXECUTE] Executed %d buys this cycle", executed_count)
