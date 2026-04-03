from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.core.trading.utils.trading_candidate_utils import get_price_from_token_information_list
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_price_deviation_filter(
        candidates: list[TradingCandidate],
        token_price_information_list: list[DexscreenerTokenInformation],
) -> list[TradingCandidate]:
    from src.core.trading.analytics.trading_analytics_recorder import TradingAnalyticsRecorder

    max_deviation = settings.TRADING_MAX_PRICE_DEVIATION_MULTIPLIER
    retained: list[TradingCandidate] = []

    for candidate in candidates:
        dex_price = get_price_from_token_information_list(token_price_information_list, candidate)
        symbol = candidate.dexscreener_token_information.base_token.symbol

        if dex_price is None or dex_price <= 0.0:
            logger.debug("[TRADING][FILTER][PRICE] %s — invalid DEX price", symbol)
            TradingAnalyticsRecorder.persist_and_broadcast_skip(candidate, len(retained) + 1, "NO_DEX_PRICE")
            continue

        quoted_price = candidate.dexscreener_token_information.price_usd
        if dex_price and quoted_price:
            low, high = sorted([dex_price, quoted_price])
            if low > 0.0 and (high / low) > max_deviation:
                logger.debug("[TRADING][FILTER][PRICE] %s — deviation too high dex=%.10f quoted=%.10f", symbol, dex_price, quoted_price)
                TradingAnalyticsRecorder.persist_and_broadcast_skip(candidate, len(retained) + 1, "PRICE_DEVIATION")
                continue

        candidate.dex_price = dex_price
        retained.append(candidate)

    if not retained:
        logger.info("[TRADING][FILTER][PRICE] Zero candidates after price deviation check")
    else:
        logger.info("[TRADING][FILTER][PRICE] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
