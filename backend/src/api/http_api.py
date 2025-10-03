from __future__ import annotations

from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core import orchestrator
from src.core.pnl import (
    cash_from_trades,
    fifo_realized_pnl,
    holdings_and_unrealized_from_trades,
)
from src.core.prices import merge_prices_with_entry
from src.core.utils import timezone_now
from src.integrations.dexscreener_client import fetch_prices_by_addresses
from src.logging.logger import get_logger
from src.persistence import service
from src.persistence.dao.portfolio_snapshots import (
    get_latest_portfolio,
    snapshot_portfolio,
    equity_curve,
    ensure_initial_cash,
)
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


@router.get("/api/portfolio")
async def get_portfolio(db: Session = Depends(get_db)) -> Dict[str, Any]:
    snapshot = get_latest_portfolio(db, create_if_missing=True)
    positions = get_open_positions(db)

    addresses = [getattr(p, "address", "") for p in positions if getattr(p, "address", None)]
    live_prices = await fetch_prices_by_addresses(addresses)
    price_map = merge_prices_with_entry(positions, live_prices)

    trades = get_recent_trades(db, limit=10000)
    starting_cash: float = float(settings.PAPER_STARTING_CASH)
    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
    cash, _, _, _ = cash_from_trades(starting_cash, trades)
    holdings, unrealized_pnl = holdings_and_unrealized_from_trades(trades, price_map)
    equity = round(cash + holdings, 2)

    snapshot = snapshot_portfolio(db=db, equity=equity, cash=cash, holdings=holdings)
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
        equity, cash, holdings, realized_total, realized_24h
    )
    return payload


@router.get("/api/positions")
async def get_positions(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    positions = get_open_positions(db)
    addresses = [getattr(p, "address", "") for p in positions if getattr(p, "address", None)]
    live_prices = await fetch_prices_by_addresses(addresses)
    price_map = merge_prices_with_entry(positions, live_prices)

    result: List[Dict[str, Any]] = []
    for position in positions:
        addr = getattr(position, "address", "") or ""
        last_price: Optional[float] = price_map.get(addr)
        result.append(serialize_position(position, last_price))

    log.info("Returned open positions")
    log.debug("Returned %d open positions", len(result))
    return result


@router.get("/api/trades")
def get_trades(limit: int = 100, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = get_recent_trades(db, limit=limit)
    result = [serialize_trade(t) for t in rows]
    log.info("Returned recent trades")
    log.debug("Returned %d recent trades (limit=%d)", len(result), limit)
    return result


@router.post("/api/paper/reset")
def reset_paper(db: Session = Depends(get_db)) -> Dict[str, bool]:
    service.reset_paper(db)
    ensure_initial_cash(db)
    orchestrator.reset_runtime_state()
    log.info("Paper mode has been reset and initial cash ensured")
    return {"ok": True}


@router.get("/pnl/summary")
async def pnl_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    ALL_TIME_CUTOFF_HOURS = 10_000

    positions = get_open_positions(db)
    addresses = [getattr(p, "address", "") for p in positions if getattr(p, "address", None)]
    live_prices = await fetch_prices_by_addresses(addresses)
    price_map = merge_prices_with_entry(positions, live_prices)

    trades = get_recent_trades(db, limit=10000)
    realized_total, _ = fifo_realized_pnl(trades, cutoff_hours=ALL_TIME_CUTOFF_HOURS)
    _, unrealized_total = holdings_and_unrealized_from_trades(trades, price_map)
    total_usd = round(realized_total + unrealized_total, 2)

    trades_by_chain: DefaultDict[str, list] = defaultdict(list)
    for trade in trades:
        chain_key = (getattr(trade, "chain", "") or "unknown").lower()
        trades_by_chain[chain_key].append(trade)

    realized_by_chain: Dict[str, float] = {}
    unrealized_by_chain: Dict[str, float] = {}
    for chain_key, chain_trades in trades_by_chain.items():
        realized_chain, _ = fifo_realized_pnl(chain_trades, cutoff_hours=ALL_TIME_CUTOFF_HOURS)
        unrealized_chain = holdings_and_unrealized_from_trades(chain_trades, price_map)[1]
        realized_by_chain[chain_key] = round(realized_chain, 2)
        unrealized_by_chain[chain_key] = round(unrealized_chain, 2)

    by_chain: Dict[str, Dict[str, float]] = {}
    for chain_key in set(list(realized_by_chain.keys()) + list(unrealized_by_chain.keys())):
        r = realized_by_chain.get(chain_key, 0.0)
        u = unrealized_by_chain.get(chain_key, 0.0)
        by_chain[chain_key] = {"realizedUsd": r, "unrealizedUsd": u, "totalUsd": round(r + u, 2)}

    payload = {
        "realizedUsd": round(realized_total, 2),
        "unrealizedUsd": round(unrealized_total, 2),
        "totalUsd": total_usd,
        "byChain": by_chain,
    }
    log.info("PnL summary computed")
    log.debug(
        "PnL summary (realized=%.2f, unrealized=%.2f, total=%.2f, chains=%d)",
        payload["realizedUsd"], payload["unrealizedUsd"], payload["totalUsd"], len(by_chain)
    )
    return payload
