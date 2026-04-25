import asyncio
import threading
import time
from typing import Optional

from src.api.websocket.websocket_hub import recompute_metrics_and_broadcast
from src.configuration.config import settings
from src.core.jobs.shadow_job import ShadowJob
from src.core.structures.structures import Mode
from src.core.trading.trading_job import TradingJob
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_trading_thread: Optional[threading.Thread] = None
_shadow_thread: Optional[threading.Thread] = None
_trading_job: Optional[TradingJob] = None
_shadow_job: Optional[ShadowJob] = None
_started: bool = False
_orchestrator_loop_task: asyncio.Task | None = None


def _trading_loop() -> None:
    interval = int(settings.TRADING_LOOP_INTERVAL_SECONDS)
    logger.info("[ORCHESTRATOR] Trading loop starting (interval=%ss)", interval)
    while True:
        try:
            if settings.TRADING_ENABLED:
                _trading_job.run_once()
            else:
                logger.debug("[ORCHESTRATOR] Trading is disabled in settings, skipping cycle")
        except Exception as exception:
            logger.exception("[ORCHESTRATOR] Trading loop error: %s", exception)
        time.sleep(interval)


def _shadow_loop() -> None:
    logger.info("[ORCHESTRATOR] Shadowing loop starting")
    while True:
        try:
            _shadow_job.run_once()
        except Exception as exception:
            logger.exception("[ORCHESTRATOR] Shadowing loop error: %s", exception)
        time.sleep(10)


def ensure_started() -> None:
    global _started, _trading_thread, _shadow_thread, _trading_job, _shadow_job, _orchestrator_loop_task
    if _started:
        return

    _trading_job = TradingJob()
    _shadow_job = ShadowJob()

    _trading_thread = threading.Thread(target=_trading_loop, name="trading-loop", daemon=True)
    _trading_thread.start()

    _shadow_thread = threading.Thread(target=_shadow_loop, name="shadow-loop", daemon=True)
    _shadow_thread.start()

    _started = True

    loop = asyncio.get_event_loop()
    if _orchestrator_loop_task is None or _orchestrator_loop_task.done():
        _orchestrator_loop_task = loop.create_task(_orchestrator_loop())


def get_status() -> dict[str, object]:
    return {
        "mode": Mode.PAPER if settings.PAPER_MODE else Mode.LIVE,
        "trading_enabled": settings.TRADING_ENABLED,
        "interval": int(settings.TRADING_LOOP_INTERVAL_SECONDS),
        "prices_interval": int(settings.DEXSCREENER_FETCH_INTERVAL_SECONDS),
    }


async def _orchestrator_loop() -> None:
    fetch_interval = settings.DEXSCREENER_FETCH_INTERVAL_SECONDS
    logger.info("[ORCHESTRATOR] Metrics broadcast loop starting (fetch_interval=%ss)", fetch_interval)

    while True:
        try:
            await recompute_metrics_and_broadcast()
            await asyncio.sleep(fetch_interval)
        except Exception as exception:
            logger.exception("[ORCHESTRATOR] Metrics broadcast loop error: %s", exception)
        finally:
            await asyncio.sleep(fetch_interval)
