from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.format_utils import _tail
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
    skipped_missing_data_count = 0

    for candidate in candidates:
        token_information = candidate.dexscreener_token_information
        symbol = token_information.base_token.symbol
        short_address = _tail(token_information.base_token.address)

        fdv: Optional[float] = token_information.fully_diluted_valuation
        market_cap: Optional[float] = token_information.market_cap
        liquidity_usd: float = token_information.liquidity.usd if token_information.liquidity and token_information.liquidity.usd is not None else 0.0

        if fdv is not None and fdv > 0.0:
            if fdv < minimum_fdv_usd:
                logger.debug("[TRADING][FILTER][FUNDAMENTALS] %s (%s) rejected — FDV %.0f < %.0f", symbol, short_address, fdv, minimum_fdv_usd)
                rejected_fdv_count += 1
                continue

            if fdv > maximum_fdv_usd:
                logger.debug("[TRADING][FILTER][FUNDAMENTALS] %s (%s) rejected — FDV %.0f > %.0f", symbol, short_address, fdv, maximum_fdv_usd)
                rejected_fdv_count += 1
                continue

            liquidity_to_fdv_ratio = liquidity_usd / fdv if fdv > 0.0 else 0.0
            if liquidity_to_fdv_ratio < minimum_liquidity_to_fdv_ratio:
                logger.debug(
                    "[TRADING][FILTER][FUNDAMENTALS] %s (%s) rejected — liq/FDV ratio %.4f < %.4f (liq=%.0f fdv=%.0f)",
                    symbol, short_address, liquidity_to_fdv_ratio, minimum_liquidity_to_fdv_ratio, liquidity_usd, fdv,
                )
                rejected_liquidity_ratio_count += 1
                continue
        else:
            logger.debug("[TRADING][FILTER][FUNDAMENTALS] %s (%s) — FDV not available, skipping FDV checks", symbol, short_address)
            skipped_missing_data_count += 1

        if market_cap is not None and market_cap > 0.0:
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
        "[TRADING][FILTER][FUNDAMENTALS] Retained %d / %d candidates (rejected_fdv=%d, rejected_mc=%d, rejected_liq_ratio=%d, skipped_missing=%d)",
        len(retained), len(candidates), rejected_fdv_count, rejected_market_cap_count, rejected_liquidity_ratio_count, skipped_missing_data_count,
    )
    return retained
