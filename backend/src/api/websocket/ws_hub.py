from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from src.api.websocket.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.utils.pnl_utils import fifo_realized_pnl, cash_from_trades, holdings_and_unrealized_from_trades
from src.core.utils.price_utils import merge_prices_with_entry
from src.integrations.dexscreener.dexscreener_client import fetch_prices_by_token_addresses
from src.logging.logger import get_logger
from src.persistence.dao import trades as dao_trades
from src.persistence.dao.analytics import get_recent_analytics
from src.persistence.dao.portfolio_snapshots import get_latest_portfolio, equity_curve
from src.persistence.dao.positions import get_open_positions
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import get_db
from src.persistence.serializers import (
    serialize_trade,
    serialize_position,
    serialize_portfolio,
    serialize_analytics,
)

router = APIRouter()
log = get_logger(__name__)


async def _send_init(ws: WebSocket, db: Session) -> None:
    snapshot = get_latest_portfolio(db)
    positions = get_open_positions(db)

    tokenAddresses: List[str] = [p.tokenAddress for p in positions if p.tokenAddress]
    live_prices: Dict[str, float] = await fetch_prices_by_token_addresses(tokenAddresses)
    price_map = merge_prices_with_entry(positions, live_prices)

    get_all = getattr(dao_trades, "get_all_trades", None)
    trades_all = get_all(db) if callable(get_all) else get_recent_trades(db, limit=10000)
    realized_total, realized_24h = fifo_realized_pnl(trades_all, cutoff_hours=24)

    starting_cash = float(settings.PAPER_STARTING_CASH)
    cash, _, _, _ = cash_from_trades(starting_cash, trades_all)
    holdings, unrealized = holdings_and_unrealized_from_trades(trades_all, price_map)

    portfolio = (
        serialize_portfolio(
            snapshot,
            equity_curve=equity_curve(db),
            realized_total=realized_total,
            realized_24h=realized_24h,
        )
        if snapshot else {}
    )
    portfolio.setdefault("cash", cash)
    portfolio.setdefault("holdings", holdings)
    portfolio["equity"] = round(float(portfolio.get("cash", cash)) + holdings, 2)
    portfolio["unrealized_pnl"] = unrealized
    portfolio["realized_pnl_total"] = realized_total
    portfolio["realized_pnl_24h"] = realized_24h

    positions_payload: List[Dict[str, Any]] = []
    for p in positions:
        s = serialize_position(p)
        s["last_price"] = price_map.get(p.tokenAddress)
        positions_payload.append(s)

    trades_recent = get_recent_trades(db, limit=100)

    latest_analytics = [serialize_analytics(a) for a in get_recent_analytics(db, limit=1000)]

    payload: Dict[str, Any] = {
        "status": {"paperMode": settings.PAPER_MODE, "interval": settings.TREND_INTERVAL_SEC},
        "portfolio": portfolio,
        "positions": positions_payload,
        "trades": [serialize_trade(t) for t in trades_recent],
        "analytics": latest_analytics,
    }
    await ws.send_json({"type": "init", "payload": jsonable_encoder(payload)})


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, db: Session = Depends(get_db)) -> None:
    await ws.accept()
    ws_manager.connect(ws)
    try:
        await _send_init(ws, db)
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif msg.get("type") == "refresh":
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
