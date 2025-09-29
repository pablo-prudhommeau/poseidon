from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, Iterable, Tuple

from src.persistence.models import Trade


def _get_qty(obj: Any) -> float:
    """Return trade/position quantity from common attribute names."""
    return float(getattr(obj, "qty", getattr(obj, "quantity", 0.0)) or 0.0)


def _get_price(obj: Any) -> float:
    """Return unit price from common attribute names."""
    return float(getattr(obj, "price", getattr(obj, "price_usd", 0.0)) or 0.0)


def _get_created_at(obj: Any) -> datetime:
    """Return creation timestamp if present; otherwise a minimal datetime."""
    return getattr(obj, "created_at", None) or datetime.min


def _get_addr(obj: Any) -> str:
    """Return a normalized (lowercased) on-chain address if present."""
    return (getattr(obj, "address", "") or "").lower()


def _get_entry(obj: Any) -> float:
    """Return entry price for a position, defaulting to 0.0."""
    return float(getattr(obj, "entry", 0.0) or 0.0)


def _get_qty_pos(obj: Any) -> float:
    """Return position quantity, defaulting to 0.0."""
    return float(getattr(obj, "qty", 0.0) or 0.0)


def fifo_realized_pnl(trades: Iterable[Trade], *, cutoff_hours: int = 24) -> Tuple[float, float]:
    """Compute realized PnL using FIFO lots per address.

    Args:
        trades: Iterable of trade-like objects (BUY/SELL).
        cutoff_hours: Hours window to compute the "recent" realized PnL.

    Returns:
        (realized_total, realized_last_{cutoff_hours}h) — both rounded to 2 decimals.
    """
    lots: Dict[str, Deque[list[float]]] = defaultdict(deque)  # address -> deque of [qty, price]
    realized_total = 0.0
    realized_recent = 0.0
    cutoff_ts = datetime.utcnow() - timedelta(hours=cutoff_hours)

    trades_sorted = sorted(trades, key=_get_created_at)
    for t in trades_sorted:
        side = t.side
        address = _get_addr(t)
        qty = _get_qty(t)
        price = _get_price(t)
        if qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            lots[address].append([qty, price])
            continue

        if side == "SELL":
            remaining = qty
            pnl_sell = 0.0
            while remaining > 1e-12 and lots[address]:
                lot_qty, lot_px = lots[address][0]
                take = min(remaining, lot_qty)
                pnl_sell += (price - lot_px) * take
                lot_qty -= take
                remaining -= take
                if lot_qty <= 1e-12:
                    lots[address].popleft()
                else:
                    lots[address][0][0] = lot_qty
            realized_total += pnl_sell
            if _get_created_at(t) >= cutoff_ts:
                realized_recent += pnl_sell

    return round(realized_total, 2), round(realized_recent, 2)


def cash_from_trades(start_cash: float, trades: Iterable[Any]) -> Tuple[float, float, float, float]:
    """Compute cash balance and aggregates from the trade journal.

    Args:
        start_cash: Starting cash amount.
        trades: Iterable of trade-like objects.

    Returns:
        (cash, total_buys, total_sells, total_fees) — all rounded to 2 decimals.
    """
    total_buys = 0.0
    total_sells = 0.0
    total_fees = 0.0

    for t in trades:
        side = t.side
        qty = _get_qty(t)
        price = _get_price(t)
        fee = float(getattr(t, "fee", 0.0) or 0.0)
        if qty <= 0 or price <= 0:
            continue
        if side == "BUY":
            total_buys += price * qty
        elif side == "SELL":
            total_sells += price * qty
        total_fees += fee

    cash = float(start_cash) - total_buys + total_sells - total_fees
    return round(cash, 2), round(total_buys, 2), round(total_sells, 2), round(total_fees, 2)


def holdings_and_unrealized(positions: Iterable[Any], address_price: Dict[str, float]) -> Tuple[float, float]:
    """Compute portfolio holdings valuation and unrealized PnL.

    Args:
        positions: Iterable of position-like objects.
        address_price: Mapping of address -> last price (USD).

    Returns:
        (holdings_value_usd, unrealized_pnl_usd) — rounded to 2 decimals.
    """
    holdings_value = 0.0
    unrealized = 0.0
    for p in positions:
        addr = _get_addr(p)
        last = float(address_price.get(addr, 0.0) or 0.0)
        if last <= 0.0:
            last = _get_entry(p)
        qty = _get_qty_pos(p)
        entry = _get_entry(p)
        holdings_value += last * qty
        unrealized += (last - entry) * qty
    return round(holdings_value, 2), round(unrealized, 2)


async def latest_prices_for_positions(positions: Iterable[Any]) -> Dict[str, float]:
    """Fetch multi-chain DexScreener prices by the addresses found in positions.

    Args:
        positions: Iterable of position-like objects.

    Returns:
        Dict[address_lower, last_price].
    """
    addresses = [_get_addr(p) for p in positions if _get_addr(p)]
    unique_addresses = list(dict.fromkeys(addresses))
    if not unique_addresses:
        return {}
    # Late import to avoid circular dependencies
    from src.integrations.dexscreener_client import fetch_prices_by_addresses
    return await fetch_prices_by_addresses(unique_addresses)
