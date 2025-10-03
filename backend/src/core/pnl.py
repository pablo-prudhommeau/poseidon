from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum
from typing import Any, Deque, Dict, Iterable, Tuple

from src.logging.logger import get_logger
from src.persistence.models import Trade

log = get_logger(__name__)

# ---------------------------- extractors (no normalization) -------------------

def _get_quantity(obj: Any) -> float:
    return float(getattr(obj, "qty", getattr(obj, "quantity", 0.0)) or 0.0)

def _get_price(obj: Any) -> float:
    return float(getattr(obj, "price", getattr(obj, "price_usd", 0.0)) or 0.0)

def _get_fee(obj: Any) -> float:
    return float(getattr(obj, "fee", 0.0) or 0.0)

def _get_address(obj: Any) -> str:
    return getattr(obj, "address", "") or ""

def _get_entry(obj: Any) -> float:
    return float(getattr(obj, "entry", 0.0) or 0.0)

def _get_created_at(obj: Any) -> datetime:
    dt = getattr(obj, "created_at", None).astimezone()
    return dt

def _normalize_side(value: Any) -> str:
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

def _D(x: float | int | str) -> Decimal:
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

# -------------------------------- Realized PnL --------------------------------

def fifo_realized_pnl(trades: Iterable[Trade], *, cutoff_hours: int = 24) -> Tuple[float, float]:
    """
    FIFO par **adresse telle quelle**. Les frais sont répartis au prorata.
    """
    lots_by_addr: Dict[str, Deque[list[float]]] = defaultdict(deque)
    realized_total = Decimal("0")
    realized_recent = Decimal("0")
    cutoff_ts = datetime.now().astimezone() - timedelta(hours=cutoff_hours)

    for tr in sorted(trades, key=_get_created_at):
        side = _normalize_side(getattr(tr, "side", None))
        addr = _get_address(tr)
        qty = _get_quantity(tr)
        px = _get_price(tr)
        fee = _get_fee(tr)
        if qty <= 0.0 or px <= 0.0:
            continue

        if side == "BUY":
            fee_u = fee / qty if qty > 0.0 else 0.0
            lots_by_addr[addr].append([qty, px, fee_u])
            continue

        if side == "SELL":
            sell_fee_u = fee / qty if qty > 0.0 else 0.0
            remaining = qty
            pnl = Decimal("0")
            while remaining > 1e-12 and lots_by_addr[addr]:
                lot_qty, lot_px, buy_fee_u = lots_by_addr[addr][0]
                matched = min(remaining, lot_qty)
                contrib = (px - lot_px) * matched
                contrib -= buy_fee_u * matched
                contrib -= sell_fee_u * matched
                pnl += _D(contrib)

                lot_qty -= matched
                remaining -= matched
                if lot_qty <= 1e-12:
                    lots_by_addr[addr].popleft()
                else:
                    lots_by_addr[addr][0][0] = lot_qty

            realized_total += pnl
            if _get_created_at(tr) >= cutoff_ts:
                realized_recent += pnl

    q = Decimal("0.01")
    return float(realized_total.quantize(q, rounding=ROUND_HALF_UP)), float(
        realized_recent.quantize(q, rounding=ROUND_HALF_UP)
    )

# ----------------------------------- Cash -------------------------------------

def cash_from_trades(start_cash: float, trades: Iterable[Any]) -> Tuple[float, float, float, float]:
    total_buys = _D(0)
    total_sells = _D(0)
    total_fees = _D(0)

    for tr in trades:
        side = _normalize_side(getattr(tr, "side", None))
        qty = _get_quantity(tr)
        px = _get_price(tr)
        fee = _get_fee(tr)
        if qty <= 0.0 or px <= 0.0:
            continue
        notional = _D(px * qty)
        if side == "BUY":
            total_buys += notional
        elif side == "SELL":
            total_sells += notional
        total_fees += _D(fee)

    cash = _D(start_cash) - total_buys + total_sells - total_fees
    q = Decimal("0.01")
    return (
        float(cash.quantize(q, rounding=ROUND_HALF_UP)),
        float(total_buys.quantize(q, rounding=ROUND_HALF_UP)),
        float(total_sells.quantize(q, rounding=ROUND_HALF_UP)),
        float(total_fees.quantize(q, rounding=ROUND_HALF_UP)),
    )

# -------------------------- Holdings / Unrealized -----------------------------

def holdings_and_unrealized_from_trades(trades: Iterable[Trade], address_price: Dict[str, float]) -> Tuple[float, float]:
    """
    Reconstitue les lots restants par **adresse telle quelle**, puis valorise avec `address_price`
    (clé = adresse d’origine), sans normalisation.
    """
    lots_by_addr: Dict[str, Deque[list[float]]] = defaultdict(deque)
    for tr in sorted(trades, key=_get_created_at):
        side = _normalize_side(getattr(tr, "side", None))
        addr = _get_address(tr)
        qty = _get_quantity(tr)
        px = _get_price(tr)
        fee = _get_fee(tr)
        if qty <= 0.0 or px <= 0.0:
            continue
        if side == "BUY":
            fee_u = fee / qty if qty > 0.0 else 0.0
            lots_by_addr[addr].append([qty, px, fee_u])
        elif side == "SELL":
            remaining = qty
            while remaining > 1e-12 and lots_by_addr[addr]:
                lot_qty, lot_px, fee_u = lots_by_addr[addr][0]
                matched = min(remaining, lot_qty)
                lot_qty -= matched
                remaining -= matched
                if lot_qty <= 1e-12:
                    lots_by_addr[addr].popleft()
                else:
                    lots_by_addr[addr][0][0] = lot_qty

    holdings = _D(0)
    unreal = _D(0)
    for addr, dq in lots_by_addr.items():
        last = float(address_price.get(addr, 0.0) or 0.0)
        last_for_value = last if last > 0 else 0.0
        for lot_qty, lot_px, fee_u in dq:
            holdings += _D(lot_qty * last_for_value)
            unreal += _D((last_for_value - (lot_px + fee_u)) * lot_qty)

    q = Decimal("0.01")
    return float(holdings.quantize(q, rounding=ROUND_HALF_UP)), float(
        unreal.quantize(q, rounding=ROUND_HALF_UP)
    )

# ---------------------------------- Prices ------------------------------------

async def latest_prices_for_positions(positions: Iterable[Any]) -> Dict[str, float]:
    """
    (Compat) Récupère les prix live **en conservant les clés** = adresses de `positions`.
    """
    from src.integrations.dexscreener_client import fetch_prices_by_addresses
    addrs = [getattr(p, "address", "") for p in positions if getattr(p, "address", None)]
    return await fetch_prices_by_addresses(addrs)
