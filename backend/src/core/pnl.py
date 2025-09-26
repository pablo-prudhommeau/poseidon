# src/core/pnl_center.py
from __future__ import annotations

from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, Tuple, Iterable, Any, Optional

# Helpers robustes d'accès attributs ORM/DTO
def _get_qty(t: Any) -> float:
    return float(getattr(t, "qty", getattr(t, "quantity", 0.0)) or 0.0)

def _get_price(t: Any) -> float:
    return float(getattr(t, "price", getattr(t, "price_usd", 0.0)) or 0.0)

def _get_created_at(t: Any) -> datetime:
    return getattr(t, "created_at", None) or datetime.min

def _get_addr(p: Any) -> str:
    return (getattr(p, "address", "") or "").lower()

def _get_entry(p: Any) -> float:
    return float(getattr(p, "entry", 0.0) or 0.0)

def _get_qty_pos(p: Any) -> float:
    return float(getattr(p, "qty", 0.0) or 0.0)


# --------- Calcul PnL réalisé (FIFO) ---------
def fifo_realized_pnl(trades: Iterable[Any], *, cutoff_hours: int = 24) -> Tuple[float, float]:
    """
    Retourne (realized_total, realized_last_{cutoff_hours}h)
    FIFO par adresse, uniquement sur SELL.
    """
    lots: Dict[str, deque] = defaultdict(deque)
    total = 0.0
    lastX = 0.0
    cutoff = datetime.utcnow() - timedelta(hours=cutoff_hours)

    trades_sorted = sorted(trades, key=_get_created_at)
    for t in trades_sorted:
        side = (getattr(t, "side", "") or "").upper()
        addr = _get_addr(t)
        qty = _get_qty(t)
        px = _get_price(t)
        if qty <= 0 or px <= 0:
            continue

        if side == "BUY":
            lots[addr].append([qty, px])
            continue

        if side == "SELL":
            remain = qty
            pnl_sell = 0.0
            while remain > 1e-12 and lots[addr]:
                lot_qty, lot_px = lots[addr][0]
                take = min(remain, lot_qty)
                pnl_sell += (px - lot_px) * take
                lot_qty -= take
                remain -= take
                if lot_qty <= 1e-12:
                    lots[addr].popleft()
                else:
                    lots[addr][0][0] = lot_qty
            total += pnl_sell
            if _get_created_at(t) >= cutoff:
                lastX += pnl_sell

    return round(total, 2), round(lastX, 2)


# --------- Cash depuis le journal de trades ---------
def cash_from_trades(start_cash: float, trades: Iterable[Any]) -> Tuple[float, float, float, float]:
    """
    Retourne (cash, total_buys, total_sells, total_fees)
    """
    total_buys = 0.0
    total_sells = 0.0
    total_fees = 0.0

    for t in trades:
        side = (getattr(t, "side", "") or "").upper()
        qty = _get_qty(t)
        px = _get_price(t)
        fee = float(getattr(t, "fee", 0.0) or 0.0)
        if qty <= 0 or px <= 0:
            continue
        if side == "BUY":
            total_buys += px * qty
        elif side == "SELL":
            total_sells += px * qty
        total_fees += fee

    cash = float(start_cash) - total_buys + total_sells - total_fees
    return round(cash, 2), round(total_buys, 2), round(total_sells, 2), round(total_fees, 2)


# --------- Holdings + Unrealized via prix live ---------
def holdings_and_unrealized(positions: Iterable[Any], address_price: Dict[str, float]) -> Tuple[float, float]:
    holdings = 0.0
    unrealized = 0.0
    for p in positions:
        addr = _get_addr(p)
        last = float(address_price.get(addr, 0.0) or 0.0)
        if last <= 0.0:
            last = _get_entry(p)
        qty = _get_qty_pos(p)
        entry = _get_entry(p)
        holdings += last * qty
        unrealized += (last - entry) * qty
    return round(holdings, 2), round(unrealized, 2)


# --------- Prix live pour une liste de positions ---------
async def latest_prices_for_positions(positions: Iterable[Any], *, chain_id: Optional[str] = None) -> Dict[str, float]:
    """
    Fetch multi-chain DexScreener prices by addresses found in positions.
    """
    addrs = [ _get_addr(p) for p in positions if _get_addr(p) ]
    uniq = list(dict.fromkeys(addrs))
    if not uniq:
        return {}
    # import tardif pour éviter les cycles
    from src.integrations.dexscreener_client import fetch_prices_by_addresses
    return await fetch_prices_by_addresses(uniq, chain_id=chain_id)
