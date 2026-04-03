from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_age_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    minimum_age_hours = settings.TRADING_MIN_AGE_HOURS
    maximum_age_hours = settings.TRADING_MAX_AGE_HOURS
    retained: list[TradingCandidate] = []
    rejected_count = 0

    for candidate in candidates:
        age_hours = candidate.dexscreener_token_information.age_hours

        if minimum_age_hours <= age_hours <= maximum_age_hours:
            retained.append(candidate)
        else:
            symbol = candidate.dexscreener_token_information.base_token.symbol
            logger.debug("[TRADING][FILTER][AGE] %s rejected — age %.1fh outside bounds [%.1f, %.1f]", symbol, age_hours, minimum_age_hours, maximum_age_hours)
            rejected_count += 1

    logger.info("[TRADING][FILTER][AGE] Retained %d / %d candidates (rejected=%d)", len(retained), len(candidates), rejected_count)
    return retained
