from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.utils.date_utils import timezone_now
from src.logging.logger import get_logger
from src.persistence import service
from src.persistence.dao.portfolio_snapshots import ensure_initial_cash
from src.persistence.db import get_db
from src.api.websocket.ws_hub import schedule_full_recompute_broadcast

router = APIRouter()
log = get_logger(__name__)


@router.get("/api/health", tags=["health"])
async def get_health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Report service health and basic component status.

    Returns a structured payload including database connectivity and a UTC timestamp.
    """
    current_timestamp = timezone_now().isoformat()
    database_ok = False
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
        log.debug("[HTTP][HEALTH] Database connectivity validated")
    except Exception:
        log.exception("[HTTP][HEALTH] Health check database connectivity failed")

    status = "ok" if database_ok else "degraded"
    return {
        "status": status,
        "timestampUtc": current_timestamp,
        "components": {"database": {"ok": database_ok}},
    }


@router.post("/api/paper/reset")
def reset_paper(db: Session = Depends(get_db)) -> Dict[str, bool]:
    """
    Reset paper mode state, ensure initial cash, and trigger an immediate websocket rebroadcast.

    This endpoint performs a synchronous reset then schedules a full recomputation
    (positions, portfolio, trades, analytics) to be broadcast to all connected clients.
    """
    service.reset_paper(db)
    ensure_initial_cash(db)
    log.info("[HTTP][PAPER][RESET] Paper mode has been reset and initial cash ensured")

    try:
        loop = asyncio.get_running_loop()
        if loop.is_running() and not loop.is_closed():
            schedule_full_recompute_broadcast()
            log.debug("[HTTP][PAPER][REBROADCAST] Scheduled immediate recompute after reset")
        else:
            log.debug("[HTTP][PAPER][REBROADCAST] No running loop, UI will refresh on next orchestrator tick")
    except RuntimeError:
        log.debug("[HTTP][PAPER][REBROADCAST] No running loop, UI will refresh on next orchestrator tick")

    return {"ok": True}
