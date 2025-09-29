from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.persistence.db import _session
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
    trade = Trade(
        side=Side.SELL,
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
    if position is not None:
        sell_qty = min(float(qty), float(position.qty or 0.0))
        cost_basis = float(position.entry or 0.0) * sell_qty
        proceeds = float(price) * sell_qty
        realized = proceeds - cost_basis - float(fee or 0.0)
        position.qty = float(position.qty or 0.0) - sell_qty
        if position.qty <= 0:
            position.qty = 0.0
            position.is_open = False
            position.phase = phase
            position.closed_at = datetime.utcnow()
    else:
        realized = (float(price) - 0.0) * float(qty) - float(fee or 0.0)
    trade.pnl = realized
    db.commit()
    db.refresh(trade)
    return trade


def get_recent_trades(db: Session,limit: int = 100) -> List[Trade]:
    """Return the most recent trades (descending by time and id)."""
    stmt = select(Trade).order_by(Trade.created_at.desc(), Trade.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_all_trades(db: Session,) -> List[Trade]:
    """Return all trades in ascending time order (useful for FIFO computations)."""
    stmt = select(Trade).order_by(Trade.created_at.asc(), Trade.id.asc())
    return list(db.execute(stmt).scalars().all())
