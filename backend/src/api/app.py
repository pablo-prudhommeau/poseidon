from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from src.api.http.http_api import router as http_router
from src.api.http.trading_http_api import router as trading_http_router
from src.api.websocket.websocket_hub import router as ws_router
from src.api.websocket.websocket_manager import websocket_manager
from src.cache.cache_invalidator import cache_invalidator
from src.configuration.config import settings
from src.core.aavedca.aave_dca_notification_service import register_aave_dca_telegram_handlers
from src.core.aavedca.cache.aave_dca_cache_rebuilders import register_aave_dca_rebuilders
from src.core.aavesentinel.aave_sentinel_service import register_aave_sentinel_telegram_handlers, sentinel
from src.core.aavesentinel.cache.aave_sentinel_cache_rebuilders import register_aave_sentinel_rebuilders
from src.core.jobs.job_structures import ApiStatusResponse
from src.core.jobs.orchestrator import read_background_jobs_runtime_status, start_background_jobs, stop_background_jobs
from src.core.trading.cache.trading_cache_rebuilders import register_trading_rebuilders
from src.core.trading.shadowing.cache.trading_shadowing_cache_rebuilders import register_trading_shadowing_rebuilders
from src.logging.application_exception_hooks import install_asyncio_unhandled_exception_handler
from src.logging.logger import get_application_logger, initialize_application_logging
from src.persistence.database_migration_manager import run_database_migrations
from src.persistence.database_session_manager import get_database_session

logger = get_application_logger(__name__)


def _parse_allowed_origins(environment_value: str) -> list[str]:
    return [origin_segment.strip() for origin_segment in environment_value.split(",") if origin_segment.strip()]


def _register_enabled_cache_rebuilders() -> bool:
    registered_rebuilder_count: int = 0

    if settings.TRADING_ENABLED:
        register_trading_rebuilders()
        registered_rebuilder_count += 1
        logger.info("[STARTUP][CACHE][TRADING] Trading rebuilders registered")
    else:
        logger.info("[STARTUP][CACHE][TRADING] Trading disabled, trading rebuilders skipped")

    if settings.TRADING_ENABLED and settings.TRADING_SHADOWING_ENABLED:
        register_trading_shadowing_rebuilders()
        registered_rebuilder_count += 1
        logger.info("[STARTUP][CACHE][SHADOWING] Shadowing rebuilders registered")
    else:
        logger.info("[STARTUP][CACHE][SHADOWING] Shadowing disabled or trading inactive, shadowing rebuilders skipped")

    if settings.AAVE_DCA_ENABLED:
        register_aave_dca_rebuilders()
        registered_rebuilder_count += 1
        logger.info("[STARTUP][CACHE][AAVEDCA] DCA rebuilders registered")
    else:
        logger.info("[STARTUP][CACHE][AAVEDCA] DCA disabled, DCA rebuilders skipped")

    if settings.AAVE_SENTINEL_ENABLED:
        register_aave_sentinel_rebuilders()
        registered_rebuilder_count += 1
        logger.info("[STARTUP][CACHE][AAVESENTINEL] Sentinel rebuilders registered")
    else:
        logger.info("[STARTUP][CACHE][AAVESENTINEL] Sentinel disabled, sentinel rebuilders skipped")

    return registered_rebuilder_count > 0


def _register_enabled_telegram_handlers() -> bool:
    registered_handler_module_count: int = 0

    if settings.AAVE_DCA_ENABLED:
        register_aave_dca_telegram_handlers()
        registered_handler_module_count += 1
        logger.info("[STARTUP][TELEGRAM][AAVEDCA] DCA Telegram handlers registered")
    else:
        logger.info("[STARTUP][TELEGRAM][AAVEDCA] DCA disabled, Telegram handlers skipped")

    if settings.AAVE_SENTINEL_ENABLED:
        register_aave_sentinel_telegram_handlers()
        registered_handler_module_count += 1
        logger.info("[STARTUP][TELEGRAM][AAVESENTINEL] Sentinel Telegram handlers registered")
    else:
        logger.info("[STARTUP][TELEGRAM][AAVESENTINEL] Sentinel disabled, Telegram handlers skipped")

    return registered_handler_module_count > 0


def create_app() -> FastAPI:
    initialize_application_logging()
    application = FastAPI(title="Poseidon API")

    cors_origins_environment_value = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:4200,http://127.0.0.1:4200",
    )
    allowed_origin_list = _parse_allowed_origins(cors_origins_environment_value)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.add_middleware(GZipMiddleware, minimum_size=500)

    @application.exception_handler(Exception)
    async def unhandled_http_exception_handler(request: Request, exception: Exception) -> JSONResponse:
        logger.exception(
            "[HTTP][API] Unhandled exception — method=%s path=%s",
            request.method,
            request.url.path,
        )
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    @application.on_event("startup")
    async def on_startup() -> None:
        install_asyncio_unhandled_exception_handler(asyncio.get_running_loop())

        if settings.DATABASE_AUTO_MIGRATE:
            await asyncio.to_thread(run_database_migrations)

        websocket_manager.attach_current_event_loop()

        if _register_enabled_cache_rebuilders():
            cache_invalidator.start_watcher()
            logger.info("[STARTUP][CACHE] Invalidation watcher started")
        else:
            logger.info("[STARTUP][CACHE] No enabled rebuilders detected, invalidation watcher skipped")

        if settings.AAVE_DCA_ENABLED:
            with get_database_session() as database_session:
                from src.core.aavedca.aave_dca_notification_service import resync_active_dca_order_telegram_messages

                resync_active_dca_order_telegram_messages(database_session)
        else:
            logger.info("[STARTUP][AAVEDCA] DCA disabled in settings, telegram resync skipped")

        _register_enabled_telegram_handlers()

        start_background_jobs()

    @application.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("[SHUTDOWN] Application shutdown initiated")

        stop_background_jobs()

        await websocket_manager.close_all_connections()

        await sentinel.stop()

        logger.info("[SHUTDOWN] Application shutdown complete")

    @application.get("/api/status", response_model=ApiStatusResponse)
    def api_status() -> ApiStatusResponse:
        return ApiStatusResponse(
            ok=True,
            status=read_background_jobs_runtime_status(),
        )

    application.include_router(ws_router)
    application.include_router(http_router)
    application.include_router(trading_http_router)

    return application


app = create_app()
