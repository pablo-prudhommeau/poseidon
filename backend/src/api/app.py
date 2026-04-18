from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from src.api.http.http_api import router as http_router
from src.api.websocket.websocket_hub import router as ws_router
from src.api.websocket.websocket_manager import websocket_manager
from src.core.jobs.dca_job import dca_job as aave_dca
from src.core.jobs.orchestrator_job import ensure_started, get_status
from src.integrations.aave.aave_sentinel import sentinel as aave_sentinel
from src.logging.logger import get_application_logger
from src.persistence.db import initialize_database

log = get_application_logger(__name__)


def _parse_allowed_origins(env_value: str) -> List[str]:
    return [origin.strip() for origin in env_value.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title="Poseidon API")

    cors_origins_env = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:4200,http://127.0.0.1:4200",
    )
    allowed_origins = _parse_allowed_origins(cors_origins_env)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(GZipMiddleware, minimum_size=500)

    @app.on_event("startup")
    async def on_startup() -> None:
        initialize_database()
        websocket_manager.attach_current_event_loop()
        ensure_started()

        from src.persistence.db import DatabaseSessionLocal
        from src.core.dca.dca_manager import DcaManager
        with DatabaseSessionLocal() as session:
            manager = DcaManager(session)
            manager.resync_waiting_approvals()

        asyncio.create_task(aave_sentinel.start())
        log.info("Aave Sentinel task scheduled.")

        asyncio.create_task(aave_dca.start())
        log.info("DCA background task successfully scheduled.")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        await aave_sentinel.stop()

    @app.get("/api/status")
    def api_status() -> Dict[str, Any]:
        return {"ok": True, "status": get_status()}

    app.include_router(ws_router)
    app.include_router(http_router)

    return app


app = create_app()
