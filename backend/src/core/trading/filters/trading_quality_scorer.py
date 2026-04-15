from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.scoring.trading_scoring_engine import blend_momentum_percentages, compute_buy_sell_score
from src.core.trading.trading_structures import TradingCandidate, TradingQualityContext, TradingQualityResult
from src.core.trading.utils.trading_candidate_utils import is_finite_number
from src.core.utils.format_utils import _tail
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _evaluate_quality(candidate: TradingCandidate) -> TradingQualityResult:
    token_information = candidate.dexscreener_token_information
    base_token = token_information.base_token

    liquidity_usd = token_information.liquidity.usd if token_information.liquidity and token_information.liquidity.usd is not None else 0.0

    volume_m5_usd = token_information.volume.m5 if token_information.volume and token_information.volume.m5 is not None else 0.0
    volume_h1_usd = token_information.volume.h1 if token_information.volume and token_information.volume.h1 is not None else 0.0
    volume_h6_usd = token_information.volume.h6 if token_information.volume and token_information.volume.h6 is not None else 0.0
    volume_h24_usd = token_information.volume.h24 if token_information.volume and token_information.volume.h24 is not None else 0.0

    percent_m5 = token_information.price_change.m5 if token_information.price_change and token_information.price_change.m5 is not None else 0.0
    percent_h1 = token_information.price_change.h1 if token_information.price_change and token_information.price_change.h1 is not None else 0.0
    percent_h6 = token_information.price_change.h6 if token_information.price_change and token_information.price_change.h6 is not None else 0.0
    percent_h24 = token_information.price_change.h24 if token_information.price_change and token_information.price_change.h24 is not None else 0.0

    order_flow_score = compute_buy_sell_score(token_information.transactions)

    minimum_liquidity_usd = settings.TRADING_MIN_LIQUIDITY_USD
    minimum_volume_m5_usd = settings.TRADING_MIN_VOLUME_5M_USD
    minimum_volume_h1_usd = settings.TRADING_MIN_VOLUME_1H_USD
    minimum_volume_h6_usd = settings.TRADING_MIN_VOLUME_6H_USD
    minimum_volume_h24_usd = settings.TRADING_MIN_VOLUME_24H_USD

    quality_context = TradingQualityContext(
        liquidity_usd=liquidity_usd,
        volume_m5_usd=volume_m5_usd,
        volume_h1_usd=volume_h1_usd,
        volume_h6_usd=volume_h6_usd,
        volume_h24_usd=volume_h24_usd,
        age_hours=token_information.age_hours,
        percent_m5=percent_m5,
        percent_h1=percent_h1,
        percent_h6=percent_h6,
        percent_h24=percent_h24,
        momentum_score=0.0,
        liquidity_score=0.0,
        volume_score=0.0,
        order_flow_score=order_flow_score,
    )

    if liquidity_usd < minimum_liquidity_usd:
        logger.debug("[TRADING][FILTER][QUALITY] %s rejected — insufficient liquidity %.0f < %.0f", base_token.symbol, liquidity_usd, minimum_liquidity_usd)
        return TradingQualityResult(is_admissible=False, score=0.0, rejection_reason="insufficient_liquidity", context=quality_context)

    if volume_h24_usd < minimum_volume_h24_usd:
        logger.debug("[TRADING][FILTER][QUALITY] %s rejected — insufficient volume_24h %.0f < %.0f", base_token.symbol, volume_h24_usd, minimum_volume_h24_usd)
        return TradingQualityResult(is_admissible=False, score=0.0, rejection_reason="insufficient_volume", context=quality_context)

    momentum_score = blend_momentum_percentages(percent_m5, percent_h1, percent_h6, percent_h24)
    liquidity_component_score = min(1.0, liquidity_usd / (minimum_liquidity_usd * 4.0))

    volume_m5_component = min(1.0, volume_m5_usd / (minimum_volume_m5_usd * 4.0))
    volume_h1_component = min(1.0, volume_h1_usd / (minimum_volume_h1_usd * 4.0))
    volume_h6_component = min(1.0, volume_h6_usd / (minimum_volume_h6_usd * 4.0))
    volume_h24_component = min(1.0, volume_h24_usd / (minimum_volume_h24_usd * 4.0))

    volume_component_score = (
            0.4 * volume_m5_component
            + 0.3 * volume_h1_component
            + 0.2 * volume_h6_component
            + 0.1 * volume_h24_component
    )

    quality_score = 100.0 * (
            0.45 * momentum_score
            + 0.25 * liquidity_component_score
            + 0.30 * volume_component_score
    )

    quality_context.momentum_score = momentum_score
    quality_context.liquidity_score = liquidity_component_score
    quality_context.volume_score = volume_component_score

    return TradingQualityResult(is_admissible=True, score=quality_score, rejection_reason="none", context=quality_context)


def _has_valid_intraday_bars(candidate: TradingCandidate) -> bool:
    price_change = candidate.dexscreener_token_information.price_change
    if not price_change:
        return False

    return (
            is_finite_number(price_change.m5)
            and is_finite_number(price_change.h1)
            and is_finite_number(price_change.h6)
            and is_finite_number(price_change.h24)
    )


def apply_quality_scorer(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    if not candidates:
        logger.info("[TRADING][FILTER][QUALITY] Empty candidate list, skipping")
        return []

    minimum_quality_score = settings.TRADING_SCORE_MIN_QUALITY
    retained: list[TradingCandidate] = []

    for candidate in candidates:
        quality_result = _evaluate_quality(candidate=candidate)
        candidate.quality_score = quality_result.score

        base_token = candidate.dexscreener_token_information.base_token
        short_address = _tail(base_token.address)

        if quality_result.is_admissible and quality_result.score >= minimum_quality_score:
            if not _has_valid_intraday_bars(candidate):
                logger.debug("[TRADING][FILTER][QUALITY] %s rejected — missing intraday bars", base_token.symbol)
                continue

            retained.append(candidate)
            logger.debug("[TRADING][FILTER][QUALITY] %s (%s) passed with score %.1f", base_token.symbol, short_address, quality_result.score)
        else:
            reason = quality_result.rejection_reason if not quality_result.is_admissible else "insufficient_score"
            logger.debug(
                "[TRADING][FILTER][QUALITY] %s (%s) rejected — score %.1f < %.1f, reason: %s",
                base_token.symbol, short_address, quality_result.score, minimum_quality_score, reason,
            )

    if not retained:
        logger.info("[TRADING][FILTER][QUALITY] Zero candidates passed the quality gate")
    else:
        logger.info("[TRADING][FILTER][QUALITY] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
