from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.api.websocket.ws_hub import schedule_full_recompute_broadcast
from src.core.structures.structures import Token
from src.core.utils.date_utils import timezone_now
from src.integrations.dexscreener.dexscreener_client import fetch_dexscreener_token_information_list
from src.logging.logger import get_logger
from src.persistence import service
from src.persistence.dao.analytics import get_recent_analytics
from src.persistence.dao.portfolio_snapshots import ensure_initial_cash
from src.persistence.dao.positions import (
    get_open_positions,
    serialize_positions_with_token_information,
)
from src.persistence.db import get_db
from src.persistence.serializers import serialize_analytics

router = APIRouter()
log = get_logger(__name__)


@router.get("/api/health", tags=["health"])  # type: ignore[misc]
async def get_health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Report service health and basic component status.

    Returns:
        A structured payload including database connectivity and a timestamp in the system local timezone.
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
        "timestamp": current_timestamp,
        "components": {"database": {"ok": database_ok}},
    }


@router.post("/api/paper/reset")  # type: ignore[misc]
def reset_paper(db: Session = Depends(get_db)) -> Dict[str, bool]:
    """
    Reset paper mode state, ensure initial cash, and trigger a WS rebroadcast.

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


@router.get("/api/analytics", tags=["analytics"])  # type: ignore[misc]
async def get_analytics(
        limit: int = Query(5000, ge=1, le=10000),
        db: Session = Depends(get_db),
) -> Dict[str, List[Dict[str, object]]]:
    """
    Return the most recent analytics rows, serialized for the frontend.

    Args:
        limit: Maximum number of rows to return (1..10000). Defaults to 5000.

    Returns:
        A dictionary containing the "analytics" array.
    """
    rows = get_recent_analytics(db, limit=limit)
    payload = [serialize_analytics(a) for a in rows]
    log.info("[HTTP][ANALYTICS][FETCH] rows=%s", len(payload))
    return {"analytics": payload}


@router.get("/api/positions", tags=["positions"])  # type: ignore[misc]
async def get_positions(
        db: Session = Depends(get_db),
) -> Dict[str, List[Dict[str, object]]]:
    """
    Return open positions merged with their latest token prices.

    The payload mirrors the structure sent on WebSocket init, making it a drop-in
    replacement for clients that prefer HTTP over WebSockets.

    Returns:
        A dictionary containing the "positions" array.
    """
    positions = get_open_positions(db)
    tokens: List[Token] = [
        Token(
            chain=p.chain,
            symbol=p.symbol,
            tokenAddress=p.tokenAddress,
            pairAddress=p.pairAddress,
        )
        for p in positions
    ]

    token_information_list = await fetch_dexscreener_token_information_list(tokens)
    payload = serialize_positions_with_token_information(positions, token_information_list)
    log.info("[HTTP][POSITIONS][FETCH] positions=%s", len(payload))
    return {"positions": payload}
