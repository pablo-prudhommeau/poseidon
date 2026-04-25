from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate, TradingPipelineContext
from src.core.utils.math_utils import _clamp
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_ai_scorer(candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> list[TradingCandidate]:
    if not settings.TRADING_AI_ENABLED:
        logger.debug("[TRADING][EVALUATOR][AI] AI scoring is disabled, passing all candidates through")
        for candidate in candidates:
            candidate.ai_adjusted_quality_score = candidate.quality_score
        return candidates

    from src.core.trading.ai.trading_chart_signal_provider import TradingChartAiSignalProvider

    chart_ai = TradingChartAiSignalProvider()
    ai_budget_remaining = max(0, settings.TRADING_AI_TOP_K_CANDIDATES)
    delta_multiplier = settings.TRADING_AI_DELTA_MULTIPLIER
    maximum_absolute_delta_points = settings.TRADING_AI_MAX_ABSOLUTE_DELTA_POINTS

    for candidate in sorted(candidates, key=lambda candidate_item: candidate_item.quality_score, reverse=True):
        ai_delta = 0.0
        ai_probability = 0.0

        if ai_budget_remaining > 0:
            try:
                signal = chart_ai.predict_market_signal(
                    symbol=candidate.token.symbol,
                    chain_name=candidate.token.chain or None,
                    pair_address=candidate.token.pair_address or None,
                    timeframe_minutes=settings.TRADING_AI_TIMEFRAME_MINUTES,
                    lookback_minutes=settings.TRADING_AI_LOOKBACK_MINUTES,
                    token_age_hours=candidate.dexscreener_token_information.age_hours,
                )
            except Exception:
                logger.exception("[TRADING][EVALUATOR][AI] Chart AI failed for %s", candidate.token.symbol)
                signal = None
            ai_budget_remaining -= 1

            if signal is not None:
                ai_delta = signal.quality_score_delta
                ai_probability = signal.take_profit_one_probability

        scaled_delta = ai_delta * delta_multiplier
        bounded_delta = _clamp(scaled_delta, -maximum_absolute_delta_points, +maximum_absolute_delta_points)
        adjusted_quality_score = _clamp(candidate.quality_score + bounded_delta, 0.0, 100.0)

        candidate.ai_quality_delta = ai_delta
        candidate.ai_buy_probability = ai_probability
        candidate.ai_adjusted_quality_score = adjusted_quality_score

        logger.debug(
            "[TRADING][EVALUATOR][AI] %s — quality=%.2f aiΔ=%.2f adjusted=%.2f prob=%.3f",
            candidate.token.symbol, candidate.quality_score, bounded_delta, adjusted_quality_score, ai_probability,
        )

    logger.info("[TRADING][EVALUATOR][AI] Processed %d candidates", len(candidates))
    return candidates
