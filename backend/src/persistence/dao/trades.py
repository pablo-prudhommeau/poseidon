from __future__ import annotations

from collections import deque
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.utils import timezone_now
from src.persistence.models import Position, Trade, Phase, Status, Side


def buy(
        db: Session,
        symbol: str,
        chain: str,
        address: str,
        qty: float,
        price: float,
        stop: float,
        tp1: float,
        tp2: float,
        fee: float,
        status: Status,
) -> Trade:
    """
    Register a BUY trade and update/initialize the corresponding Position.
    Uses moving average entry for DCA.
    """
    trade = Trade(
        side=Side.BUY,
        symbol=symbol,
        chain=chain,
        price=price,
        qty=qty,
        fee=fee,
        status=status,
        address=address,
    )
    db.add(trade)
    position = db.execute(select(Position).where(Position.address == address)).scalars().first()
    if position is None:
        position = Position(
            symbol=symbol,
            chain=chain,
            address=address,
            qty=qty,
            entry=price,
            tp1=tp1,
            tp2=tp2,
            stop=stop,
            phase=Phase.OPEN
        )
        db.add(position)
    else:
        previous_qty = float(position.qty or 0.0)
        total_qty = previous_qty + float(qty)
        avg_entry = 0.0 if total_qty <= 0 else (
                ((float(position.entry or 0.0) * previous_qty) + (float(price) * float(qty))) / total_qty
        )
        position.qty = total_qty
        position.entry = avg_entry
        position.is_open = total_qty > 0
        position.tp1 = tp1
        position.tp2 = tp2
        position.stop = stop
    db.commit()
    db.refresh(trade)
    return trade


def _fifo_realized_for_sell(db: Session, address: str, sell_qty: float, sell_price: float, fee: float) -> float:
    """
    Compute realized PnL for a SELL using FIFO lots built from prior trades of the same address.
    Fees are subtracted once from the final result.
    """
    if sell_qty <= 0.0 or sell_price <= 0.0:
        return 0.0 - float(fee or 0.0)

    # 1) Build lots from PRIOR trades for this address (time order)
    prior_trades = db.execute(
        select(Trade).where(Trade.address == address).order_by(Trade.created_at.asc(), Trade.id.asc())
    ).scalars().all()

    lots: deque[list[float]] = deque()  # [qty, price]
    for tr in prior_trades:
        if tr.qty is None or tr.price is None:
            continue
        if tr.qty <= 0.0 or tr.price <= 0.0:
            continue
        if tr.side == Side.BUY:
            lots.append([float(tr.qty), float(tr.price)])
        elif tr.side == Side.SELL:
            remaining = float(tr.qty)
            while remaining > 1e-12 and lots:
                lot_qty, lot_px = lots[0]
                matched = min(remaining, lot_qty)
                lot_qty -= matched
                remaining -= matched
                if lot_qty <= 1e-12:
                    lots.popleft()
                else:
                    lots[0][0] = lot_qty

    # 2) Realize PnL for THIS sell against remaining lots
    remaining_to_sell = float(sell_qty)
    realized = 0.0

    while remaining_to_sell > 1e-12 and lots:
        lot_qty, lot_px = lots[0]
        matched = min(remaining_to_sell, lot_qty)
        realized += (float(sell_price) - float(lot_px)) * matched
        lot_qty -= matched
        remaining_to_sell -= matched
        if lot_qty <= 1e-12:
            lots.popleft()
        else:
            lots[0][0] = lot_qty

    # Defensive: if overselling (should not happen), treat the remainder as full gain at sell price
    if remaining_to_sell > 1e-12:
        realized += float(sell_price) * remaining_to_sell

    realized -= float(fee or 0.0)
    return round(realized, 8)


def sell(
        db: Session,
        symbol: str,
        chain: str,
        address: str,
        qty: float,
        price: float,
        fee: float,
        status: Status,
        phase: Phase
) -> Trade:
    """
    Register a SELL trade, compute realized PnL using FIFO lots, and update the Position.
    """
    # Compute realized BEFORE adding the new trade to avoid including it in FIFO building.
    position = db.execute(select(Position).where(Position.address == address)).scalars().first()
    if position is not None:
        sell_qty = min(float(qty), float(position.qty or 0.0))
        realized = _fifo_realized_for_sell(
            db=db,
            address=address,
            sell_qty=sell_qty,
            sell_price=float(price),
            fee=float(fee or 0.0),
        )
    else:
        sell_qty = float(qty)
        realized = float(price) * sell_qty - float(fee or 0.0)

    trade = Trade(
        side=Side.SELL,
        symbol=symbol,
        chain=chain,
        price=price,
        qty=qty,
        fee=fee,
        status=status,
        address=address,
        pnl=realized,
    )
    db.add(trade)

    if position is not None:
        position.qty = float(position.qty or 0.0) - sell_qty
        if position.qty <= 0:
            position.qty = 0.0
            position.is_open = False
            position.phase = phase
            position.closed_at = timezone_now()

    db.commit()
    db.refresh(trade)
    return trade


def get_recent_trades(db: Session, limit: int = 100) -> List[Trade]:
    """Return the most recent trades (descending by time and id)."""
    stmt = select(Trade).order_by(Trade.created_at.desc(), Trade.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_all_trades(db: Session) -> List[Trade]:
    """Return all trades in ascending time order (useful for FIFO computations)."""
    stmt = select(Trade).order_by(Trade.created_at.asc(), Trade.id.asc())
    return list(db.execute(stmt).scalars().all())
