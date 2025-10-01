from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Enum as SqlAchemyEnum, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.utils import timezone_now
from src.persistence.db import Base


class Phase(Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class Status(Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Position(Base):
    """Open/closed positions with entry, thresholds, and lifecycle metadata."""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    entry: Mapped[float] = mapped_column(Float, nullable=False)
    tp1: Mapped[float] = mapped_column(Float, nullable=False)
    tp2: Mapped[float] = mapped_column(Float, nullable=False)
    stop: Mapped[float] = mapped_column(Float, nullable=False)
    phase: Mapped[Phase] = mapped_column(SqlAchemyEnum(Phase), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(default=timezone_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=timezone_now, onupdate=timezone_now, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(default=None, nullable=True)

    def __repr__(self) -> str:
        return f"<Position {self.symbol} {self.address[-6:]} qty={self.qty} phase={self.phase}>"


class Trade(Base):
    """Executed trades (paper/live), including realized PnL and bookkeeping."""
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    side: Mapped[Side] = mapped_column(SqlAchemyEnum(Side), index=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Status] = mapped_column(SqlAchemyEnum(Status), nullable=False)
    address: Mapped[str] = mapped_column(String(128))
    tx_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=timezone_now, nullable=False)

    def __repr__(self) -> str:
        return f"<Trade {self.side} {self.symbol} qty={self.qty} px={self.price}>"


class PortfolioSnapshot(Base):
    """Periodic snapshot of portfolio values for equity curve and telemetry."""
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    holdings: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=timezone_now, nullable=False)

    def __repr__(self) -> str:
        return f"<Snapshot equity={self.equity} cash={self.cash} holdings={self.holdings}>"
