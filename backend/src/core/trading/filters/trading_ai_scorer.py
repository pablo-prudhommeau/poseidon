from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate, TradingPipelineContext
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_ai_scorer(candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> list[TradingCandidate]:
    if not settings.TRADING_AI_ENABLED:
        logger.debug("[TRADING][FILTER][AI] AI scoring is disabled, passing all candidates through")
        for candidate in candidates:
            candidate.entry_score = candidate.statistics_score
        return candidates

    from src.core.trading.ai.trading_chart_signal_provider import TradingChartAiSignalProvider
    from src.core.trading.scoring.trading_scoring_engine import TradingScoringEngine

    scoring_engine: TradingScoringEngine = pipeline_context.scoring_engine
    chart_ai = TradingChartAiSignalProvider()
    ai_budget_remaining = max(0, settings.TRADING_AI_TOP_K_CANDIDATES)
    minimum_entry_score = settings.TRADING_SCORE_MIN_ENTRY

    retained: list[TradingCandidate] = []

    for candidate in sorted(candidates, key=lambda candidate_item: candidate_item.statistics_score, reverse=True):
        entry_score = candidate.statistics_score
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
                logger.exception("[TRADING][FILTER][AI] Chart AI failed for %s", candidate.token.symbol)
                signal = None
            ai_budget_remaining -= 1

            if signal is not None:
                ai_delta = signal.quality_score_delta
                ai_probability = signal.take_profit_one_probability
                entry_score = scoring_engine.apply_artificial_intelligence_adjustment(candidate.statistics_score, ai_delta)

        candidate.ai_quality_delta = ai_delta
        candidate.ai_buy_probability = ai_probability
        candidate.entry_score = entry_score

        if entry_score >= minimum_entry_score:
            retained.append(candidate)
            logger.debug(
                "[TRADING][FILTER][AI] %s — entry=%.2f (stat=%.2f aiΔ=%.2f prob=%.3f)",
                candidate.token.symbol, entry_score, candidate.statistics_score, ai_delta, ai_probability,
            )
        else:
            from src.core.trading.analytics.trading_analytics_recorder import TradingAnalyticsRecorder
            TradingAnalyticsRecorder.persist_and_broadcast(candidate, rank=len(retained) + 1, decision="SKIP", reason="ENTRY_SCORE_BELOW_MIN")
            logger.debug(
                "[TRADING][FILTER][AI] %s dropped — entry=%.2f < %.2f (stat=%.2f aiΔ=%.2f prob=%.3f)",
                candidate.token.symbol, entry_score, minimum_entry_score, candidate.statistics_score, ai_delta, ai_probability,
            )

    if not retained:
        logger.info("[TRADING][FILTER][AI] Zero candidates after AI scoring")
    else:
        logger.info("[TRADING][FILTER][AI] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
