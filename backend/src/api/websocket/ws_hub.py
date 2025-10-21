from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.api.websocket.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.structures.structures import (
    Token,
    HoldingsAndUnrealizedFromTrades,
    RealizedPnl,
    EquityCurve,
    CashFromTrades, WebsocketInboundMessage,
)
from src.core.utils.pnl_utils import (
    fifo_realized_pnl,
    holdings_and_unrealized_from_trades,
    cash_from_trades,
)
from src.integrations.dexscreener.dexscreener_client import fetch_prices_by_tokens
from src.integrations.dexscreener.dexscreener_structures import TokenPrice
from src.logging.logger import get_logger
from src.persistence.dao.analytics import get_recent_analytics
from src.persistence.dao.portfolio_snapshots import (
    get_portfolio_snapshot,
    equity_curve,
    snapshot_portfolio,
)
from src.persistence.dao.positions import (
    get_open_positions,
    serialize_positions_with_token_prices,
)
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import get_db, _session
from src.persistence.models import PortfolioSnapshot, Position, Trade, Analytics
from src.persistence.serializers import serialize_trade, serialize_portfolio, serialize_analytics
from src.persistence.service import check_thresholds_and_autosell

router = APIRouter()
log = get_logger(__name__)


async def _compute_trades_payload(trades: List[Trade]) -> List[Dict[str, Any]]:
    """
    Serialize trades for frontend consumption.
    """
    trades_payload = [serialize_trade(t) for t in trades]
    return trades_payload


async def _compute_analytics_payload(analytics: List[Analytics]) -> List[Dict[str, Any]]:
    """
    Serialize analytics rows for frontend consumption.
    """
    analytics_payload = [serialize_analytics(a) for a in analytics]
    return analytics_payload


async def _compute_positions_payload(
        token_prices: List[TokenPrice],
        positions: List[Position],
) -> List[Dict[str, Any]]:
    """
    Merge open positions with latest token prices and serialize for the frontend.
    """
    positions_payload = serialize_positions_with_token_prices(positions, token_prices)
    return positions_payload


async def _compute_portfolio_payload(
        token_prices: List[TokenPrice],
        portfolio_snapshot: PortfolioSnapshot,
        trades: List[Trade],
        equity_curve_data: EquityCurve,
) -> Dict[str, Any]:
    """
    Compute and serialize the portfolio summary, including realized and unrealized PnL.
    """
    realized_pnl: RealizedPnl = fifo_realized_pnl(trades, cutoff_hours=24)
    holdings_and_unrealized: HoldingsAndUnrealizedFromTrades = holdings_and_unrealized_from_trades(
        trades, token_prices
    )

    portfolio_payload = serialize_portfolio(
        portfolio_snapshot,
        equity_curve=equity_curve_data,
        realized_total=realized_pnl.total,
        realized_24h=realized_pnl.recent,
        unrealized=holdings_and_unrealized.unrealized_pnl,
    )
    return portfolio_payload


async def _send_init(ws: WebSocket, db: Session) -> None:
    """
    Send the initial snapshot to a single websocket client.
    """

    snapshot = get_portfolio_snapshot(db)
    positions = get_open_positions(db)

    tokens: List[Token] = [
        Token(
            symbol=position.symbol,
            chain=position.chain,
            tokenAddress=position.tokenAddress,
            pairAddress=position.pairAddress,
        )
        for position in positions
    ]

    token_prices: List[TokenPrice] = await fetch_prices_by_tokens(tokens)
    trades = get_recent_trades(db, limit=10000)
    analytics = get_recent_analytics(db, limit=10000)

    portfolio_payload = await _compute_portfolio_payload(token_prices, snapshot, trades, equity_curve(db))
    positions_payload = await _compute_positions_payload(token_prices, positions)
    trades_payload = await _compute_trades_payload(trades)
    analytics_payload = await _compute_analytics_payload(analytics)

    payload: Dict[str, Any] = {
        "status": {"paperMode": settings.PAPER_MODE, "interval": settings.TREND_INTERVAL_SEC},
        "portfolio": portfolio_payload,
        "positions": positions_payload,
        "trades": trades_payload,
        "analytics": analytics_payload,
    }
    await ws.send_json({"type": "init", "payload": jsonable_encoder(payload)})


def schedule_full_recompute_broadcast() -> None:
    """
    Schedule a full recomputation and broadcast on the running event loop.

    This must be called from non-async contexts (e.g., HTTP endpoints) to ensure
    the coroutine runs safely within the server event loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.debug("[WS][REBROADCAST] No running loop; recompute will happen on next orchestrator tick")
        return

    if not loop.is_running() or loop.is_closed():
        log.debug("[WS][REBROADCAST] Event loop not running; recompute will happen on next orchestrator tick")
        return

    loop.call_soon_threadsafe(
        lambda: loop.create_task(_recompute_positions_and_portfolio_and_analytics_and_broadcast()))


async def _recompute_positions_and_portfolio_and_analytics_and_broadcast() -> None:
    """
    Recompute positions, portfolio, analytics and broadcast to all websocket clients.

    This also evaluates autosell thresholds using the latest token prices. Any newly
    created trades are broadcast immediately to keep the UI consistent.
    """
    with _session() as db:
        positions = get_open_positions(db)
        tokens: List[Token] = [
            Token(
                symbol=position.symbol,
                chain=position.chain,
                tokenAddress=position.tokenAddress,
                pairAddress=position.pairAddress,
            )
            for position in positions
        ]
        token_prices: List[TokenPrice] = await fetch_prices_by_tokens(tokens)

        autosell_trades: List[Trade] = []
        for price in token_prices:
            try:
                if price.priceUsd is None or float(price.priceUsd) <= 0.0:
                    continue
                created_trades = check_thresholds_and_autosell(db, token=price.token, last_price=float(price.priceUsd))
                if created_trades:
                    autosell_trades.extend(created_trades)
            except Exception as exc:
                log.warning("[WS][AUTOSELL] Threshold evaluation failed for %s - %s", price.token, exc)

        for created in autosell_trades:
            ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(created)})
        if autosell_trades:
            log.info("[WS][AUTOSELL] Broadcasted %d autosell trade(s)", len(autosell_trades))

        trades = get_recent_trades(db, limit=10000)
        analytics = get_recent_analytics(db, limit=10000)

        starting_cash_usd = settings.PAPER_STARTING_CASH
        cash_flow: CashFromTrades = cash_from_trades(starting_cash_usd, trades)
        holdings_and_unrealized: HoldingsAndUnrealizedFromTrades = holdings_and_unrealized_from_trades(trades,
                                                                                                       token_prices)
        equity_usd = round(cash_flow.cash + holdings_and_unrealized.holdings, 2)

        snapshot = snapshot_portfolio(
            db,
            equity=equity_usd,
            cash=cash_flow.cash,
            holdings=holdings_and_unrealized.holdings,
        )

        positions_payload = await _compute_positions_payload(token_prices, positions)
        trades_payload = await _compute_trades_payload(trades)
        portfolio_payload = await _compute_portfolio_payload(token_prices, snapshot, trades, equity_curve(db))
        analytics_payload = await _compute_analytics_payload(analytics)

        ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": positions_payload})
        ws_manager.broadcast_json_threadsafe({"type": "portfolio", "payload": portfolio_payload})
        ws_manager.broadcast_json_threadsafe({"type": "trades", "payload": trades_payload})
        ws_manager.broadcast_json_threadsafe({"type": "analytics", "payload": analytics_payload})


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, db: Session = Depends(get_db)) -> None:
    """
    Websocket endpoint: streams portfolio/positions/trades/analytics and handles simple commands.
    """
    await ws.accept()
    ws_manager.connect(ws)
    log.info("[WS][CONNECT] Client connected")

    try:
        await _send_init(ws, db)
        while True:
            raw_message = await ws.receive_json()
            try:
                inbound = WebsocketInboundMessage.model_validate(raw_message)
            except ValidationError as exc:
                log.debug("[WS][RECV] Invalid message schema: %s", exc)
                await ws.send_json({"type": "error", "payload": "Invalid message schema"})
                continue

            message_type = inbound.type

            if message_type == "ping":
                await ws.send_json({"type": "pong"})
                log.debug("[WS][RECV] Ping → Pong")
            elif message_type == "refresh":
                await _send_init(ws, db)
                log.info("[WS][REFRESH] Full init payload sent on client request")
            else:
                log.debug("[WS][RECV] Unknown message type: %s", message_type)

    except WebSocketDisconnect:
        log.info("[WS][DISCONNECT] Client disconnected")
    except Exception as exc:
        log.exception("[WS][ERROR] WebSocket error: %s", exc)
        try:
            await ws.send_json({"type": "error", "payload": str(exc)})
        except Exception:
            pass
    finally:
        ws_manager.disconnect(ws)
        log.debug("[WS][CLEANUP] Socket removed from manager")
