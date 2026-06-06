from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.math_utils import clamp
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _pass_candidates_through_without_chart_ai_vision_adjustment(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    for candidate in candidates:
        candidate.ai_analysis.adjusted_quality_score = candidate.quality_score
    return sorted(candidates, key=lambda candidate_item: candidate_item.ai_analysis.adjusted_quality_score, reverse=True)


def apply_ai_scorer(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    if not settings.TRADING_CHART_AI_VISION_ENABLED:
        logger.debug("[TRADING][EVALUATOR][CHART_AI_VISION] Chart AI vision scoring is disabled, passing all candidates through")
        return _pass_candidates_through_without_chart_ai_vision_adjustment(candidates)

    from src.core.trading.ai.trading_chart_signal_provider import TradingChartAiSignalProvider

    chart_ai_vision_provider = TradingChartAiSignalProvider()
    ai_budget_remaining = max(0, settings.TRADING_CHART_AI_VISION_TOP_K_CANDIDATES)
    delta_multiplier = settings.TRADING_CHART_AI_VISION_DELTA_MULTIPLIER
    maximum_absolute_delta_points = settings.TRADING_CHART_AI_VISION_MAX_ABSOLUTE_DELTA_POINTS

    for candidate in sorted(candidates, key=lambda candidate_item: candidate_item.quality_score, reverse=True):
        ai_delta = 0.0
        ai_probability = 0.0

        if ai_budget_remaining > 0:
            try:
                signal = chart_ai_vision_provider.predict_market_signal(
                    symbol=candidate.token.symbol,
                    chain=candidate.token.chain,
                    pair_address=candidate.token.pair_address or None,
                    timeframe_minutes=settings.TRADING_CHART_AI_VISION_TIMEFRAME_MINUTES,
                    lookback_minutes=settings.TRADING_CHART_AI_VISION_LOOKBACK_MINUTES,
                    token_age_hours=candidate.market_snapshot.token_age_hours,
                )
            except Exception:
                logger.exception("[TRADING][EVALUATOR][CHART_AI_VISION] Chart AI vision failed for %s", candidate.token.symbol)
                signal = None
            ai_budget_remaining -= 1

            if signal is not None:
                ai_delta = signal.quality_score_delta
                ai_probability = signal.take_profit_one_probability

        scaled_delta = ai_delta * delta_multiplier
        bounded_delta = clamp(scaled_delta, -maximum_absolute_delta_points, +maximum_absolute_delta_points)
        adjusted_quality_score = clamp(candidate.quality_score + bounded_delta, 0.0, 100.0)

        candidate.ai_analysis.quality_delta = ai_delta
        candidate.ai_analysis.buy_probability = ai_probability
        candidate.ai_analysis.adjusted_quality_score = adjusted_quality_score

        logger.debug(
            "[TRADING][EVALUATOR][CHART_AI_VISION] %s — quality=%.2f aiΔ=%.2f adjusted=%.2f prob=%.3f",
            candidate.token.symbol, candidate.quality_score, bounded_delta, adjusted_quality_score, ai_probability,
        )

    logger.info("[TRADING][EVALUATOR][CHART_AI_VISION] Processed %d candidates", len(candidates))
    return sorted(candidates, key=lambda candidate_item: candidate_item.ai_analysis.adjusted_quality_score, reverse=True)
