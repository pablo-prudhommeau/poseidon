from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Deque, Dict, Iterable, Tuple

from src.logging.logger import get_logger
from src.persistence.models import Trade

log = get_logger(__name__)


# -----------------------------------------------------------------------------
# Generic extractors
# -----------------------------------------------------------------------------

def _get_qty(obj: Any) -> float:
    """Return trade/position quantity from common attribute names."""
    return float(getattr(obj, "qty", getattr(obj, "quantity", 0.0)) or 0.0)


def _get_price(obj: Any) -> float:
    """Return unit price from common attribute names."""
    return float(getattr(obj, "price", getattr(obj, "price_usd", 0.0)) or 0.0)


def _get_fee(obj: Any) -> float:
    """Return execution fee if present; otherwise 0.0."""
    return float(getattr(obj, "fee", 0.0) or 0.0)


def _get_addr(obj: Any) -> str:
    """Return a normalized (lowercased) on-chain address if present."""
    return (getattr(obj, "address", "") or "").lower()


def _get_entry(obj: Any) -> float:
    """Return entry price for a position, defaulting to 0.0."""
    return float(getattr(obj, "entry", 0.0) or 0.0)


def _get_qty_pos(obj: Any) -> float:
    """Return position quantity, defaulting to 0.0."""
    return float(getattr(obj, "qty", 0.0) or 0.0)


def _get_created_at(obj: Any) -> datetime:
    """Return a UTC-aware creation timestamp for comparisons and sorting."""
    return getattr(obj, "created_at", None).astimezone()


# -----------------------------------------------------------------------------
# Side normalization (Enum or string)
# -----------------------------------------------------------------------------

def _normalize_side(value: Any) -> str:
    """
    Normalize a trade side to the canonical 'BUY' or 'SELL' string.

    Accepts:
      - Enum (e.g., Side.BUY / Side.SELL) -> uses .value if present
      - String ('buy'/'BUY'/etc.)
      - Anything else -> stringified then uppercased
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.upper()
    if isinstance(value, Enum):
        try:
            return str(getattr(value, "value", value)).upper()
        except Exception:
            return str(value).upper()
    return str(value).upper()


# -----------------------------------------------------------------------------
# PnL / Cash
# -----------------------------------------------------------------------------

def fifo_realized_pnl(trades: Iterable[Trade], *, cutoff_hours: int = 24) -> Tuple[float, float]:
    """Compute realized PnL using FIFO lots per address.

    Args:
        trades: Iterable of trade-like objects (BUY/SELL).
        cutoff_hours: Hours window to compute the "recent" realized PnL.

    Returns:
        (realized_total, realized_last_{cutoff_hours}h) — both rounded to 2 decimals.
    """
    lots_by_address: Dict[str, Deque[list[float]]] = defaultdict(deque)  # address -> deque[[qty, price], ...]
    realized_total = 0.0
    realized_recent = 0.0
    cutoff_timestamp = datetime.now(timezone.utc) - timedelta(hours=cutoff_hours)
    trades_sorted = sorted(trades, key=_get_created_at)

    for trade in trades_sorted:
        side = _normalize_side(getattr(trade, "side", None))
        address = _get_addr(trade)
        quantity = _get_qty(trade)
        price = _get_price(trade)

        if quantity <= 0.0 or price <= 0.0:
            continue

        if side == "BUY":
            lots_by_address[address].append([quantity, price])
            continue

        if side == "SELL":
            remaining_to_match = quantity
            pnl_for_this_sell = 0.0

            while remaining_to_match > 1e-12 and lots_by_address[address]:
                lot_qty, lot_px = lots_by_address[address][0]
                matched = min(remaining_to_match, lot_qty)
                pnl_for_this_sell += (price - lot_px) * matched
                lot_qty -= matched
                remaining_to_match -= matched

                if lot_qty <= 1e-12:
                    lots_by_address[address].popleft()
                else:
                    lots_by_address[address][0][0] = lot_qty


            realized_total += pnl_for_this_sell
            if _get_created_at(trade) >= cutoff_timestamp:
                realized_recent += pnl_for_this_sell

    realized_total = round(realized_total, 2)
    realized_recent = round(realized_recent, 2)
    return realized_total, realized_recent


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

    for trade in trades:
        side = _normalize_side(getattr(trade, "side", None))
        quantity = _get_qty(trade)
        price = _get_price(trade)
        fee = _get_fee(trade)

        if quantity <= 0.0 or price <= 0.0:
            continue

        if side == "BUY":
            total_buys += price * quantity
        elif side == "SELL":
            total_sells += price * quantity

        total_fees += fee

    cash = float(start_cash) - total_buys + total_sells - total_fees
    cash, total_buys, total_sells, total_fees = round(cash, 2), round(total_buys, 2), round(total_sells, 2), round(total_fees, 2)
    return cash, total_buys, total_sells, total_fees


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

    for position in positions:
        address = _get_addr(position)
        last_price = float(address_price.get(address, 0.0) or 0.0)
        if last_price <= 0.0:
            last_price = _get_entry(position)

        quantity = _get_qty_pos(position)
        entry_price = _get_entry(position)

        holdings_value += last_price * quantity
        unrealized += (last_price - entry_price) * quantity

    holdings_value, unrealized = round(holdings_value, 2), round(unrealized, 2)
    return holdings_value, unrealized


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
    prices = await fetch_prices_by_addresses(unique_addresses)
    return prices
