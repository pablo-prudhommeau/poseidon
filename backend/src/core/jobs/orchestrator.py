from __future__ import annotations

import asyncio
import threading

from src.configuration.config import settings
from src.core.jobs.aave_sentinel_job import AaveSentinelJob
from src.core.jobs.aave_dca_job import AaveDcaJob
from src.core.jobs.job_structures import BackgroundJobsRuntimeStatus
from src.core.jobs.telegram_polling_job import TelegramPollingJob
from src.core.jobs.trading_cycle_job import TradingCycleJob
from src.integrations.telegram.telegram_update_registry import telegram_update_registry
from src.core.jobs.trading_position_guard_job import TradingPositionGuardJob
from src.core.jobs.trading_shadowing_job import TradingShadowingJob
from src.core.jobs.trading_wallet_maintenance_job import TradingWalletMaintenanceJob
from src.core.structures.structures import Mode
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_started: bool = False
_trading_cycle_thread: threading.Thread | None = None
_shadowing_thread: threading.Thread | None = None
_position_guard_task: asyncio.Task | None = None
_aave_sentinel_task: asyncio.Task | None = None
_aave_dca_background_task: asyncio.Task | None = None
_trading_cortex_training_task: asyncio.Task | None = None
_wallet_maintenance_task: asyncio.Task | None = None
_telegram_polling_task: asyncio.Task | None = None
_stop_event = threading.Event()


def start_background_jobs() -> None:
    global _started, _stop_event
    global _trading_cycle_thread, _shadowing_thread
    global _position_guard_task, _aave_sentinel_task, _aave_dca_background_task, _trading_cortex_training_task, _wallet_maintenance_task, _telegram_polling_task

    if _started:
        return

    _stop_event.clear()

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
        logger.info("[ORCHESTRATOR][AAVESENTINEL] Sentinel background task armed")
    else:
        logger.info("[ORCHESTRATOR][AAVESENTINEL] Sentinel disabled in settings, task not scheduled")

    if settings.AAVE_DCA_ENABLED:
        _aave_dca_background_task = event_loop.create_task(AaveDcaJob().run_loop())
        logger.info("[ORCHESTRATOR][AAVEDCA] Scheduled task started (interval=%ss)", settings.AAVE_DCA_PROCESS_TICKER_INTERVAL_SECONDS)
    else:
        logger.info("[ORCHESTRATOR][AAVEDCA] DCA disabled in settings, task not scheduled")

    if telegram_update_registry.has_registered_handlers():
        _telegram_polling_task = event_loop.create_task(TelegramPollingJob().run_loop())
        logger.info(
            "[ORCHESTRATOR][TELEGRAM] Telegram polling task started (interval=%ss)",
            settings.TELEGRAM_POLL_INTERVAL_SECONDS,
        )
    else:
        logger.info("[ORCHESTRATOR][TELEGRAM] No Telegram handlers registered, polling not scheduled")

    if settings.TRADING_CORTEX_ENABLED:
        from src.core.jobs.trading_cortex_training_job import TradingCortexTrainingJob
        _trading_cortex_training_task = event_loop.create_task(TradingCortexTrainingJob().run_loop())
        logger.info(
            "[ORCHESTRATOR][TRADING][CORTEX][TRAINING] Scheduled task started (interval=%ss)",
            settings.TRADING_CORTEX_LOOP_INTERVAL_SECONDS,
        )
    else:
        logger.info("[ORCHESTRATOR][TRADING][CORTEX][TRAINING] TradingCortex disabled in settings, task not scheduled")

    if settings.TRADING_WALLET_MAINTENANCE_ENABLED and not settings.TRADING_PAPER_MODE:
        _wallet_maintenance_task = event_loop.create_task(TradingWalletMaintenanceJob().run_loop())
        logger.info(
            "[ORCHESTRATOR][TRADING][WALLET_MAINTENANCE] Scheduled task started (interval=%ss)",
            settings.TRADING_WALLET_MAINTENANCE_INTERVAL_SECONDS,
        )
    else:
        logger.info("[ORCHESTRATOR][TRADING][WALLET_MAINTENANCE] Wallet maintenance disabled, task not scheduled")

    _started = True
    logger.info("[ORCHESTRATOR] All background jobs armed successfully")


def stop_background_jobs() -> None:
    global _started, _stop_event
    global _position_guard_task, _aave_sentinel_task, _aave_dca_background_task, _trading_cortex_training_task, _wallet_maintenance_task, _telegram_polling_task

    if not _started:
        return

    logger.info("[ORCHESTRATOR][SHUTDOWN] Signaling background threads to stop...")
    _stop_event.set()

    logger.info("[ORCHESTRATOR][SHUTDOWN] Canceling asyncio tasks...")
    tasks_to_cancel = [
        task for task in [
            _position_guard_task,
            _aave_sentinel_task,
            _aave_dca_background_task,
            _trading_cortex_training_task,
            _wallet_maintenance_task,
            _telegram_polling_task,
        ] if task is not None
    ]

    for task in tasks_to_cancel:
        task.cancel()

    _started = False
    logger.info("[ORCHESTRATOR][SHUTDOWN] All background jobs signalized for termination")


def read_background_jobs_runtime_status() -> BackgroundJobsRuntimeStatus:
    return BackgroundJobsRuntimeStatus(
        mode=Mode.PAPER if settings.TRADING_PAPER_MODE else Mode.LIVE,
        trading_enabled=settings.TRADING_ENABLED,
        aave_dca_enabled=settings.AAVE_DCA_ENABLED,
        trading_interval_seconds=settings.TRADING_LOOP_INTERVAL_SECONDS,
        position_guard_interval_seconds=settings.TRADING_POSITION_GUARD_INTERVAL_SECONDS,
        shadowing_enabled=settings.TRADING_SHADOWING_ENABLED,
        aave_sentinel_enabled=settings.AAVE_SENTINEL_ENABLED,
        trading_wallet_maintenance_enabled=settings.TRADING_WALLET_MAINTENANCE_ENABLED,
    )
