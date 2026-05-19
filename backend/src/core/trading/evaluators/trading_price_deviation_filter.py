from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_price_deviation_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    from src.core.trading.trading_service import record_skipped_trading_evaluation

    maximum_slippage = settings.TRADING_MAX_SLIPPAGE
    retained: list[TradingCandidate] = []

    for candidate in candidates:
        symbol = candidate.token.symbol
        screened_price = candidate.screened_price_usd
        current_price = candidate.market_snapshot.price_usd

        if screened_price is None or screened_price <= 0.0:
            logger.debug("[TRADING][FILTER][PRICE] %s — missing screened price", symbol)
            record_skipped_trading_evaluation(candidate, len(retained) + 1, "NO_SCREENED_PRICE")
            continue

        if current_price <= 0.0:
            logger.debug("[TRADING][FILTER][PRICE] %s — invalid refreshed market price", symbol)
            record_skipped_trading_evaluation(candidate, len(retained) + 1, "NO_DEX_PRICE")
            continue

        low, high = sorted([screened_price, current_price])
        if low > 0.0 and (high / low - 1.0) > maximum_slippage:
            logger.debug(
                "[TRADING][FILTER][PRICE] %s — slippage too high screened=%.10f refreshed=%.10f (>%.1f%%)",
                symbol, screened_price, current_price, maximum_slippage * 100.0,
            )
            record_skipped_trading_evaluation(candidate, len(retained) + 1, "PRICE_DEVIATION")
            continue

        retained.append(candidate)

    if not retained:
        logger.info("[TRADING][FILTER][PRICE] Zero candidates after price deviation check")
    else:
        logger.info("[TRADING][FILTER][PRICE] Retained %d / %d candidates", len(retained), len(candidates))

    return retained
