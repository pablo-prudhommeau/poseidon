from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.http.http_api import router as http_router
from src.api.websocket.ws_hub import router as ws_router
from src.api.websocket.ws_manager import ws_manager
from src.core.jobs.orchestrator_job import ensure_started, get_status
from src.logging.logger import get_logger
from src.persistence.db import init_db
from src.integrations.aave.aave_sentinel import sentinel as aave_sentinel

log = get_logger(__name__)


def _parse_allowed_origins(env_value: str) -> List[str]:
    """Parse a comma-separated CORS origins string into a clean list."""
    return [origin.strip() for origin in env_value.split(",") if origin.strip()]


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Configured Poseidon API application.
    """
    app = FastAPI(title="Poseidon API")

    # CORS configuration
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

    @app.on_event("startup")
    async def on_startup() -> None:
        """Initialize DB, bind the WebSocket manager to the current loop, and start the orchestrator."""
        init_db()
        ws_manager.attach_current_loop()
        ensure_started()

        # Start Aave Sentinel background task
        asyncio.create_task(aave_sentinel.start())

        log.info("Poseidon startup: Orchestrator & Aave Sentinel started.")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        """Clean shutdown of services."""
        await aave_sentinel.stop()

    @app.get("/api/status")
    def api_status() -> Dict[str, Any]:
        """Return a minimal health/status payload for the UI."""
        return {"ok": True, "status": get_status()}

    # Routers
    app.include_router(ws_router)
    app.include_router(http_router)

    return app


# Expose an application instance for WSGI/ASGI servers.
app = create_app()
