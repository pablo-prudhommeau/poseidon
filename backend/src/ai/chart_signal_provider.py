from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Any, Optional

from src.ai.chart_capture import ChartCaptureService, ChartCaptureResult, ChartCaptureError
from src.ai.chart_openai_client import ChartOpenAiClient, ChartAiOutput
from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ChartAiSignal:
    """Chart-based AI signal for blending into the quality score."""
    probability_tp1_before_sl: float  # 0..1
    quality_score_delta: float  # -20..+20
    meta: Dict[str, Any]


class ChartAiSignalProvider:
    """
    Orchestrates chart capture and OpenAI analysis to produce a compact signal.
    Includes local caching and simple rate limiting.
    """

    def __init__(self) -> None:
        self._capture = ChartCaptureService()
        self._client = ChartOpenAiClient()
        self._last_minute_timestamps: list[float] = []
        self._cache: Dict[str, tuple[float, ChartAiSignal]] = {}

    def _rate_limit_ok(self) -> bool:
        now = time.time()
        self._last_minute_timestamps = [t for t in self._last_minute_timestamps if now - t < 60.0]
        if len(self._last_minute_timestamps) >= int(settings.CHART_AI_MAX_REQUESTS_PER_MINUTE):
            return False
        self._last_minute_timestamps.append(now)
        return True

    def predict(
            self,
            symbol: Optional[str],
            chain_name: Optional[str],
            pair_address: Optional[str],
            timeframe_minutes: int,
            lookback_minutes: int,
            token_age_hours: float
    ) -> Optional[ChartAiSignal]:
        """
        Produce a probability that TP1 occurs before SL in the next 30–60 minutes,
        along with a suggested delta to the baseline quality score.
        """
        if not settings.CHART_AI_ENABLED:
            return None
        key = f"{symbol or chain_name}:{pair_address}:{timeframe_minutes}:{lookback_minutes}"
        now = time.time()
        cached = self._cache.get(key)
        if cached and (now - cached[0]) < float(settings.CHART_AI_MIN_CACHE_SECONDS):
            return cached[1]

        if not self._rate_limit_ok():
            log.warning("ChartAI: rate limit reached, skipping for %s", key)
            return None

        try:
            capture: ChartCaptureResult = self._capture.capture_chart_png(
                symbol=symbol,
                chain_name=chain_name,
                pair_address=pair_address,
                timeframe_minutes=timeframe_minutes,
                lookback_minutes=lookback_minutes,
                token_age_hours=token_age_hours
            )
        except ChartCaptureError as exc:
            log.warning("ChartAI: capture failed for %s: %s", key, exc)
            return None

        analysis: Optional[ChartAiOutput] = self._client.analyze_chart_png(
            png_bytes=capture.png_bytes,
            symbol=symbol,
            chain_name=chain_name,
            pair_address=pair_address,
            timeframe_minutes=timeframe_minutes,
            lookback_minutes=lookback_minutes,
        )
        if analysis is None:
            return None

        # The primary signal: probability that TP1 occurs before SL soon.
        prob = float(analysis.tp1_probability)
        delta = float(analysis.quality_score_delta)

        signal = ChartAiSignal(
            probability_tp1_before_sl=prob,
            quality_score_delta=delta,
            meta={
                "source": capture.source_name,
                "timeframe_minutes": timeframe_minutes,
                "lookback_minutes": lookback_minutes,
                "trend_state": analysis.trend_state,
                "momentum_bias": analysis.momentum_bias,
                "patterns": analysis.patterns,
                "screenshot_path": capture.file_path
            },
        )
        self._cache[key] = (now, signal)
        log.info("ChartAI: generated signal p=%.3f delta=%.2f for %s", prob, delta, key)
        log.debug("ChartAI: meta=%s", signal.meta)
        return signal
