from __future__ import annotations

import time
from typing import Optional

from src.configuration.config import settings
from src.core.ai.chart_capture import ChartCaptureService, ChartCaptureError
from src.core.ai.chart_openai_client import ChartOpenAiClient
from src.core.ai.chart_structures import (
    ChartAiSignal,
    ChartAiOutput,
    ChartCaptureResult,
    ChartSignalCacheEntry
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class ChartAiSignalProvider:
    def __init__(self) -> None:
        self._capture_service = ChartCaptureService()
        self._openai_client = ChartOpenAiClient()
        self._request_window_timestamps: list[float] = []
        self._signal_cache: dict[str, ChartSignalCacheEntry] = {}

    def _is_rate_limit_exceeded(self) -> bool:
        current_time = time.time()
        self._request_window_timestamps = [
            request_timestamp for request_timestamp in self._request_window_timestamps
            if current_time - request_timestamp < 60.0
        ]

        if len(self._request_window_timestamps) >= int(settings.CHART_AI_MAX_REQUESTS_PER_MINUTE):
            return True

        self._request_window_timestamps.append(current_time)
        return False

    def predict_market_signal(
            self,
            symbol: Optional[str],
            chain_name: Optional[str],
            pair_address: Optional[str],
            timeframe_minutes: int,
            lookback_minutes: int,
            token_age_hours: Optional[float] = None
    ) -> Optional[ChartAiSignal]:
        cache_lookup_key = f"{symbol or chain_name}:{pair_address}:{timeframe_minutes}:{lookback_minutes}"
        current_timestamp = time.time()

        cached_entry = self._signal_cache.get(cache_lookup_key)
        if cached_entry and (current_timestamp - cached_entry.timestamp) < float(settings.CHART_AI_MIN_CACHE_SECONDS):
            logger.debug("[AI][SIGNAL][PROVIDER][CACHE] Cache hit for %s", cache_lookup_key)
            return cached_entry.signal

        if self._is_rate_limit_exceeded():
            logger.warning("[AI][SIGNAL][PROVIDER][LIMIT] Rate limit reached, skipping analysis for %s", cache_lookup_key)
            return None

        try:
            capture_result: ChartCaptureResult = self._capture_service.capture_chart_png(
                symbol=symbol,
                chain_name=chain_name,
                pair_address=pair_address,
                timeframe_minutes=timeframe_minutes,
                lookback_minutes=lookback_minutes,
                token_age_hours=token_age_hours
            )
        except ChartCaptureError as exception:
            logger.warning("[AI][SIGNAL][PROVIDER][CAPTURE] Market chart capture failed for %s", cache_lookup_key, exception)
            return None

        ai_analysis: Optional[ChartAiOutput] = self._openai_client.analyze_chart_vision(
            screenshot_bytes=capture_result.png_bytes,
            symbol=symbol,
            chain_name=chain_name,
            pair_address=pair_address,
            timeframe_minutes=timeframe_minutes,
            lookback_minutes=lookback_minutes,
        )

        if ai_analysis is None:
            logger.warning("[AI][SIGNAL][PROVIDER][OPENAI] OpenAI analysis returned empty payload for %s", cache_lookup_key)
            return None

        generated_signal = ChartAiSignal(
            take_profit_one_probability=ai_analysis.take_profit_one_probability,
            quality_score_delta=ai_analysis.quality_score_delta,
            source_name=capture_result.source_name,
            timeframe_minutes=timeframe_minutes,
            lookback_minutes=lookback_minutes,
            trend_state=ai_analysis.trend_state,
            momentum_bias=ai_analysis.momentum_bias,
            detected_patterns=ai_analysis.detected_patterns,
            screenshot_path=capture_result.file_path
        )

        self._signal_cache[cache_lookup_key] = ChartSignalCacheEntry(
            timestamp=current_timestamp,
            signal=generated_signal
        )

        logger.info(
            "[AI][SIGNAL][PROVIDER][SUCCESS] Signal generated: probability=%.3f, delta=%.2f for %s",
            generated_signal.take_profit_one_probability,
            generated_signal.quality_score_delta,
            cache_lookup_key
        )

        return generated_signal
