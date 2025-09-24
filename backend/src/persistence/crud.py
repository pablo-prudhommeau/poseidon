from __future__ import annotations
from datetime import datetime
from typing import Iterable, Optional, List
from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session
from sqlalchemy import desc

from . import models
from .db import engine
from .models import Base, Position, Trade, PortfolioSnapshot

# ---------- bootstrap ----------
def init_db() -> None:
    Base.metadata.create_all(bind=engine)

# ---------- portfolio ----------
def snapshot_portfolio(db: Session, equity: float, cash: float, holdings: float) -> PortfolioSnapshot:
    snap = PortfolioSnapshot(equity=equity, cash=cash, holdings=holdings)
    db.add(snap)
    return snap

def get_latest_portfolio(db: Session) -> PortfolioSnapshot:
    row = db.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.id.desc()).limit(1)).scalar_one_or_none()
    return row or PortfolioSnapshot(equity=0.0, cash=0.0, holdings=0.0)

# ---------- positions ----------
def add_or_update_position(db: Session, *, symbol: str, address: str = "", qty: float, entry: float,
                           tp1: float, tp2: float, stop: float, phase: str = "OPEN") -> Position:
    q = select(Position).where(Position.symbol == symbol, Position.address == address)
    row = db.execute(q).scalar_one_or_none()
    if row is None:
        row = Position(symbol=symbol, address=address, qty=qty, entry=entry, tp1=tp1, tp2=tp2, stop=stop, phase=phase, is_open=(phase!="CLOSED"))
        db.add(row)
    else:
        row.qty = qty
        row.entry = entry
        row.tp1 = tp1
        row.tp2 = tp2
        row.stop = stop
        row.phase = phase
        row.is_open = (phase != "CLOSED")
        row.updated_at = datetime.utcnow()
    return row

def upsert_position(db: Session, **kwargs) -> Position:  # compat
    return add_or_update_position(db, **kwargs)

def close_position(db: Session, *, symbol: str, address: str = "", pnl: Optional[float] = None) -> Optional[Position]:
    q = select(Position).where(Position.symbol == symbol, Position.address == address)
    row = db.execute(q).scalar_one_or_none()
    if row:
        row.phase = "CLOSED"
        row.is_open = False
        row.closed_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
    return row

def get_open_positions(db: Session) -> list[Position]:
    q = select(Position).where(Position.phase != "CLOSED").order_by(Position.id.desc())
    return list(db.execute(q).scalars().all())

# ---------- trades ----------
def add_trade(db: Session, *, side: str, symbol: str, price: float, qty: float,
              fee: float = 0.0, pnl: Optional[float] = None, status: str = "PAPER",
              address: str = "", tx_hash: str = "", notes: str = "") -> Trade:
    t = Trade(side=side, symbol=symbol, price=price, qty=qty, fee=fee, pnl=pnl,
              status=status, address=address, tx_hash=tx_hash, notes=notes)
    db.add(t)
    return t

def get_trades(db: Session, limit: int = 100) -> list[models.Trade]:
    stmt = select(models.Trade).order_by(models.Trade.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())

# ---------- housekeeping ----------
def reset_paper(db: Session) -> None:
    db.execute(delete(Trade))
    db.execute(delete(Position))
    db.execute(delete(PortfolioSnapshot))

def get_recent_trades(db: Session, limit: int = 100) -> list[models.Trade]:
    """Retourne les derniers trades (ordre antichronologique)."""
    stmt = (
        select(models.Trade)
        .order_by(models.Trade.created_at.desc(), models.Trade.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())
