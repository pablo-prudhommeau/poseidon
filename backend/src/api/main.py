# backend/src/api/main.py
from __future__ import annotations
import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.persistence.db import init_db
from src.realtime.ws_manager import ws_manager
from src.ui.ws_hub import router as ws_router
from src.ui.orchestrator import ensure_started, get_status
from src.ui.http_api import router as http_router

log = logging.getLogger("poseidon.api")  # <- notre logger

def create_app() -> FastAPI:
    app = FastAPI(title="Poseidon API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:4200,http://127.0.0.1:4200").split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()
        ws_manager.attach_current_loop()
        ensure_started()
        log.info("Poseidon startup: orchestrator started")  # <- remplace app.logger

    @app.get("/api/status")
    def api_status():
        return {"ok": True, "status": get_status()}

    app.include_router(ws_router)
    app.include_router(http_router)
    return app

app = create_app()
