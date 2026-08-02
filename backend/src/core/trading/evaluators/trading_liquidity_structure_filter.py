from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.format_utils import tail
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def compute_market_cap_to_liquidity_ratio(market_cap_usd: float, liquidity_usd: float) -> Optional[float]:
    if market_cap_usd <= 0.0 or liquidity_usd <= 0.0:
        return None
    return market_cap_usd / liquidity_usd


def apply_liquidity_structure_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    minimum_market_cap_to_liquidity_ratio: float = settings.TRADING_LIQUIDITY_STRUCTURE_MIN_MARKET_CAP_TO_LIQUIDITY_RATIO
    maximum_market_cap_to_liquidity_ratio: float = settings.TRADING_LIQUIDITY_STRUCTURE_MAX_MARKET_CAP_TO_LIQUIDITY_RATIO

    retained: list[TradingCandidate] = []
    rejected_shallow_liquidity_count: int = 0
    rejected_inflated_valuation_count: int = 0
    rejected_undeterminable_ratio_count: int = 0

    for candidate in candidates:
        symbol: str = candidate.token.symbol
        short_address: str = tail(candidate.token.token_address)

        market_cap_usd: float = candidate.market_snapshot.market_cap_usd
        liquidity_usd: float = candidate.market_snapshot.liquidity_usd
        market_cap_to_liquidity_ratio: Optional[float] = compute_market_cap_to_liquidity_ratio(market_cap_usd, liquidity_usd)

        if market_cap_to_liquidity_ratio is None:
            logger.debug(
                "[TRADING][FILTER][LIQUIDITY_STRUCTURE] %s (%s) rejected — undeterminable market cap / liquidity ratio (market_cap=%.0f liquidity=%.0f)",
                symbol, short_address, market_cap_usd, liquidity_usd,
            )
            rejected_undeterminable_ratio_count += 1
            continue

        if market_cap_to_liquidity_ratio < minimum_market_cap_to_liquidity_ratio:
            logger.debug(
                "[TRADING][FILTER][LIQUIDITY_STRUCTURE] %s (%s) rejected — market cap / liquidity %.2f < %.2f (market_cap=%.0f liquidity=%.0f)",
                symbol, short_address, market_cap_to_liquidity_ratio, minimum_market_cap_to_liquidity_ratio, market_cap_usd, liquidity_usd,
            )
            rejected_shallow_liquidity_count += 1
            continue

        if market_cap_to_liquidity_ratio > maximum_market_cap_to_liquidity_ratio:
            logger.debug(
                "[TRADING][FILTER][LIQUIDITY_STRUCTURE] %s (%s) rejected — market cap / liquidity %.2f > %.2f (market_cap=%.0f liquidity=%.0f)",
                symbol, short_address, market_cap_to_liquidity_ratio, maximum_market_cap_to_liquidity_ratio, market_cap_usd, liquidity_usd,
            )
            rejected_inflated_valuation_count += 1
            continue

        retained.append(candidate)

    logger.info(
        "[TRADING][FILTER][LIQUIDITY_STRUCTURE] Retained %d / %d candidates (band=[%.2f, %.2f], rejected_shallow=%d, rejected_inflated=%d, rejected_undeterminable=%d)",
        len(retained), len(candidates), minimum_market_cap_to_liquidity_ratio, maximum_market_cap_to_liquidity_ratio,
        rejected_shallow_liquidity_count, rejected_inflated_valuation_count, rejected_undeterminable_ratio_count,
    )
    return retained
