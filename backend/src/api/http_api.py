from __future__ import annotations

from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core import orchestrator
from src.core.pnl import (
    cash_from_trades,
    fifo_realized_pnl,
    holdings_and_unrealized,
    latest_prices_for_positions,
)
from src.logging.logger import get_logger
from src.persistence import service
from src.persistence.dao.portfolio_snapshots import get_latest_portfolio, snapshot_portfolio, equity_curve, \
    ensure_initial_cash
from src.persistence.dao.positions import get_open_positions
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import get_db
from src.persistence.serializers import (
    serialize_portfolio,
    serialize_position,
    serialize_trade,
)

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
    snapshot = get_latest_portfolio(db, create_if_missing=True)
    positions = get_open_positions(db)

    prices = await latest_prices_for_positions(positions)

    trades = get_recent_trades(db, limit=10000)

    starting_cash: float = float(settings.PAPER_STARTING_CASH)
    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
    cash, _, _, _ = cash_from_trades(starting_cash, trades)
    holdings, unrealized_pnl = holdings_and_unrealized(positions, prices)
    equity = round(cash + holdings, 2)

    snapshot = snapshot_portfolio(equity=equity, cash=cash, holdings=holdings)

    payload = serialize_portfolio(
        snapshot,
        equity_curve=equity_curve(db),
        realized_total=realized_total,
        realized_24h=realized_24h,
    )
    payload["unrealized_pnl"] = unrealized_pnl

    log.info("Portfolio snapshot refreshed")
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
    positions = get_open_positions(db)
    prices = await latest_prices_for_positions(positions)

    result: List[Dict[str, Any]] = []
    for position in positions:
        address = (getattr(position, "address", "") or "").lower()
        last_price: Optional[float] = prices.get(address)
        result.append(serialize_position(position, last_price))

    log.info("Returned open positions")
    log.debug("Returned %d open positions", len(result))
    return result


@router.get("/api/trades")
def get_trades(limit: int = 100, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Return recent trades (serialized)."""
    trades = get_recent_trades(db, limit=limit)
    result = [serialize_trade(t) for t in trades]

    log.info("Returned recent trades")
    log.debug("Returned %d recent trades (limit=%d)", len(result), limit)
    return result


@router.post("/api/paper/reset")
def reset_paper(db: Session = Depends(get_db)) -> Dict[str, bool]:
    """Reset PAPER mode data and ensure initial cash is seeded."""
    service.reset_paper(db)
    ensure_initial_cash(db)
    orchestrator.reset_runtime_state()
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
    ALL_TIME_CUTOFF_HOURS = 10_000

    positions = get_open_positions(db)
    prices = await latest_prices_for_positions(positions)

    trades = get_recent_trades(db, limit=10000)

    realized_total, _ = fifo_realized_pnl(trades, cutoff_hours=ALL_TIME_CUTOFF_HOURS)
    _, unrealized_total = holdings_and_unrealized(positions, prices)
    total_usd = round(realized_total + unrealized_total, 2)

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

    log.info("PnL summary computed")
    log.debug(
        "PnL summary (realized=%.2f, unrealized=%.2f, total=%.2f, chains=%d)",
        payload["realizedUsd"],
        payload["unrealizedUsd"],
        payload["totalUsd"],
        len(by_chain),
    )
    return payload
