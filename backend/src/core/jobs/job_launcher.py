from __future__ import annotations

import asyncio
import threading

from src.configuration.config import settings
from src.core.structures.structures import Mode
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_started: bool = False
_trading_cycle_thread: threading.Thread | None = None
_shadowing_thread: threading.Thread | None = None
_position_guard_task: asyncio.Task | None = None
_display_broadcast_task: asyncio.Task | None = None


def ensure_started() -> None:
    global _started, _trading_cycle_thread, _shadowing_thread, _position_guard_task, _display_broadcast_task

    if _started:
        return

    from src.core.jobs.trading_cycle_job import TradingCycleJob
    from src.core.jobs.trading_shadowing_job import TradingShadowingJob
    from src.core.jobs.trading_position_guard_job import TradingPositionGuardJob
    from src.core.jobs.trading_display_broadcast_job import TradingDisplayBroadcastJob

    trading_cycle_job = TradingCycleJob()
    trading_shadowing_job = TradingShadowingJob()
    trading_position_guard_job = TradingPositionGuardJob()
    trading_display_broadcast_job = TradingDisplayBroadcastJob()

    _trading_cycle_thread = threading.Thread(target=trading_cycle_job.run_loop, name="trading-cycle-loop", daemon=True)
    _trading_cycle_thread.start()
    logger.info("[JOB_LAUNCHER] Trading cycle thread started (interval=%ss)", settings.TRADING_LOOP_INTERVAL_SECONDS)

    _shadowing_thread = threading.Thread(target=trading_shadowing_job.run_loop, name="shadowing-loop", daemon=True)
    _shadowing_thread.start()
    logger.info("[JOB_LAUNCHER] Shadowing thread started (interval=%ss)", settings.TRADING_SHADOWING_LOOP_INTERVAL_SECONDS)

    event_loop = asyncio.get_event_loop()

    if _position_guard_task is None or _position_guard_task.done():
        _position_guard_task = event_loop.create_task(trading_position_guard_job.run_loop())
        logger.info("[JOB_LAUNCHER] Position guard async task started (interval=%ss)", settings.TRADING_POSITION_GUARD_INTERVAL_SECONDS)

    if _display_broadcast_task is None or _display_broadcast_task.done():
        _display_broadcast_task = event_loop.create_task(trading_display_broadcast_job.run_loop())
        logger.info("[JOB_LAUNCHER] Display broadcast async task started (interval=%ss)", settings.TRADING_DISPLAY_BROADCAST_INTERVAL_SECONDS)

    _started = True
    logger.info("[JOB_LAUNCHER] All trading jobs successfully launched")


def get_status() -> dict[str, object]:
    return {
        "mode": Mode.PAPER if settings.PAPER_MODE else Mode.LIVE,
        "trading_enabled": settings.TRADING_ENABLED,
        "interval": settings.TRADING_LOOP_INTERVAL_SECONDS,
        "display_broadcast_interval": settings.TRADING_DISPLAY_BROADCAST_INTERVAL_SECONDS,
    }
