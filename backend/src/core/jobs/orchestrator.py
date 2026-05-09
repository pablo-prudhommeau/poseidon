from __future__ import annotations

import asyncio
import threading

from src.configuration.config import settings
from src.core.jobs.job_structures import BackgroundJobsRuntimeStatus
from src.core.structures.structures import Mode
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_started: bool = False
_trading_cycle_thread: threading.Thread | None = None
_shadowing_thread: threading.Thread | None = None
_position_guard_task: asyncio.Task | None = None
_aave_sentinel_task: asyncio.Task | None = None
_dca_background_task: asyncio.Task | None = None


def start_background_jobs() -> None:
    global _started
    global _trading_cycle_thread, _shadowing_thread
    global _position_guard_task, _aave_sentinel_task, _dca_background_task

    if _started:
        return

    from src.core.jobs.trading_cycle_job import TradingCycleJob
    from src.core.jobs.trading_shadowing_job import TradingShadowingJob
    from src.core.jobs.trading_position_guard_job import TradingPositionGuardJob
    from src.core.jobs.aave_sentinel_job import AaveSentinelJob
    from src.core.jobs.dca_job import DcaJob

    _trading_cycle_thread = threading.Thread(
        target=TradingCycleJob().run_loop,
        name="trading-cycle-loop",
        daemon=True,
    )
    _trading_cycle_thread.start()
    logger.info("[ORCHESTRATOR] Trading cycle thread started (interval=%ss)", settings.TRADING_LOOP_INTERVAL_SECONDS)

    _shadowing_thread = threading.Thread(
        target=TradingShadowingJob().run_loop,
        name="shadowing-loop",
        daemon=True,
    )
    _shadowing_thread.start()
    logger.info("[ORCHESTRATOR] Shadowing thread started (interval=%ss)", settings.TRADING_SHADOWING_LOOP_INTERVAL_SECONDS)

    event_loop = asyncio.get_event_loop()

    _position_guard_task = event_loop.create_task(TradingPositionGuardJob().run_loop())
    logger.info("[ORCHESTRATOR] Position guard task started (interval=%ss)", settings.TRADING_POSITION_GUARD_INTERVAL_SECONDS)

    _aave_sentinel_task = event_loop.create_task(AaveSentinelJob().run_loop())
    logger.info("[ORCHESTRATOR][AAVE_SENTINEL] Sentinel background task armed")

    _dca_background_task = event_loop.create_task(DcaJob().run_loop())
    logger.info("[ORCHESTRATOR][DCA_JOB] Scheduled task started (interval=%ss)", settings.AAVE_DCA_PROCESS_TICKER_INTERVAL_SECONDS)

    _started = True
    logger.info("[ORCHESTRATOR] All background jobs armed successfully")


def read_background_jobs_runtime_status() -> BackgroundJobsRuntimeStatus:
    return BackgroundJobsRuntimeStatus(
        mode=Mode.PAPER if settings.PAPER_MODE else Mode.LIVE,
        trading_enabled=settings.TRADING_ENABLED,
        trading_interval_seconds=settings.TRADING_LOOP_INTERVAL_SECONDS,
        position_guard_interval_seconds=settings.TRADING_POSITION_GUARD_INTERVAL_SECONDS,
        shadowing_enabled=settings.TRADING_SHADOWING_ENABLED,
    )
