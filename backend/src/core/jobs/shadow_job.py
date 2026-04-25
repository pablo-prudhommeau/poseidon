from __future__ import annotations

import time

from src.configuration.config import settings
from src.core.trading.shadowing.shadow_trading_pipeline import ShadowTradingPipeline
from src.core.trading.shadowing.shadow_verdict_tracker import ShadowVerdictTracker
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class ShadowJob:
    def __init__(self) -> None:
        self._pipeline = ShadowTradingPipeline()
        self._verdict_tracker = ShadowVerdictTracker()
        self._last_run_timestamp = 0.0

    def run_once(self) -> None:
        if not settings.TRADING_SHADOWING_ENABLED:
            return

        current_time = time.time()
        interval = settings.TRADING_SHADOWING_LOOP_INTERVAL_SECONDS

        if current_time - self._last_run_timestamp < interval:
            return

        logger.info("[TRADING][SHADOW][JOB] Starting shadow intelligence synchronization cycle")

        self._pipeline.run_once()

        self._verdict_tracker.check_pending_verdicts()

        self._last_run_timestamp = current_time
        logger.info("[TRADING][SHADOW][JOB] Shadow intelligence synchronization cycle complete")
