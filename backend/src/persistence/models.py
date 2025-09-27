# src/persistence/models.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Enum, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

# Use the single declarative Base defined in db.py to avoid split metadata.
from src.persistence.db import Base

# Phases for a position's lifecycle
PositionPhase = Enum("OPEN", "PARTIAL", "CLOSED", name="position_phase")


class Position(Base):
    """Open/closed positions with entry, thresholds, and lifecycle metadata."""
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    address: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    qty: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    entry: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tp1: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tp2: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stop: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    phase: Mapped[str] = mapped_column(PositionPhase, default="OPEN", nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now(), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(default=None, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Position {self.symbol} {self.address[-6:]} qty={self.qty} phase={self.phase}>"


class Trade(Base):
    """Executed trades (paper/live), including realized PnL and bookkeeping."""
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    side: Mapped[str] = mapped_column(String(4), index=True)  # BUY/SELL
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, default=0.0)  # fixed earlier: default fee
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # realized PnL for this trade (SELL)
    status: Mapped[str] = mapped_column(String(16), default="PAPER")    # PAPER | LIVE
    address: Mapped[str] = mapped_column(String(128), default="")
    tx_hash: Mapped[str] = mapped_column(String(128), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Trade {self.side} {self.symbol} qty={self.qty} px={self.price}>"


class PortfolioSnapshot(Base):
    """Periodic snapshot of portfolio values for equity curve and telemetry."""
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equity: Mapped[float] = mapped_column(Float, default=0.0)
    cash: Mapped[float] = mapped_column(Float, default=0.0)
    holdings: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Snapshot equity={self.equity} cash={self.cash} holdings={self.holdings}>"
