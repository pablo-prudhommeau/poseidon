from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.format_utils import tail
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_fundamentals_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    minimum_fdv_usd = settings.TRADING_MIN_FDV_USD
    maximum_fdv_usd = settings.TRADING_MAX_FDV_USD
    minimum_market_cap_usd = settings.TRADING_MIN_MARKET_CAP_USD
    maximum_market_cap_usd = settings.TRADING_MAX_MARKET_CAP_USD
    minimum_liquidity_to_fdv_ratio = settings.TRADING_MIN_LIQUIDITY_TO_FDV_RATIO

    retained: list[TradingCandidate] = []
    rejected_fdv_count = 0
    rejected_market_cap_count = 0
    rejected_liquidity_ratio_count = 0
    for candidate in candidates:
        symbol = candidate.token.symbol
        short_address = tail(candidate.token.token_address)

        market_snapshot = candidate.market_snapshot
        fdv: float = market_snapshot.fully_diluted_valuation_usd
        market_cap: float = market_snapshot.market_cap_usd
        liquidity_usd: float = market_snapshot.liquidity_usd

        if fdv < minimum_fdv_usd:
            logger.debug("[TRADING][FILTER][FUNDAMENTALS] %s (%s) rejected — FDV %.0f < %.0f", symbol, short_address, fdv, minimum_fdv_usd)
            rejected_fdv_count += 1
            continue

        if fdv > maximum_fdv_usd:
            logger.debug("[TRADING][FILTER][FUNDAMENTALS] %s (%s) rejected — FDV %.0f > %.0f", symbol, short_address, fdv, maximum_fdv_usd)
            rejected_fdv_count += 1
            continue

        liquidity_to_fdv_ratio = liquidity_usd / fdv
        if liquidity_to_fdv_ratio < minimum_liquidity_to_fdv_ratio:
            logger.debug(
                "[TRADING][FILTER][FUNDAMENTALS] %s (%s) rejected — liq/FDV ratio %.4f < %.4f (liq=%.0f fdv=%.0f)",
                symbol, short_address, liquidity_to_fdv_ratio, minimum_liquidity_to_fdv_ratio, liquidity_usd, fdv,
            )
            rejected_liquidity_ratio_count += 1
            continue

        if market_cap < minimum_market_cap_usd:
            logger.debug("[TRADING][FILTER][FUNDAMENTALS] %s (%s) rejected — market cap %.0f < %.0f", symbol, short_address, market_cap, minimum_market_cap_usd)
            rejected_market_cap_count += 1
            continue

        if market_cap > maximum_market_cap_usd:
            logger.debug("[TRADING][FILTER][FUNDAMENTALS] %s (%s) rejected — market cap %.0f > %.0f", symbol, short_address, market_cap, maximum_market_cap_usd)
            rejected_market_cap_count += 1
            continue

        retained.append(candidate)

    logger.info(
        "[TRADING][FILTER][FUNDAMENTALS] Retained %d / %d candidates (rejected_fdv=%d, rejected_mc=%d, rejected_liq_ratio=%d)",
        len(retained), len(candidates), rejected_fdv_count, rejected_market_cap_count, rejected_liquidity_ratio_count,
    )
    return retained
