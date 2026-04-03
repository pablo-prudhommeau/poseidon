from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_liquidity_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    minimum_liquidity_usd = settings.TRADING_MIN_LIQUIDITY_USD
    retained: list[TradingCandidate] = []
    rejected_count = 0

    for candidate in candidates:
        liquidity = candidate.dexscreener_token_information.liquidity
        liquidity_usd = liquidity.usd if liquidity and liquidity.usd is not None else 0.0

        if liquidity_usd >= minimum_liquidity_usd:
            retained.append(candidate)
        else:
            symbol = candidate.dexscreener_token_information.base_token.symbol
            logger.debug("[TRADING][FILTER][LIQUIDITY] %s rejected — liquidity %.0f < %.0f USD", symbol, liquidity_usd, minimum_liquidity_usd)
            rejected_count += 1

    logger.info("[TRADING][FILTER][LIQUIDITY] Retained %d / %d candidates (rejected=%d)", len(retained), len(candidates), rejected_count)
    return retained
