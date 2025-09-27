from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Dict, Optional

from src.api.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.pnl import (
    latest_prices_for_positions,
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)
from src.persistence import crud
from src.persistence.db import SessionLocal
from src.persistence.serializers import serialize_trade, serialize_portfolio


@contextmanager
def _session(db: Optional[SessionLocal] = None):
    """Yield a DB session, committing on success and rolling back on error."""
    if db is not None:
        # Reuse caller-provided session without owning commit/close lifecycle.
        yield db
        return
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def on_trade(
        side: str,
        symbol: str,
        price: float,
        qty: float,
        *,
        address: str = "",
        chain: str,
        fee: float = 0.0,
        status: str = "PAPER",
        db=None,
) -> None:
    """Record a trade, trigger any threshold-based autosells, then (as needed)
    schedule a unified recompute + broadcast of positions and portfolio.
    """
    with _session(db) as s:
        tr = crud.record_trade(
            s,
            side=side,
            symbol=symbol,
            chain=chain,
            address=address,
            qty=qty,
            price=price,
            fee=fee,
            status=status,
        )
        ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(tr)})

        # Trigger autosells for this symbol at the current price
        auto_trades = crud.check_thresholds_and_autosell(s, symbol=symbol, last_price=price)
        for atr in auto_trades:
            ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(atr)})

            # Recompute + broadcast (positions + portfolio) in the background
            _schedule_recompute_and_broadcast()


def on_position_opened(*, address: str, db=None) -> None:
    """Hook called when a position is opened."""
    _schedule_recompute_and_broadcast()


def on_position_closed(*, address: str, db=None) -> None:
    """Hook called when a position is closed."""
    _schedule_recompute_and_broadcast()


def on_portfolio_snapshot(*, latest: bool = True, db=None) -> None:
    """Hook called after a portfolio snapshot is written."""
    _schedule_recompute_and_broadcast()


def _schedule_recompute_and_broadcast() -> None:
    """Schedule `_recompute_and_broadcast()` without blocking the caller thread."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_recompute_and_broadcast())
    except RuntimeError:
        # No active loop (called from a sync context)
        asyncio.run(_recompute_and_broadcast())


async def _recompute_and_broadcast() -> None:
    """Recompute with PnL helpers, then broadcast:
      - positions (with live last_price per address)
      - portfolio (unrealized, realized 24h/total, equity, etc.)
    Writes a snapshot (equity/cash/holdings) via `crud.snapshot_portfolio`.
    """
    # 1) Load data
    with SessionLocal() as db:
        positions = crud.get_open_positions(db)
        get_all = getattr(crud, "get_all_trades", None)
        trades = get_all(db) if callable(get_all) else crud.get_recent_trades(db, limit=10000)

    # 2) Live prices by address
    prices: Dict[str, float] = {}
    if positions:
        prices = await latest_prices_for_positions(positions)

    # 3) Centralized computations
    starting_cash = float(settings.PAPER_STARTING_CASH)
    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
    cash, _, _, _ = cash_from_trades(starting_cash, trades)
    holdings, unrealized = holdings_and_unrealized(positions, prices)
    equity = round(cash + holdings, 2)

    # 4) Snapshot + payloads and broadcast
    with SessionLocal() as db:
        # Snapshot (write-only: values already computed)
        snap = crud.snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings)

        # Positions with live last_price
        pos_payload = crud.serialize_positions_with_prices_by_address(db, prices)

        # Portfolio consistent with orchestrator/ws_hub
        portfolio_payload = serialize_portfolio(
            snap,
            equity_curve=crud.equity_curve(db),
            realized_total=realized_total,
            realized_24h=realized_24h,
        )
        portfolio_payload["unrealized_pnl"] = unrealized

    # Thread-safe broadcast
    ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": pos_payload})
    ws_manager.broadcast_json_threadsafe({"type": "portfolio", "payload": portfolio_payload})


# Public alias used by Trader._rebroadcast_portfolio()
async def rebroadcast_portfolio() -> None:
    """Recompute and broadcast portfolio/positions immediately."""
    await _recompute_and_broadcast()
