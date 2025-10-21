import asyncio
import threading
import time
from typing import Optional, Dict, Any

from src.api.websocket.ws_hub import _recompute_positions_and_portfolio_and_analytics_and_broadcast
from src.configuration.config import settings
from src.core.jobs.trending_job import TrendingJob
from src.core.structures.structures import Mode
from src.logging.logger import get_logger

log = get_logger(__name__)

_thread: Optional[threading.Thread] = None
_trending_job: Optional[TrendingJob] = None
_started: bool = False
_orchestrator_loop_task: asyncio.Task | None = None


def _loop() -> None:
    """Background loop that runs the trending job at a fixed interval."""
    interval = int(settings.TREND_INTERVAL_SEC)
    log.info("Background trending loop starting (interval=%ss)", interval)
    while True:
        try:
            _trending_job.run_once()
        except Exception as exc:
            log.exception("Trending loop error: %s", exc)
        time.sleep(interval)


def ensure_started() -> None:
    global _started, _thread, _trending_job, _orchestrator_loop_task
    if _started:
        return

    _trending_job = TrendingJob()

    _thread = threading.Thread(target=_loop, name="trending-loop", daemon=True)
    _thread.start()
    _started = True

    loop = asyncio.get_event_loop()
    if _orchestrator_loop_task is None or _orchestrator_loop_task.done():
        _orchestrator_loop_task = loop.create_task(_orchestrator_loop())


def get_status() -> Dict[str, Any]:
    """Return a lightweight orchestrator status for the API/UI."""
    return {
        "mode": Mode.PAPER if settings.PAPER_MODE else Mode.LIVE,
        "interval": int(settings.TREND_INTERVAL_SEC),
        "prices_interval": int(settings.DEXSCREENER_FETCH_INTERVAL_SECONDS),
    }


async def _orchestrator_loop() -> None:
    fetch_interval = settings.DEXSCREENER_FETCH_INTERVAL_SECONDS
    log.info("Orchestrator loop starting (fetch_interval=%ss)", fetch_interval)

    while True:
        try:
            await _recompute_positions_and_portfolio_and_analytics_and_broadcast()
            await asyncio.sleep(fetch_interval)
        except Exception as exception:
            log.exception("Orchestrator loop error: %s", exception)
