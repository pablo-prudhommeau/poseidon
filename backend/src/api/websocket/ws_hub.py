from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.websocket.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.structures.structures import (
    Token,
    HoldingsAndUnrealizedPnl,
    RealizedPnl,
    EquityCurve,
    CashFromTrades,
    WebsocketInboundMessage,
)
from src.core.utils.pnl_utils import (
    fifo_realized_pnl,
    holdings_and_unrealized_from_positions,
    cash_from_trades,
)
from src.integrations.dexscreener.dexscreener_client import fetch_prices_by_tokens
from src.integrations.dexscreener.dexscreener_structures import TokenPrice
from src.integrations.dexscreener.dexscreener_consistency_guard import (
    DexConsistencyGuard,
    PairIdentity,
    Observation,
    WindowActivity,
    ConsistencyVerdict,
)
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
from src.persistence.models import PortfolioSnapshot, Position, Trade, Analytics, Phase
from src.persistence.serializers import serialize_trade, serialize_portfolio, serialize_analytics

router = APIRouter()
log = get_logger(__name__)

_guard = DexConsistencyGuard(
    window_size=settings.DEX_INCONSISTENCY_WINDOW_SIZE,
    alternation_min_cycles=settings.DEX_INCONSISTENCY_ALTERNATION_CYCLES,
    jump_factor=settings.DEX_INCONSISTENCY_JUMP_FACTOR,
    fields_mismatch_min=settings.DEX_INCONSISTENCY_FIELDS_MISMATCH_MIN,
    staleness_horizon=timedelta(seconds=settings.MARKETDATA_MAX_STALE_SECONDS),
)


async def _compute_trades_payload(trades: List[Trade]) -> List[Dict[str, object]]:
    """Serialize trades for frontend consumption."""
    return [serialize_trade(t) for t in trades]


async def _compute_analytics_payload(analytics: List[Analytics]) -> List[Dict[str, object]]:
    """Serialize analytics rows for frontend consumption."""
    return [serialize_analytics(a) for a in analytics]


async def _compute_positions_payload(
        token_prices: List[TokenPrice],
        positions: List[Position],
) -> List[Dict[str, object]]:
    """Merge open positions with latest token prices and serialize for the frontend."""
    return serialize_positions_with_token_prices(positions, token_prices)


async def _compute_portfolio_payload(
        token_prices: List[TokenPrice],
        portfolio_snapshot: PortfolioSnapshot,
        positions: List[Position],
        trades: List[Trade],
        equity_curve_data: EquityCurve,
) -> Dict[str, object]:
    """Compute and serialize the portfolio summary, including realized/unrealized PnL."""
    realized: RealizedPnl = fifo_realized_pnl(trades, cutoff_hours=24)
    holdings_and_unrealized: HoldingsAndUnrealizedPnl = holdings_and_unrealized_from_positions(positions, token_prices)

    return serialize_portfolio(
        portfolio_snapshot,
        equity_curve=equity_curve_data,
        realized_total=realized.total,
        realized_24h=realized.recent,
        unrealized=holdings_and_unrealized.unrealized_pnl,
    )


async def _send_init(ws: WebSocket, db: Session) -> None:
    """Send the initial snapshot to a single websocket client."""
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
    analytics_rows = get_recent_analytics(db, limit=10000)

    portfolio_payload = await _compute_portfolio_payload(token_prices, snapshot, positions, trades, equity_curve(db))
    positions_payload = await _compute_positions_payload(token_prices, positions)
    trades_payload = await _compute_trades_payload(trades)
    analytics_payload = await _compute_analytics_payload(analytics_rows)

    payload: Dict[str, object] = {
        "status": {"paperMode": settings.PAPER_MODE, "interval": settings.TREND_INTERVAL_SEC},
        "portfolio": portfolio_payload,
        "positions": positions_payload,
        "trades": trades_payload,
        "analytics": analytics_payload,
    }
    await ws.send_json({"type": "init", "payload": jsonable_encoder(payload)})
    log.info("[WS][INIT] Initial snapshot sent.")


def schedule_full_recompute_broadcast() -> None:
    """
    Schedule a full recomputation and broadcast on the running event loop.

    Call from non-async contexts; the coroutine is scheduled on the server loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.debug("[WS][REBROADCAST] No running loop; recompute will happen on next orchestrator tick.")
        return

    if not loop.is_running() or loop.is_closed():
        log.debug("[WS][REBROADCAST] Event loop not running; recompute will happen on next orchestrator tick.")
        return

    loop.call_soon_threadsafe(lambda: loop.create_task(_recompute_positions_portfolio_analytics_and_broadcast()))


async def _recompute_positions_portfolio_analytics_and_broadcast() -> None:
    """
    Recompute positions, portfolio, analytics and broadcast to all websocket clients.

    Also evaluates autosell thresholds using the latest token prices. Any newly
    created trades are broadcast immediately to keep the UI consistent.
    """
    from src.core.jobs.trending.execution_stage import AnalyticsRecorder
    from src.persistence.service import check_thresholds_and_autosell

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
        staled_keys: set[str] = set()

        # Runtime consistency guard: ONLY multi-field jumps + ABAB
        for price in token_prices:
            try:
                pair = PairIdentity(
                    chain=price.token.chain,
                    token_address=price.token.tokenAddress,
                    pair_address=price.token.pairAddress,
                )
                observation = Observation(
                    as_of=price.asOf,
                    liquidity_usd=price.liquidityUsd,
                    fully_diluted_valuation_usd=price.fdvUsd,
                    market_cap_usd=price.marketCapUsd,
                    window_5m=WindowActivity(
                        buys=price.buys5m,
                        sells=price.sells5m,
                    ),
                    window_1h=WindowActivity(
                        buys=(price.txns.h1.buys if (price.txns and price.txns.h1) else None),
                        sells=(price.txns.h1.sells if (price.txns and price.txns.h1) else None),
                    ),
                    window_6h=WindowActivity(
                        buys=(price.txns.h6.buys if (price.txns and price.txns.h6) else None),
                        sells=(price.txns.h6.sells if (price.txns and price.txns.h6) else None),
                    ),
                    window_24h=WindowActivity(
                        buys=(price.txns.h24.buys if (price.txns and price.txns.h24) else None),
                        sells=(price.txns.h24.sells if (price.txns and price.txns.h24) else None),
                    ),
                )
                verdict = _guard.observe(pair, observation)
                if verdict == ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION:
                    key = pair.key()
                    staled_keys.add(key)

                    # Mark position as STALED if still OPEN/PARTIAL
                    position = (
                        db.execute(
                            select(Position).where(
                                Position.chain == price.token.chain,
                                Position.symbol == price.token.symbol,
                                Position.tokenAddress == price.token.tokenAddress,
                                Position.pairAddress == price.token.pairAddress,
                                Position.phase.in_([Phase.OPEN, Phase.PARTIAL]),
                                )
                        )
                        .scalars()
                        .first()
                    )
                    if position:
                        position.phase = Phase.STALED
                        db.commit()
                        log.warning(
                            "[WS][STALED][TRIGGER] symbol=%s token=%s pair=%s reason=DEX_INCONSISTENT_DATA",
                            position.symbol,
                            position.tokenAddress,
                            position.pairAddress,
                        )
            except Exception as exc:
                log.warning("[WS][DEX][CONSISTENCY] Check failed for %s - %s", price.token, exc)

        # Autosell evaluation (skip STALED keys)
        for price in token_prices:
            staled_key = f"{price.token.chain}:{price.token.pairAddress or price.token.tokenAddress}".lower()
            if staled_key in staled_keys:
                log.info("[WS][AUTOSELL][SKIP][STALED] token=%s pair=%s", price.token.tokenAddress, price.token.pairAddress)
                continue

            try:
                if price.priceUsd is None or price.priceUsd <= 0.0:
                    continue
                created = check_thresholds_and_autosell(db, token=price.token, last_price=float(price.priceUsd))
                if created:
                    autosell_trades.extend(created)
            except Exception as exc:
                log.warning("[WS][AUTOSELL] Threshold evaluation failed for %s - %s", price.token, exc)

        for created in autosell_trades:
            ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(created)})
        if autosell_trades:
            log.info("[WS][AUTOSELL] Broadcasted %d autosell trade(s).", len(autosell_trades))

        # Recompute aggregates and broadcast
        trades = get_recent_trades(db, limit=10000)
        analytics_rows = get_recent_analytics(db, limit=10000)

        starting_cash_usd: float = settings.PAPER_STARTING_CASH
        cash_flow: CashFromTrades = cash_from_trades(starting_cash_usd, trades)
        holdings_and_unrealized: HoldingsAndUnrealizedPnl = holdings_and_unrealized_from_positions(positions, token_prices)
        equity_usd: float = round(cash_flow.cash + holdings_and_unrealized.holdings, 2)

        snapshot = snapshot_portfolio(
            db,
            equity=equity_usd,
            cash=cash_flow.cash,
            holdings=holdings_and_unrealized.holdings,
        )

        positions_payload = await _compute_positions_payload(token_prices, positions)
        trades_payload = await _compute_trades_payload(trades)
        portfolio_payload = await _compute_portfolio_payload(token_prices, snapshot, positions, trades, equity_curve(db))
        analytics_payload = await _compute_analytics_payload(analytics_rows)

        ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": positions_payload})
        ws_manager.broadcast_json_threadsafe({"type": "portfolio", "payload": portfolio_payload})
        ws_manager.broadcast_json_threadsafe({"type": "trades", "payload": trades_payload})
        ws_manager.broadcast_json_threadsafe({"type": "analytics", "payload": analytics_payload})
        log.info("[WS][BROADCAST] positions/portfolio/trades/analytics refreshed.")


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, db: Session = Depends(get_db)) -> None:
    """
    WebSocket endpoint: streams portfolio/positions/trades/analytics and handles simple commands.
    """
    await ws.accept()
    ws_manager.connect(ws)
    log.info("[WS][CONNECT] Client connected.")

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
                log.debug("[WS][RECV] Ping → Pong.")
            elif message_type == "refresh":
                await _send_init(ws, db)
                log.info("[WS][REFRESH] Full init payload sent on client request.")
            else:
                log.debug("[WS][RECV] Unknown message type: %s", message_type)

    except WebSocketDisconnect:
        log.info("[WS][DISCONNECT] Client disconnected.")
    except Exception as exc:
        log.exception("[WS][ERROR] WebSocket error: %s", exc)
        try:
            await ws.send_json({"type": "error", "payload": str(exc)})
        except Exception:
            pass
    finally:
        ws_manager.disconnect(ws)
        log.debug("[WS][CLEANUP] Socket removed from manager.")
