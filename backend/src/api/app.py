from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from src.api.http.http_api import router as http_router
from src.api.websocket.websocket_hub import router as ws_router
from src.api.websocket.websocket_manager import websocket_manager
from src.cache.cache_invalidator import cache_invalidator
from src.core.dca.cache.dca_cache_rebuilders import register_dca_rebuilders
from src.core.jobs.job_structures import ApiStatusResponse
from src.core.jobs.orchestrator import read_background_jobs_runtime_status, start_background_jobs
from src.core.trading.cache.trading_cache_rebuilders import register_trading_rebuilders
from src.core.trading.shadowing.cache.trading_shadowing_cache_rebuilders import register_trading_shadowing_rebuilders
from src.logging.logger import get_application_logger
from src.persistence.db import get_database_session, initialize_database

logger = get_application_logger(__name__)


def _parse_allowed_origins(environment_value: str) -> list[str]:
    return [origin_segment.strip() for origin_segment in environment_value.split(",") if origin_segment.strip()]


def create_app() -> FastAPI:
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

    @application.on_event("startup")
    async def on_startup() -> None:
        initialize_database()
        websocket_manager.attach_current_event_loop()

        register_trading_rebuilders()
        register_trading_shadowing_rebuilders()
        register_dca_rebuilders()

        cache_invalidator.start_watcher()
        logger.info("[STARTUP][CACHE] Invalidation watcher started")

        from src.core.dca.dca_manager import DcaManager
        with get_database_session() as database_session:
            DcaManager(database_session).resync_waiting_approvals()

        start_background_jobs()

    @application.on_event("shutdown")
    async def on_shutdown() -> None:
        from src.integrations.aave.aave_sentinel import sentinel
        await sentinel.stop()

    @application.get("/api/status", response_model=ApiStatusResponse)
    def api_status() -> ApiStatusResponse:
        return ApiStatusResponse(
            ok=True,
            status=read_background_jobs_runtime_status(),
        )

    application.include_router(ws_router)
    application.include_router(http_router)

    return application


app = create_app()
