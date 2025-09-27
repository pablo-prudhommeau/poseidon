from __future__ import annotations

from collections import defaultdict
from http.client import HTTPException
from typing import Any, Dict, List, DefaultDict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.pnl import (
    latest_prices_for_positions,
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)
from src.logging.logger import get_logger
from src.persistence.db import get_db
from src.persistence.serializers import (
    serialize_trade,
    serialize_position,
    serialize_portfolio,
)

from fastapi import APIRouter, HTTPException
from datetime import timedelta
from src.persistence.db import SessionLocal
from src.persistence import crud

router = APIRouter()
log = get_logger(__name__)


@router.get("/api/portfolio")
async def get_portfolio(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return the current portfolio snapshot and derived metrics.

    Computes:
      - realized_total / realized_24h using FIFO
      - cash from the trade journal
      - holdings + unrealized_pnl using live prices (DexScreener)
      - equity (cash + holdings)

    Also writes a DB snapshot for the equity history.
    """
    # Latest snapshot and open positions
    snapshot = crud.get_latest_portfolio(db, create_if_missing=True)
    positions = crud.get_open_positions(db)

    # Live prices by address
    prices = await latest_prices_for_positions(positions)

    # All trades (or a large recent fallback if the helper does not exist)
    get_all = getattr(crud, "get_all_trades", None)
    trades = get_all(db) if callable(get_all) else crud.get_recent_trades(db, limit=10000)

    # Centralized computations (starting_cash taken directly from settings)
    starting_cash: float = float(settings.PAPER_STARTING_CASH)
    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
    cash, _, _, _ = cash_from_trades(starting_cash, trades)
    holdings, unrealized_pnl = holdings_and_unrealized(positions, prices)
    equity = round(cash + holdings, 2)

    # Persist an equity snapshot (pure write; no business logic in CRUD)
    snapshot = crud.snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings)

    payload = serialize_portfolio(
        snapshot,
        equity_curve=crud.equity_curve(db),
        realized_total=realized_total,
        realized_24h=realized_24h,
    )
    # Explicit field expected by the frontend
    payload["unrealized_pnl"] = unrealized_pnl

    log.debug(
        "Portfolio snapshot updated (equity=%.2f, cash=%.2f, holdings=%.2f, realized_total=%.2f, realized_24h=%.2f)",
        equity,
        cash,
        holdings,
        realized_total,
        realized_24h,
    )
    return payload


@router.get("/api/positions")
async def get_positions(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Return open positions enriched with a live last_price (DexScreener) for the UI."""
    positions = crud.get_open_positions(db)
    prices = await latest_prices_for_positions(positions)
    result: List[Dict[str, Any]] = []
    for position in positions:
        address = (getattr(position, "address", "") or "").lower()
        last_price: Optional[float] = prices.get(address)
        result.append(serialize_position(position, last_price))
    log.debug("Returned %d open positions", len(result))
    return result


@router.get("/api/trades")
def get_trades(limit: int = 100, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Return recent trades (serialized)."""
    trades = crud.get_recent_trades(db, limit=limit)
    result = [serialize_trade(t) for t in trades]
    log.debug("Returned %d recent trades (limit=%d)", len(result), limit)
    return result


@router.post("/api/paper/reset")
def reset_paper(db: Session = Depends(get_db)) -> Dict[str, bool]:
    """Reset PAPER mode data and ensure initial cash is seeded."""
    crud.reset_paper(db)
    crud.ensure_initial_cash(db)  # seed initial cash
    log.info("Paper mode has been reset and initial cash ensured")
    return {"ok": True}


@router.get("/pnl/summary")
async def pnl_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return a PnL summary consistent with orchestrator/ws_hub.

    Fields:
      - realizedUsd (total FIFO)
      - unrealizedUsd (live prices)
      - totalUsd
      - byChain: breakdown per chain (realized/unrealized/total)
    """
    ALL_TIME_CUTOFF_HOURS = 10_000  # effectively "all-time"

    positions = crud.get_open_positions(db)
    prices = await latest_prices_for_positions(positions)

    get_all = getattr(crud, "get_all_trades", None)
    trades = get_all(db) if callable(get_all) else crud.get_recent_trades(db, limit=10000)

    # Totals
    realized_total, _ = fifo_realized_pnl(trades, cutoff_hours=ALL_TIME_CUTOFF_HOURS)
    _, unrealized_total = holdings_and_unrealized(positions, prices)
    total_usd = round(realized_total + unrealized_total, 2)

    # Per-chain breakdown (FIFO per chain for realized, per-position for unrealized)
    trades_by_chain: DefaultDict[str, list] = defaultdict(list)
    for trade in trades:
        chain_key = (getattr(trade, "chain", "") or "unknown").lower()
        trades_by_chain[chain_key].append(trade)

    realized_by_chain: Dict[str, float] = {}
    for chain_key, chain_trades in trades_by_chain.items():
        realized_chain, _ = fifo_realized_pnl(chain_trades, cutoff_hours=ALL_TIME_CUTOFF_HOURS)
        realized_by_chain[chain_key] = realized_chain

    unrealized_by_chain: DefaultDict[str, float] = defaultdict(float)
    for position in positions:
        chain_key = (getattr(position, "chain", "") or "unknown").lower()
        address = (getattr(position, "address", "") or "").lower()
        last_price = float(prices.get(address, 0.0) or 0.0)
        if last_price <= 0.0:
            last_price = float(getattr(position, "entry", 0.0) or 0.0)
        entry_price = float(getattr(position, "entry", 0.0) or 0.0)
        quantity = float(getattr(position, "qty", 0.0) or 0.0)
        unrealized_by_chain[chain_key] += (last_price - entry_price) * quantity

    by_chain: Dict[str, Dict[str, float]] = {}
    for chain_key in set(list(realized_by_chain.keys()) + list(unrealized_by_chain.keys())):
        realized_usd = round(realized_by_chain.get(chain_key, 0.0), 2)
        unrealized_usd = round(unrealized_by_chain.get(chain_key, 0.0), 2)
        by_chain[chain_key] = {
            "realizedUsd": realized_usd,
            "unrealizedUsd": unrealized_usd,
            "totalUsd": round(realized_usd + unrealized_usd, 2),
        }

    payload = {
        "realizedUsd": round(realized_total, 2),
        "unrealizedUsd": round(unrealized_total, 2),
        "totalUsd": total_usd,
        "byChain": by_chain,
    }
    log.debug(
        "PnL summary computed (realized=%.2f, unrealized=%.2f, total=%.2f, chains=%d)",
        payload["realizedUsd"],
        payload["unrealizedUsd"],
        payload["totalUsd"],
        len(by_chain),
    )
    return payload

@router.get("/export/chart/{trade_id}")
def export_chart(trade_id: str, minutes_before: int = 720, minutes_after: int = 720, timeframe: str = "1m"):
    with SessionLocal() as s:
        tr = crud.get_trade(s, trade_id)
        if not tr:
            raise HTTPException(status_code=404, detail="trade not found")
        start = tr.timestamp - timedelta(minutes=minutes_before)
        end   = tr.timestamp + timedelta(minutes=minutes_after)

        candles = fetch_ohlcv(address=tr.address, chain=tr.chain, timeframe=timeframe,
                              start_ms=int(start.timestamp()*1000), end_ms=int(end.timestamp()*1000))

        payload = {
            "meta": {
                "symbol": tr.symbol, "address": tr.address, "chain": tr.chain,
                "timeframe": timeframe, "source": "dexscreener", "timezone": "UTC",
                "window": {"start": int(start.timestamp()*1000), "end": int(end.timestamp()*1000)}
            },
            "levels": {"entry": tr.entry_price, "sl": tr.stop_loss, "tp1": tr.take_profit_1, "tp2": tr.take_profit_2},
            "candles": candles,
            "marks": [
                {"t": int(tr.timestamp.timestamp()*1000), "type": "ENTRY", "price": tr.entry_price, "side": tr.side, "qty": tr.qty, "id": tr.id},
                *[m.as_dict() for m in crud.get_trade_marks(s, tr.position_id)]  # TP/SL/EXIT
            ]
        }
        return payload

