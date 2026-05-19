from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _passes_volume_thresholds(candidate: TradingCandidate, interval: str) -> bool:
    market_snapshot = candidate.market_snapshot
    volume_5m = market_snapshot.volume_m5_usd
    volume_1h = market_snapshot.volume_h1_usd
    volume_6h = market_snapshot.volume_h6_usd
    volume_24h = market_snapshot.volume_h24_usd

    threshold_5m = settings.TRADING_MIN_VOLUME_5M_USD
    threshold_1h = settings.TRADING_MIN_VOLUME_1H_USD
    threshold_6h = settings.TRADING_MIN_VOLUME_6H_USD
    threshold_24h = settings.TRADING_MIN_VOLUME_24H_USD

    if interval == "5m":
        return volume_5m >= threshold_5m or volume_24h >= threshold_24h
    if interval == "1h":
        return volume_1h >= threshold_1h or volume_24h >= threshold_24h
    if interval == "6h":
        return volume_6h >= threshold_6h or volume_24h >= threshold_24h
    return volume_24h >= threshold_24h


def apply_volume_filter(candidates: list[TradingCandidate]) -> list[TradingCandidate]:
    interval = settings.TRADING_SCAN_INTERVAL
    retained: list[TradingCandidate] = []
    rejected_count = 0

    for candidate in candidates:
        if _passes_volume_thresholds(candidate, interval):
            retained.append(candidate)
        else:
            symbol = candidate.token.symbol
            logger.debug("[TRADING][FILTER][VOLUME] %s rejected — below volume thresholds for interval %s", symbol, interval)
            rejected_count += 1

    logger.info("[TRADING][FILTER][VOLUME] Retained %d / %d candidates (rejected=%d)", len(retained), len(candidates), rejected_count)
    return retained
