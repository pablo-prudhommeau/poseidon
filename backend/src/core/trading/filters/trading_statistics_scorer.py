from __future__ import annotations

from src.core.trading.scoring.trading_scoring_engine import TradingScoringEngine
from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate, TradingPipelineContext
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_statistics_scorer(candidates: list[TradingCandidate], pipeline_context: TradingPipelineContext) -> list[TradingCandidate]:
    minimum_statistics_score = settings.TRADING_SCORE_MIN_STATISTICS

    if len(candidates) == 1:
        candidates[0].statistics_score = 100.0
        logger.info("[TRADING][FILTER][STATISTICS] %s auto-passed statistics scoring (solitary cohort survivor)", candidates[0].dexscreener_token_information.base_token.symbol)
        return candidates

    engine = TradingScoringEngine().fit_scalers_to_cohort(candidates)
    pipeline_context.scoring_engine = engine

    retained: list[TradingCandidate] = []
    for candidate in candidates:
        statistics_score = engine.compute_statistics_score(candidate)
        candidate.statistics_score = statistics_score

        if statistics_score >= minimum_statistics_score:
            retained.append(candidate)
        else:
            logger.debug(
                "[TRADING][FILTER][STATISTICS] %s — score %.2f < %.2f",
                candidate.dexscreener_token_information.base_token.symbol, statistics_score, minimum_statistics_score,
            )

    if not retained:
        logger.info("[TRADING][FILTER][STATISTICS] Zero candidates after statistics scoring")
    else:
        logger.info("[TRADING][FILTER][STATISTICS] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
