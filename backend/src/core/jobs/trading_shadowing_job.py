from __future__ import annotations

import time

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_pipeline import TradingShadowingPipeline
from src.core.trading.shadowing.trading_shadowing_verdict_tracker import TradingShadowingVerdictTracker
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingShadowingJob:
    def __init__(self) -> None:
        self._pipeline = TradingShadowingPipeline()
        self._verdict_tracker = TradingShadowingVerdictTracker()

    def run_loop(self) -> None:
        interval = settings.TRADING_SHADOWING_LOOP_INTERVAL_SECONDS
        logger.info("[TRADING][SHADOWING][JOB] Shadowing loop starting (interval=%ss)", interval)
        while True:
            try:
                if settings.TRADING_SHADOWING_ENABLED:
                    logger.info("[TRADING][SHADOWING][JOB] Starting shadow intelligence synchronization cycle")
                    self._pipeline.run_once()
                    self._verdict_tracker.check_pending_verdicts()
                    cache_invalidator.mark_dirty(
                        CacheRealm.SHADOW_INTELLIGENCE_SNAPSHOT,
                        CacheRealm.SHADOW_VERDICT_CHRONICLE,
                        CacheRealm.SHADOW_META
                    )
                    logger.info("[TRADING][SHADOWING][JOB] Shadow intelligence synchronization cycle complete")
                else:
                    logger.debug("[TRADING][SHADOWING][JOB] Shadowing is disabled in settings, skipping cycle")
            except Exception as exception:
                logger.exception("[TRADING][SHADOWING][JOB] Shadowing loop error: %s", exception)
            time.sleep(interval)
