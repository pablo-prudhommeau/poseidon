from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.analytics.trading_evaluation_recorder import TradingEvaluationRecorder
from src.core.trading.evaluators.trading_age_filter import apply_age_filter
from src.core.trading.evaluators.trading_ai_scorer import apply_ai_scorer
from src.core.trading.evaluators.trading_contradictions_filter import apply_contradictions_filter
from src.core.trading.evaluators.trading_cooldown_filter import apply_cooldown_filter
from src.core.trading.evaluators.trading_deduplication_filter import apply_deduplication_filter
from src.core.trading.evaluators.trading_fundamentals_filter import apply_fundamentals_filter
from src.core.trading.evaluators.trading_liquidity_filter import apply_liquidity_filter
from src.core.trading.evaluators.trading_momentum_filter import apply_momentum_filter
from src.core.trading.evaluators.trading_price_deviation_filter import apply_price_deviation_filter
from src.core.trading.evaluators.trading_quality_scorer import apply_quality_scorer
from src.core.trading.evaluators.trading_risk_filter import apply_risk_filter
from src.core.trading.evaluators.trading_shadowing_decile_toxicity_filter import apply_shadowing_decile_toxicity_filter
from src.core.trading.evaluators.trading_shadowing_notional_booster import apply_shadowing_notional_boost
from src.core.trading.evaluators.trading_shadowing_toxic_exposure_filter import apply_shadowing_toxic_exposure_filter
from src.core.trading.evaluators.trading_volume_filter import apply_volume_filter
from src.core.trading.execution.trading_executor import TradingExecutor
from src.core.trading.execution.trading_order_builder import build_lifi_route_for_live_execution
from src.core.trading.execution.trading_risk_manager import TradingRiskManager
from src.core.trading.shadowing.shadow_analytics_intelligence import compute_shadow_intelligence_snapshot
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
        except RuntimeError as exception:
            if "interpreter shutdown" in str(exception):
                logger.warning("[TRADING][PIPELINE] Pipeline cycle aborted due to application shutdown")
            else:
                logger.exception("[TRADING][PIPELINE] Pipeline cycle failed — %s", exception)
        except Exception as exception:
            logger.exception("[TRADING][PIPELINE] Pipeline cycle failed — %s", exception)
        logger.info("[TRADING][PIPELINE] Trading cycle complete")

    def _execute_pipeline(self) -> None:
        pipeline_context = TradingPipelineContext()

        candidates = self._step_fetch_candidates()
        if not candidates:
            return

        candidates = self._step_filter_allowed_chains(candidates)
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

        candidates = self._step_deduplication(candidates)
        if not candidates:
            return

        token_price_information_list = preload_best_prices(candidates)
        pipeline_context.token_price_information_list = token_price_information_list

        candidates = self._step_contradictions(candidates, token_price_information_list)
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

        shadow_snapshot = self._step_load_shadow_intelligence()
        pipeline_context.shadow_intelligence_snapshot = shadow_snapshot

        if not shadow_snapshot.is_activated:
            logger.info("[TRADING][PIPELINE][GATE] Shadow intelligence in LEARNING phase — blocking live execution")
            for rank, candidate in enumerate(candidates, start=1):
                TradingEvaluationRecorder.persist_and_broadcast_skip(candidate, rank, "LEARNING_PHASE")
            return

        candidates = self._step_shadowing_decile_toxicity_filter(candidates, shadow_snapshot)
        if not candidates:
            return

        candidates = self._step_shadowing_toxic_exposure_filter(candidates, shadow_snapshot)
        if not candidates:
            return

        self._step_shadowing_notional_boost(candidates, shadow_snapshot)

        self._step_execute(candidates, pipeline_context)

    def _step_fetch_candidates(self) -> list[TradingCandidate]:
        candidates = fetch_trading_candidates_sync()
        logger.info("[TRADING][PIPELINE][FETCH] Fetched %d raw candidates", len(candidates))
        if candidates:
            symbols = [candidate.token.symbol for candidate in candidates]
            logger.debug("[TRADING][PIPELINE][FETCH] Candidates: %s", ", ".join(symbols))
        return candidates

    def _step_filter_allowed_chains(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        allowed_chains = set(settings.TRADING_ALLOWED_CHAINS)
        retained: list[TradingCandidate] = []
        for candidate in candidates:
            chain_identifier = (candidate.dexscreener_token_information.chain_id or "").strip().lower()
            if chain_identifier in allowed_chains:
                retained.append(candidate)
            else:
                logger.debug(
                    "[TRADING][PIPELINE][CHAIN_FILTER] %s rejected — chain %s not in allowed list %s",
                    candidate.token.symbol, chain_identifier, allowed_chains,
                )

        if len(retained) < len(candidates):
            logger.info(
                "[TRADING][PIPELINE][CHAIN_FILTER] Retained %d / %d candidates (allowed chains: %s)",
                len(retained), len(candidates), ", ".join(sorted(allowed_chains)),
            )
        return retained

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

    def _step_deduplication(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_deduplication_filter(candidates)

    def _step_contradictions(self, candidates: list[TradingCandidate], token_price_information_list: list) -> list[TradingCandidate]:
        return apply_contradictions_filter(candidates, token_price_information_list)

    def _step_risk_filter(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_risk_filter(candidates)

    def _step_cooldown(self, candidates: list[TradingCandidate]) -> list[TradingCandidate]:
        return apply_cooldown_filter(candidates)

    def _step_price_deviation(self, candidates: list[TradingCandidate], token_price_information_list: list) -> list[TradingCandidate]:
        return apply_price_deviation_filter(candidates, token_price_information_list)

    def _step_ai_scorer(self, candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> list[TradingCandidate]:
        return apply_ai_scorer(candidates, pipeline_context)

    def _step_load_shadow_intelligence(self):
        from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceSnapshot
        try:
            snapshot = compute_shadow_intelligence_snapshot()
            logger.info(
                "[TRADING][PIPELINE][SHADOW] Shadow intelligence loaded — activated=%s, outcomes=%d",
                snapshot.is_activated, snapshot.total_outcomes_analyzed,
            )
            return snapshot
        except Exception:
            logger.exception("[TRADING][PIPELINE][SHADOW] Failed to load shadow intelligence, using empty snapshot")
            return ShadowIntelligenceSnapshot(metric_snapshots=[], total_outcomes_analyzed=0, is_activated=False)

    def _step_shadowing_decile_toxicity_filter(self, candidates: list[TradingCandidate], shadow_snapshot) -> list[TradingCandidate]:
        return apply_shadowing_decile_toxicity_filter(candidates, shadow_snapshot)

    def _step_shadowing_toxic_exposure_filter(self, candidates: list[TradingCandidate], shadow_snapshot) -> list[TradingCandidate]:
        return apply_shadowing_toxic_exposure_filter(candidates, shadow_snapshot)

    def _step_shadowing_notional_boost(self, candidates: list[TradingCandidate], shadow_snapshot) -> None:
        apply_shadowing_notional_boost(candidates, shadow_snapshot)

    def _step_execute(self, candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> None:
        from sqlalchemy import select, func
        from src.persistence.db import get_database_session
        from src.persistence.models import TradingPosition, PositionPhase

        with get_database_session() as database_session:
            current_open_count = database_session.execute(
                select(func.count(TradingPosition.id))
                .where(TradingPosition.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]))
            ).scalar_one_or_none() or 0

        free_cash_usd = compute_portfolio_free_cash()
        per_buy_fraction = settings.TRADING_PER_BUY_FRACTION
        min_free_cash = settings.TRADING_MIN_FREE_CASH_USD
        max_positions = settings.TRADING_MAX_OPEN_POSITIONS

        if free_cash_usd < min_free_cash:
            logger.info("[TRADING][PIPELINE][EXECUTE] Insufficient free cash: %.2f < %.2f", free_cash_usd, min_free_cash)
            for rank, candidate in enumerate(candidates, start=1):
                TradingEvaluationRecorder.persist_and_broadcast_skip(candidate, rank, "NO_CASH")
            return

        executed_count = 0
        max_positions_logged = False

        for rank, candidate in enumerate(candidates, start=1):
            if current_open_count >= max_positions:
                if not max_positions_logged:
                    logger.info("[TRADING][PIPELINE][EXECUTE] Max positions limit reached (%d/%d) — skipping remaining", current_open_count, max_positions)
                    max_positions_logged = True
                TradingEvaluationRecorder.persist_and_broadcast_skip(candidate, rank, "MAX_POSITIONS")
                continue

            if free_cash_usd < min_free_cash:
                TradingEvaluationRecorder.persist_and_broadcast_skip(candidate, rank, "NO_CASH")
                continue

            base_sizing_multiplier = self._risk_manager.size_multiplier(candidate)
            effective_sizing_multiplier = base_sizing_multiplier * candidate.shadow_notional_multiplier
            order_notional = free_cash_usd * per_buy_fraction * effective_sizing_multiplier
            dex_price = candidate.dex_price or candidate.dexscreener_token_information.price_usd or 0.0

            lifi_route = build_lifi_route_for_live_execution(candidate, order_notional)

            free_cash_before = free_cash_usd
            free_cash_after = free_cash_usd - order_notional

            evaluation_id = TradingEvaluationRecorder.persist_and_broadcast(
                candidate,
                rank=rank,
                decision="BUY",
                reason="EXECUTION",
                sizing_multiplier=effective_sizing_multiplier,
                order_notional_usd=order_notional,
                free_cash_before_usd=free_cash_before,
                free_cash_after_usd=free_cash_after,
            )

            order_payload = TradingOrderPayload(
                target_token=candidate.token,
                execution_price=dex_price,
                order_notional=order_notional,
                original_candidate=candidate,
                origin_evaluation_id=evaluation_id,
                lifi_routing_path=lifi_route,
            )

            logger.info(
                "[TRADING][PIPELINE][EXECUTE] BUY #%d %s (%s) — notional=%.2f quality=%.2f shadow_mult=%.2f",
                rank, candidate.token.symbol, _tail(candidate.token.token_address), order_notional, candidate.ai_adjusted_quality_score, candidate.shadow_notional_multiplier,
            )

            buy_succeeded = self._executor.buy(order_payload)

            if buy_succeeded:
                free_cash_usd = free_cash_after
                executed_count += 1
                current_open_count += 1
            else:
                logger.warning("[TRADING][PIPELINE][EXECUTE] BUY #%d %s failed — free cash unchanged", rank, candidate.token.symbol)

        logger.info("[TRADING][PIPELINE][EXECUTE] Executed %d buys this cycle", executed_count)
