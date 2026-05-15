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
_trading_cortex_training_task: asyncio.Task | None = None
_stop_event = threading.Event()


def start_background_jobs() -> None:
    global _started, _stop_event
    global _trading_cycle_thread, _shadowing_thread
    global _position_guard_task, _aave_sentinel_task, _dca_background_task

    if _started:
        return
    
    _stop_event.clear()

    from src.core.jobs.trading_cycle_job import TradingCycleJob
    from src.core.jobs.trading_shadowing_job import TradingShadowingJob
    from src.core.jobs.trading_position_guard_job import TradingPositionGuardJob
    from src.core.jobs.aave_sentinel_job import AaveSentinelJob
    from src.core.jobs.dca_job import DcaJob

    event_loop = asyncio.get_event_loop()

    if settings.TRADING_ENABLED:
        _trading_cycle_thread = threading.Thread(
            target=TradingCycleJob().run_loop,
            args=(_stop_event,),
            name="trading-cycle-loop",
            daemon=True,
        )
        _trading_cycle_thread.start()
        logger.info("[ORCHESTRATOR] Trading cycle thread started (interval=%ss)", settings.TRADING_LOOP_INTERVAL_SECONDS)

        _position_guard_task = event_loop.create_task(TradingPositionGuardJob().run_loop())
        logger.info("[ORCHESTRATOR] Position guard task started (interval=%ss)", settings.TRADING_POSITION_GUARD_INTERVAL_SECONDS)
    else:
        logger.info("[ORCHESTRATOR] Trading disabled in settings, trading loop and position guard not scheduled")

    if settings.TRADING_ENABLED and settings.TRADING_SHADOWING_ENABLED:
        _shadowing_thread = threading.Thread(
            target=TradingShadowingJob().run_loop,
            args=(_stop_event,),
            name="shadowing-loop",
            daemon=True,
        )
        _shadowing_thread.start()
        logger.info("[ORCHESTRATOR] Shadowing thread started (interval=%ss)", settings.TRADING_SHADOWING_LOOP_INTERVAL_SECONDS)
    else:
        logger.info("[ORCHESTRATOR] Shadowing disabled or trading inactive, shadowing loop not scheduled")

    if settings.AAVE_SENTINEL_ENABLED:
        _aave_sentinel_task = event_loop.create_task(AaveSentinelJob().run_loop())
        logger.info("[ORCHESTRATOR][AAVE_SENTINEL] Sentinel background task armed")
    else:
        logger.info("[ORCHESTRATOR][AAVE_SENTINEL] Sentinel disabled in settings, task not scheduled")

    if settings.DCA_ENABLED:
        _dca_background_task = event_loop.create_task(DcaJob().run_loop())
        logger.info("[ORCHESTRATOR][DCA_JOB] Scheduled task started (interval=%ss)", settings.AAVE_DCA_PROCESS_TICKER_INTERVAL_SECONDS)
    else:
        logger.info("[ORCHESTRATOR][DCA_JOB] DCA disabled in settings, task not scheduled")

    if settings.TRADING_CORTEX_ENABLED:
        from src.core.jobs.trading_cortex_training_job import TradingCortexTrainingJob
        global _trading_cortex_training_task
        _trading_cortex_training_task = event_loop.create_task(TradingCortexTrainingJob().run_loop())
        logger.info("[ORCHESTRATOR][TRADING][CORTEX][TRAINING] Scheduled task started")
    else:
        logger.info("[ORCHESTRATOR][TRADING][CORTEX][TRAINING] TradingCortex disabled in settings, task not scheduled")

    _started = True
    logger.info("[ORCHESTRATOR] All background jobs armed successfully")


def stop_background_jobs() -> None:
    global _started, _stop_event
    global _position_guard_task, _aave_sentinel_task, _dca_background_task, _trading_cortex_training_task
    
    if not _started:
        return
        
    logger.info("[ORCHESTRATOR][SHUTDOWN] Signaling background threads to stop...")
    _stop_event.set()
    
    logger.info("[ORCHESTRATOR][SHUTDOWN] Canceling asyncio tasks...")
    tasks_to_cancel = [
        task for task in [
            _position_guard_task, 
            _aave_sentinel_task, 
            _dca_background_task, 
            _trading_cortex_training_task
        ] if task is not None
    ]
    
    for task in tasks_to_cancel:
        task.cancel()
        
    _started = False
    logger.info("[ORCHESTRATOR][SHUTDOWN] All background jobs signalized for termination")


def read_background_jobs_runtime_status() -> BackgroundJobsRuntimeStatus:
    return BackgroundJobsRuntimeStatus(
        mode=Mode.PAPER if settings.PAPER_MODE else Mode.LIVE,
        trading_enabled=settings.TRADING_ENABLED,
        dca_enabled=settings.DCA_ENABLED,
        trading_interval_seconds=settings.TRADING_LOOP_INTERVAL_SECONDS,
        position_guard_interval_seconds=settings.TRADING_POSITION_GUARD_INTERVAL_SECONDS,
        shadowing_enabled=settings.TRADING_SHADOWING_ENABLED,
        aave_sentinel_enabled=settings.AAVE_SENTINEL_ENABLED,
    )
