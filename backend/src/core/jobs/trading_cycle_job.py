from __future__ import annotations

import threading
import time

from src.configuration.config import settings
from src.core.trading.trading_pipeline import TradingPipeline
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingCycleJob:
    def __init__(self) -> None:
        self._pipeline = TradingPipeline()

    def run_loop(self, stop_event: threading.Event) -> None:
        interval = settings.TRADING_LOOP_INTERVAL_SECONDS
        logger.info("[TRADING][CYCLE][JOB] Trading cycle loop starting (interval=%ss)", interval)
        while not stop_event.is_set():
            try:
                if settings.TRADING_ENABLED:
                    self._pipeline.run_once()
                else:
                    logger.debug("[TRADING][CYCLE][JOB] Trading is disabled in settings, skipping cycle")
            except Exception as exception:
                logger.exception("[TRADING][CYCLE][JOB] Trading cycle error: %s", exception)
            
            for _ in range(int(interval * 2)):
                if stop_event.is_set():
                    break
                time.sleep(0.5)
        
        logger.info("[TRADING][CYCLE][JOB] Trading cycle loop successfully terminated")
