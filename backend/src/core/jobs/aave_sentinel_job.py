from __future__ import annotations

from src.configuration.config import settings
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelJob:
    async def run_loop(self) -> None:
        if not settings.AAVE_SENTINEL_ENABLED:
            logger.info("[ORCHESTRATOR][AAVE_SENTINEL] Sentinel disabled in settings, startup skipped")
            return

        from src.core.aavesentinel.aave_sentinel_service import sentinel

        logger.info("[ORCHESTRATOR][AAVE_SENTINEL] Starting Aave sentinel service")
        await sentinel.start()
