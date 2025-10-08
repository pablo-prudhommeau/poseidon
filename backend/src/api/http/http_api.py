from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.jobs import orchestrator_job
from src.core.utils.date_utils import timezone_now
from src.logging.logger import get_logger
from src.persistence import service
from src.persistence.dao.portfolio_snapshots import (
    ensure_initial_cash,
)
from src.persistence.db import get_db

router = APIRouter()
log = get_logger(__name__)


@router.get("/api/health", tags=["health"])
async def get_health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    current_timestamp = timezone_now().isoformat()
    database_ok = False
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        log.exception("Health check database connectivity failed.")

    status = "ok" if database_ok else "degraded"
    return {
        "status": status,
        "timestampUtc": current_timestamp,
        "components": {"database": {"ok": database_ok}},
    }


@router.post("/api/paper/reset")
def reset_paper(db: Session = Depends(get_db)) -> Dict[str, bool]:
    service.reset_paper(db)
    ensure_initial_cash(db)
    log.info("Paper mode has been reset and initial cash ensured")
    return {"ok": True}
