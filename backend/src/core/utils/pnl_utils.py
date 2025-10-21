from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum
from typing import Deque, Dict, Iterable, Tuple, List

from src.logging.logger import get_logger
from src.persistence.models import Trade

log = get_logger(__name__)


# --------------------------- Time helpers --------------------------- #

def _now_tz() -> datetime:
    """Return current time with timezone information."""
    return datetime.now().astimezone()


def _get_created_at(obj: object) -> datetime:
    """
    Safe accessor for created_at with timezone normalization.
    """
    dt = getattr(obj, "created_at", None)
    try:
        return dt.astimezone() if dt is not None else _now_tz()
    except Exception:
        return _now_tz()


# --------------------------- Normalizers --------------------------- #

def _normalize_side(value: object) -> str:
    """Normalize side to uppercase string."""
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
    """Safe Decimal constructor from common primitives."""
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


# --------------------------- Core PnL --------------------------- #

def fifo_realized_pnl(trades: Iterable[Trade], *, cutoff_hours: int = 24) -> Tuple[float, float]:
    """
    Compute realized PnL using FIFO **per pair address when available, otherwise per token address**.

    Policy:
        - Buy fees are amortized per-unit into cost basis.
        - Sell fee is applied to the matched quantity on the sell side.
        - Grouping key is pairAddress if present on the trade row; otherwise tokenAddress.
    """
    lots_by_addr: Dict[str, Deque[list[float]]] = defaultdict(deque)
    realized_total = Decimal("0")
    realized_recent = Decimal("0")
    cutoff_ts = _now_tz() - timedelta(hours=cutoff_hours)

    for tr in sorted(trades, key=_get_created_at):
        side = _normalize_side(getattr(tr, "side", None))
        addr = getattr(tr, "pairAddress", None) or getattr(tr, "tokenAddress", None)
        qty = float(tr.qty or 0.0)
        px = float(tr.price or 0.0)
        fee = float(tr.fee or 0.0)
        if not addr or qty <= 0.0 or px <= 0.0:
            continue

        if side == "BUY":
            fee_per_unit = fee / qty if qty > 0.0 else 0.0
            lots_by_addr[addr].append([qty, px, fee_per_unit])
            log.debug("[PNL][REALIZED][BUY] addr=%s qty=%.12f px=%.12f fee_u=%.12f", addr[-6:], qty, px, fee_per_unit)
            continue

        if side == "SELL":
            sell_fee_per_unit = fee / qty if qty > 0.0 else 0.0
            remaining = qty
            is_recent = _get_created_at(tr) >= cutoff_ts
            while remaining > 1e-12 and lots_by_addr[addr]:
                lot_qty, lot_px, buy_fee_u = lots_by_addr[addr][0]
                matched = min(remaining, lot_qty)
                pnl_unit = (px - lot_px - buy_fee_u - sell_fee_per_unit)
                pnl_contrib = Decimal(matched) * _D(pnl_unit)
                realized_total += pnl_contrib
                if is_recent:
                    realized_recent += pnl_contrib

                lot_qty -= matched
                remaining -= matched
                if lot_qty <= 1e-12:
                    lots_by_addr[addr].popleft()
                else:
                    lots_by_addr[addr][0] = [lot_qty, lot_px, buy_fee_u]
                log.debug("[PNL][REALIZED][SELL] addr=%s matched=%.12f pnl=%.6f", addr[-6:], matched, float(pnl_contrib))

    q = Decimal("0.01")
    return float(realized_total.quantize(q, rounding=ROUND_HALF_UP)), float(
        realized_recent.quantize(q, rounding=ROUND_HALF_UP)
    )


def cash_from_trades(start_cash: float, trades: Iterable[Trade]) -> Tuple[float, float, float, float]:
    """
    Compute cash balance from trades using **price (USD)** recorded on the Trade rows.

    Returns:
        (cash_usd, total_buys_usd, total_sells_usd, total_fees_usd)
    """
    total_buys = _D(0)
    total_sells = _D(0)
    total_fees = _D(0)

    for tr in trades:
        side = _normalize_side(getattr(tr, "side", None))
        qty = float(tr.qty or 0.0)
        px = float(tr.price or 0.0)
        fee = _D(tr.fee or 0.0)
        if qty <= 0.0 or px <= 0.0:
            continue
        notional = _D(px * qty)
        if side == "BUY":
            total_buys += notional
        elif side == "SELL":
            total_sells += notional
        total_fees += fee

    cash = _D(start_cash) - total_buys + total_sells - total_fees
    q = Decimal("0.01")
    return (
        float(cash.quantize(q, rounding=ROUND_HALF_UP)),
        float(total_buys.quantize(q, rounding=ROUND_HALF_UP)),
        float(total_sells.quantize(q, rounding=ROUND_HALF_UP)),
        float(total_fees.quantize(q, rounding=ROUND_HALF_UP)),
    )


def holdings_and_unrealized_from_trades(trades: Iterable[Trade], address_price: Dict[str, float]) -> Tuple[float, float]:
    """
    Rebuild remaining FIFO lots **per pairAddress when available, otherwise per tokenAddress**,
    then value holdings and unrealized PnL using the provided `address_price` map.

    The `address_price` mapping must use the same addressing policy:
    - If the system recorded trades with pairAddress, provide pairAddress -> price.
    - Otherwise, provide tokenAddress -> price (legacy fallback).
    """
    lots_by_addr: Dict[str, Deque[list[float]]] = defaultdict(deque)

    for tr in sorted(trades, key=_get_created_at):
        side = _normalize_side(getattr(tr, "side", None))
        addr = getattr(tr, "pairAddress", None) or getattr(tr, "tokenAddress", None)
        qty = float(tr.qty or 0.0)
        px = float(tr.price or 0.0)
        fee = float(tr.fee or 0.0)
        if not addr or qty <= 0.0 or px <= 0.0:
            continue

        if side == "BUY":
            fee_u = fee / qty if qty > 0.0 else 0.0
            lots_by_addr[addr].append([qty, px, fee_u])
            log.debug("[PNL][UNREAL][BUY] addr=%s qty=%.12f px=%.12f fee_u=%.12f", addr[-6:], qty, px, fee_u)
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
                    lots_by_addr[addr][0] = [lot_qty, lot_px, fee_u]
            log.debug("[PNL][UNREAL][SELL] addr=%s matched=%.12f", addr[-6:], qty - remaining)

    holdings_value = _D(0)
    unrealized = _D(0)

    for addr, dq in lots_by_addr.items():
        last = float(address_price.get(addr, 0.0) or 0.0)
        last_for_value = last if last > 0.0 else 0.0
        if last_for_value <= 0.0:
            log.debug("[PNL][UNREAL][NOPRICE] addr=%s — skipping unrealized valuation.", addr[-6:])
            continue
        for lot_qty, lot_px, fee_u in dq:
            holdings_value += _D(lot_qty * last_for_value)
            unrealized += _D((last_for_value - (lot_px + fee_u)) * lot_qty)

    q = Decimal("0.01")
    return float(holdings_value.quantize(q, rounding=ROUND_HALF_UP)), float(
        unrealized.quantize(q, rounding=ROUND_HALF_UP)
    )


# --------------------------- Live pricing helper --------------------------- #

async def latest_prices_for_positions(positions: Iterable[object]) -> Dict[str, float]:
    """
    Pair-aware live pricing for a set of positions, **preserving keys**:

    - When a position exposes a non-empty 'pairAddress' and a 'chain', return a mapping
      of pairAddress -> price using the Dexscreener /pairs endpoint.
    - Positions without a pair are ignored here (pair-only policy); callers may fallback
      to entry price for display if needed.
    """
    from src.core.structures.structures import Token
    from src.integrations.dexscreener.dexscreener_client import fetch_prices_by_tokens
    from src.integrations.dexscreener.dexscreener_structures import TokenPrice

    tokens: List[Token] = []
    for p in positions:
        pair_addr = getattr(p, "pairAddress", None)
        chain = getattr(p, "chain", None)
        token_addr = getattr(p, "tokenAddress", None) or getattr(p, "address", None)
        if isinstance(pair_addr, str) and pair_addr and isinstance(chain, str) and chain and isinstance(token_addr, str) and token_addr:
            tokens.append(Token(symbol=getattr(p, "symbol", ""), chain=chain, tokenAddress=token_addr, pairAddress=pair_addr))

    result: Dict[str, float] = {}
    if not tokens:
        return result

    prices: List[TokenPrice] = await fetch_prices_by_tokens(tokens)
    for item in prices:
        if item.token.pairAddress and item.priceUsd > 0.0:
            result[item.token.pairAddress] = float(item.priceUsd)

    return result
