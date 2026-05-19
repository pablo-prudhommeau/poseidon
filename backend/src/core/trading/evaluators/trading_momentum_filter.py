from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _passes_percent_thresholds(candidate: TradingCandidate, interval: str) -> bool:
    market_snapshot = candidate.market_snapshot
    percent_5m = market_snapshot.price_change_percentage_m5
    percent_1h = market_snapshot.price_change_percentage_h1
    percent_6h = market_snapshot.price_change_percentage_h6
    percent_24h = market_snapshot.price_change_percentage_h24

    threshold_5m = settings.TRADING_MIN_PERCENT_CHANGE_5M
    threshold_1h = settings.TRADING_MIN_PERCENT_CHANGE_1H
    threshold_6h = settings.TRADING_MIN_PERCENT_CHANGE_6H
    threshold_24h = settings.TRADING_MIN_PERCENT_CHANGE_24H

    if interval == "5m":
        return percent_5m >= threshold_5m or percent_24h >= threshold_24h
    if interval == "1h":
        return percent_1h >= threshold_1h or percent_24h >= threshold_24h
    if interval == "6h":
        return percent_6h >= threshold_6h or percent_24h >= threshold_24h
    return percent_24h >= threshold_24h


def _momentum_within_bounds(
        percent_5m: float,
        percent_1h: float,
        percent_6h: float,
        percent_24h: float,
) -> bool:
    max_5m = settings.TRADING_MAX_ABSOLUTE_PERCENT_5M
    max_1h = settings.TRADING_MAX_ABSOLUTE_PERCENT_1H
    max_6h = settings.TRADING_MAX_ABSOLUTE_PERCENT_6H
    max_24h = settings.TRADING_MAX_ABSOLUTE_PERCENT_24H

    if abs(percent_5m) > max_5m:
        return False
    if abs(percent_1h) > max_1h:
        return False
    if abs(percent_6h) > max_6h:
        return False
    if abs(percent_24h) > max_24h:
        return False
    return True


def apply_momentum_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    interval = settings.TRADING_SCAN_INTERVAL
    retained: list[TradingCandidate] = []
    rejected_percent_count = 0
    rejected_momentum_count = 0

    for candidate in candidates:
        symbol = candidate.token.symbol
        market_snapshot = candidate.market_snapshot

        if not _passes_percent_thresholds(candidate, interval):
            logger.debug("[TRADING][FILTER][MOMENTUM] %s rejected — below percent thresholds for interval %s", symbol, interval)
            rejected_percent_count += 1
            continue

        if not _momentum_within_bounds(
                market_snapshot.price_change_percentage_m5,
                market_snapshot.price_change_percentage_h1,
                market_snapshot.price_change_percentage_h6,
                market_snapshot.price_change_percentage_h24,
        ):
            logger.debug("[TRADING][FILTER][MOMENTUM] %s rejected — momentum exceeds absolute bounds", symbol)
            rejected_momentum_count += 1
            continue

        retained.append(candidate)

    logger.info(
        "[TRADING][FILTER][MOMENTUM] Retained %d / %d candidates (rejected_percent=%d, rejected_bounds=%d)",
        len(retained), len(candidates), rejected_percent_count, rejected_momentum_count,
    )
    return retained
