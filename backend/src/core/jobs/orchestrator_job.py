import asyncio
import threading
import time
from typing import Optional

from src.api.websocket.websocket_hub import recompute_metrics_and_broadcast
from src.configuration.config import settings
from src.core.structures.structures import Mode
from src.core.trading.trading_job import TradingJob
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_thread: Optional[threading.Thread] = None
_trading_job: Optional[TradingJob] = None
_started: bool = False
_orchestrator_loop_task: asyncio.Task | None = None


def _loop() -> None:
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


def ensure_started() -> None:
    global _started, _thread, _trading_job, _orchestrator_loop_task
    if _started:
        return

    _trading_job = TradingJob()

    _thread = threading.Thread(target=_loop, name="trading-loop", daemon=True)
    _thread.start()
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
