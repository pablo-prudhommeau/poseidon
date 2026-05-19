from __future__ import annotations

from typing import Final

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.format_utils import tail
from src.core.utils.math_utils import squash_positive_percentage, is_finite_number
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_MOMENTUM_WEIGHT_5M: Final[float] = 0.6
_MOMENTUM_WEIGHT_1H: Final[float] = 0.4
_MOMENTUM_WEIGHT_6H: Final[float] = 0.25
_MOMENTUM_WEIGHT_24H: Final[float] = 0.1
_MOMENTUM_TOTAL_WEIGHT: Final[float] = _MOMENTUM_WEIGHT_5M + _MOMENTUM_WEIGHT_1H + _MOMENTUM_WEIGHT_6H + _MOMENTUM_WEIGHT_24H


def blend_momentum_percentages(percent_m5: float, percent_h1: float, percent_h6: float, percent_h24: float) -> float:
    squashed_percent_m5 = squash_positive_percentage(percent_m5)
    squashed_percent_h1 = squash_positive_percentage(percent_h1)
    squashed_percent_h6 = squash_positive_percentage(percent_h6)
    squashed_percent_h24 = squash_positive_percentage(percent_h24)

    weighted_sum = (
            _MOMENTUM_WEIGHT_5M * squashed_percent_m5
            + _MOMENTUM_WEIGHT_1H * squashed_percent_h1
            + _MOMENTUM_WEIGHT_6H * squashed_percent_h6
            + _MOMENTUM_WEIGHT_24H * squashed_percent_h24
    )
    return weighted_sum / _MOMENTUM_TOTAL_WEIGHT


def compute_quality_score(candidate: TradingCandidate) -> float:
    market_snapshot = candidate.market_snapshot

    minimum_liquidity_usd = settings.TRADING_MIN_LIQUIDITY_USD
    minimum_volume_m5_usd = settings.TRADING_MIN_VOLUME_5M_USD
    minimum_volume_h1_usd = settings.TRADING_MIN_VOLUME_1H_USD
    minimum_volume_h6_usd = settings.TRADING_MIN_VOLUME_6H_USD
    minimum_volume_h24_usd = settings.TRADING_MIN_VOLUME_24H_USD

    momentum_score = blend_momentum_percentages(
        market_snapshot.price_change_percentage_m5,
        market_snapshot.price_change_percentage_h1,
        market_snapshot.price_change_percentage_h6,
        market_snapshot.price_change_percentage_h24,
    )
    liquidity_component_score = min(1.0, market_snapshot.liquidity_usd / (minimum_liquidity_usd * 4.0))

    volume_m5_component = min(1.0, market_snapshot.volume_m5_usd / (minimum_volume_m5_usd * 4.0))
    volume_h1_component = min(1.0, market_snapshot.volume_h1_usd / (minimum_volume_h1_usd * 4.0))
    volume_h6_component = min(1.0, market_snapshot.volume_h6_usd / (minimum_volume_h6_usd * 4.0))
    volume_h24_component = min(1.0, market_snapshot.volume_h24_usd / (minimum_volume_h24_usd * 4.0))

    volume_component_score = (
            0.4 * volume_m5_component
            + 0.3 * volume_h1_component
            + 0.2 * volume_h6_component
            + 0.1 * volume_h24_component
    )

    return 100.0 * (
            0.45 * momentum_score
            + 0.25 * liquidity_component_score
            + 0.30 * volume_component_score
    )


def _has_valid_intraday_bars(candidate: TradingCandidate) -> bool:
    market_snapshot = candidate.market_snapshot
    return (
            is_finite_number(market_snapshot.price_change_percentage_m5)
            and is_finite_number(market_snapshot.price_change_percentage_h1)
            and is_finite_number(market_snapshot.price_change_percentage_h6)
            and is_finite_number(market_snapshot.price_change_percentage_h24)
    )


def compute_quality_scores(candidates: list[TradingCandidate]) -> None:
    for candidate in candidates:
        candidate.quality_score = compute_quality_score(candidate)

    logger.info("[TRADING][EVALUATOR][QUALITY] Computed quality scores for %d candidates", len(candidates))


def apply_quality_gate(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    minimum_quality_score = settings.TRADING_SCORE_MIN_QUALITY
    retained: list[TradingCandidate] = []

    for candidate in candidates:
        symbol = candidate.token.symbol
        short_address = tail(candidate.token.token_address)

        if candidate.quality_score >= minimum_quality_score:
            if not _has_valid_intraday_bars(candidate):
                logger.debug("[TRADING][EVALUATOR][QUALITY] %s rejected — missing intraday bars", symbol)
                continue

            retained.append(candidate)
            logger.debug("[TRADING][EVALUATOR][QUALITY] %s (%s) passed quality gate with score %.1f", symbol, short_address, candidate.quality_score)
        else:
            logger.debug(
                "[TRADING][EVALUATOR][QUALITY] %s (%s) rejected — score %.1f < %.1f",
                symbol, short_address, candidate.quality_score, minimum_quality_score,
            )

    if not retained:
        logger.info("[TRADING][EVALUATOR][QUALITY] Zero candidates passed the quality gate")
    else:
        logger.info("[TRADING][EVALUATOR][QUALITY] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
