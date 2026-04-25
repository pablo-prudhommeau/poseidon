from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _passes_volume_thresholds(candidate: TradingCandidate, interval: str) -> bool:
    volume_data = candidate.dexscreener_token_information.volume
    volume_5m = volume_data.m5 if volume_data and volume_data.m5 is not None else None
    volume_1h = volume_data.h1 if volume_data and volume_data.h1 is not None else None
    volume_6h = volume_data.h6 if volume_data and volume_data.h6 is not None else None
    volume_24h = volume_data.h24 if volume_data and volume_data.h24 is not None else None

    threshold_5m = settings.TRADING_MIN_VOLUME_5M_USD
    threshold_1h = settings.TRADING_MIN_VOLUME_1H_USD
    threshold_6h = settings.TRADING_MIN_VOLUME_6H_USD
    threshold_24h = settings.TRADING_MIN_VOLUME_24H_USD

    if interval == "5m":
        return (volume_5m is not None and volume_5m >= threshold_5m) or (volume_24h is not None and volume_24h >= threshold_24h)
    if interval == "1h":
        return (volume_1h is not None and volume_1h >= threshold_1h) or (volume_24h is not None and volume_24h >= threshold_24h)
    if interval == "6h":
        return (volume_6h is not None and volume_6h >= threshold_6h) or (volume_24h is not None and volume_24h >= threshold_24h)
    return volume_24h is not None and volume_24h >= threshold_24h


def apply_volume_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    interval = settings.TRADING_SCAN_INTERVAL
    retained: list[TradingCandidate] = []
    rejected_count = 0

    for candidate in candidates:
        if _passes_volume_thresholds(candidate, interval):
            retained.append(candidate)
        else:
            symbol = candidate.dexscreener_token_information.base_token.symbol
            logger.debug("[TRADING][FILTER][VOLUME] %s rejected — below volume thresholds for interval %s", symbol, interval)
            rejected_count += 1

    logger.info("[TRADING][FILTER][VOLUME] Retained %d / %d candidates (rejected=%d)", len(retained), len(candidates), rejected_count)
    return retained
