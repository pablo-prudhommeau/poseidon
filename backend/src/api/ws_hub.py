from __future__ import annotations
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from src.persistence.db import get_db
from src.persistence import crud
from src.persistence.serializers import (
    serialize_trade, serialize_position, serialize_portfolio
)
from src.api.ws_manager import ws_manager
from src.configuration.config import settings

log = logging.getLogger("poseidon.api")
router = APIRouter()

async def _send_init(ws: WebSocket, db):
    snap = crud.get_latest_portfolio(db)
    positions = crud.get_open_positions(db)
    trades = crud.get_recent_trades(db, limit=100)

    payload = {
        "status": {"paperMode": settings.PAPER_MODE, "interval": settings.TREND_INTERVAL_SEC},
        "portfolio": serialize_portfolio(snap) if snap else None,
        "positions": [serialize_position(p) for p in positions],
        "trades": [serialize_trade(t) for t in trades],
    }
    await ws.send_json({"type": "init", "payload": payload})

@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, db=Depends(get_db)):
    await ws.accept()
    ws_manager.connect(ws)
    try:
        await _send_init(ws, db)

        # ⇩⇩⇩ garde la connexion ouverte et répond aux pings ⇩⇩⇩
        while True:
            msg = await ws.receive_json()
            t = msg.get("type")
            if t == "ping":
                await ws.send_json({"type": "pong"})
            elif t == "refresh":
                await _send_init(ws, db)
            # autres types ignorés pour l’instant
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.exception("WS error: %s", e)
        try:
            await ws.send_json({"type": "error", "payload": str(e)})
        except Exception:
            pass
    finally:
        ws_manager.disconnect(ws)
