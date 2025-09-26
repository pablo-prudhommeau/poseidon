# src/api/ws_hub.py
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
from src.core.pnl import (
    latest_prices_for_positions,
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)

log = logging.getLogger("poseidon.api")
router = APIRouter()


async def _send_init(ws: WebSocket, db):
    snap = crud.get_latest_portfolio(db)
    positions = crud.get_open_positions(db)

    # 1) Prix live + last_price
    prices = await latest_prices_for_positions(positions, chain_id=getattr(settings, "TREND_CHAIN_ID", None))

    # 2) Trades (source unique) et PnL réalisé
    get_all = getattr(crud, "get_all_trades", None)
    trades = get_all(db) if callable(get_all) else crud.get_recent_trades(db, limit=10000)
    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)

    # 3) Cash & holdings/unrealized
    start_cash = float(getattr(settings, "PAPER_STARTING_CASH", 10_000.0))
    cash, _, _, _ = cash_from_trades(start_cash, trades)
    holdings, unrealized = holdings_and_unrealized(positions, prices)

    # 4) Portfolio enrichi (même forme que l’orchestrator)
    portfolio = serialize_portfolio(
        snap,
        equity_curve=crud.equity_curve(db),
        realized_total=realized_total,
        realized_24h=realized_24h,
    ) if snap else {}
    portfolio.setdefault("cash", cash)         # au cas où le snapshot vient d’un ancien schéma
    portfolio.setdefault("holdings", holdings)
    portfolio["equity"] = round(float(portfolio.get("cash", cash)) + holdings, 2)
    portfolio["unrealized_pnl"] = unrealized
    portfolio["realized_pnl_total"] = realized_total
    portfolio["realized_pnl_24h"] = realized_24h

    # 5) Positions avec last_price
    positions_payload = []
    for p in positions:
        d = serialize_position(p)
        d["last_price"] = prices.get((p.address or "").lower(), None)
        positions_payload.append(d)

    # 6) Trades pour la table
    trades_recent = crud.get_recent_trades(db, limit=100)

    payload = {
        "status": {"paperMode": settings.PAPER_MODE, "interval": settings.TREND_INTERVAL_SEC},
        "portfolio": portfolio,
        "positions": positions_payload,
        "trades": [serialize_trade(t) for t in trades_recent],
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
