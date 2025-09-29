from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from src.api.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.pnl import (
    latest_prices_for_positions,
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)
from src.logging.logger import get_logger
from src.persistence import dao
from src.persistence.dao.portfolio_snapshots import get_latest_portfolio, equity_curve
from src.persistence.dao.positions import get_open_positions
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import get_db
from src.persistence.serializers import (
    serialize_trade,
    serialize_position,
    serialize_portfolio,
)

router = APIRouter()
log = get_logger(__name__)


async def _send_init(ws: WebSocket, db: Session) -> None:
    """Send the initial payload to a newly connected WebSocket client."""
    snapshot = get_latest_portfolio(db)
    positions = get_open_positions(db)

    # 1) Live prices and last_price enrichment
    prices = await latest_prices_for_positions(positions)

    # 2) Trades (single source of truth) and realized PnL
    get_all = getattr(dao, "get_all_trades", None)
    trades = get_all(db) if callable(get_all) else get_recent_trades(db, limit=10000)
    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)

    # 3) Cash & holdings/unrealized
    starting_cash = float(settings.PAPER_STARTING_CASH)
    cash, _, _, _ = cash_from_trades(starting_cash, trades)
    holdings, unrealized = holdings_and_unrealized(positions, prices)

    # 4) Portfolio payload (same shape as orchestrator)
    portfolio = (
        serialize_portfolio(
            snapshot,
            equity_curve=equity_curve(db),
            realized_total=realized_total,
            realized_24h=realized_24h,
        )
        if snapshot
        else {}
    )
    # Backward compatibility with older schemas
    portfolio.setdefault("cash", cash)
    portfolio.setdefault("holdings", holdings)
    portfolio["equity"] = round(float(portfolio.get("cash", cash)) + holdings, 2)
    portfolio["unrealized_pnl"] = unrealized
    portfolio["realized_pnl_total"] = realized_total
    portfolio["realized_pnl_24h"] = realized_24h

    # 5) Positions with last_price
    positions_payload: List[Dict[str, Any]] = []
    for position in positions:
        serialized = serialize_position(position)
        serialized["last_price"] = prices.get((position.address or "").lower(), None)
        positions_payload.append(serialized)

    # 6) Recent trades for the table
    trades_recent = get_recent_trades(db, limit=100)

    payload: Dict[str, Any] = {
        "status": {
            "paperMode": settings.PAPER_MODE,
            "interval": settings.TREND_INTERVAL_SEC
        },
        "portfolio": portfolio,
        "positions": positions_payload,
        "trades": [serialize_trade(t) for t in trades_recent],
    }
    await ws.send_json({"type": "init", "payload": jsonable_encoder(payload)})


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, db: Session = Depends(get_db)) -> None:
    """WebSocket endpoint: keeps the connection open and responds to simple commands."""
    await ws.accept()
    ws_manager.connect(ws)
    try:
        await _send_init(ws, db)
        while True:
            message = await ws.receive_json()
            message_type = message.get("type")
            if message_type == "ping":
                await ws.send_json({"type": "pong"})
            elif message_type == "refresh":
                await _send_init(ws, db)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.exception("WebSocket error: %s", exc)
        try:
            await ws.send_json({"type": "error", "payload": str(exc)})
        except Exception:
            pass
    finally:
        ws_manager.disconnect(ws)
