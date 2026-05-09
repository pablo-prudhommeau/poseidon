from __future__ import annotations

from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelJob:
    async def run_loop(self) -> None:
        from src.integrations.aave.aave_sentinel import sentinel
        logger.info("[ORCHESTRATOR][AAVE_SENTINEL] Starting Aave sentinel service")
        await sentinel.start()
