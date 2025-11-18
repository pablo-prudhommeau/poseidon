from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Enum as SqlAchemyEnum, Float, Integer, String, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from src.core.utils.date_utils import timezone_now
from src.persistence.db import Base


class Phase(Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"
    STALED = "STALED"


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class Status(Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Position(Base):
    """
    Open/closed positions with entry, thresholds, and lifecycle metadata.
    """
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    tokenAddress: Mapped[str] = mapped_column(String(128), nullable=False)
    pairAddress: Mapped[str] = mapped_column(String(128), nullable=False)
    open_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    current_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry: Mapped[float] = mapped_column(Float, nullable=False)
    tp1: Mapped[float] = mapped_column(Float, nullable=False)
    tp2: Mapped[float] = mapped_column(Float, nullable=False)
    stop: Mapped[float] = mapped_column(Float, nullable=False)
    phase: Mapped[Phase] = mapped_column(SqlAchemyEnum(Phase), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(default=timezone_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=timezone_now, onupdate=timezone_now, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(default=None, nullable=True)

    def __repr__(self) -> str:
        return f"<Position {self.symbol} {self.tokenAddress[-6:]} qty={self.open_quantity} phase={self.phase}>"


class Trade(Base):
    """
    Executed trades (paper/live), including realized PnL and bookkeeping.
    """
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
    tokenAddress: Mapped[str] = mapped_column(String(128), nullable=False)
    pairAddress: Mapped[str] = mapped_column(String(128), nullable=False)
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


class Analytics(Base):
    """
    One row per evaluated candidate — later enriched by the trade outcome.
    All fields are NOT NULL; the 'raw_*' columns capture the unstructured payloads.
    """
    __tablename__ = "analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identification
    symbol: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    tokenAddress: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    pairAddress: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    # Pricing
    priceUsd: Mapped[float] = mapped_column(Float, nullable=False)
    priceNative: Mapped[float] = mapped_column(Float, nullable=False)

    # Timing
    evaluated_at: Mapped[datetime] = mapped_column(nullable=False)

    # Ranking / Scores
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    statistics_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # AI (OpenAI / Chart AI)
    ai_probability_tp1_before_sl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ai_quality_score_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Fundamentals
    token_age_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume5m_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume1h_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume6h_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume24h_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    liquidity_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pct_5m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pct_1h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pct_6h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pct_24h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tx_5m: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tx_1h: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tx_6h: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tx_24h: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Decision + sizing/budget
    decision: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    decision_reason: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    sizing_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    order_notional_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    free_cash_before_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    free_cash_after_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Outcome (filled at close)
    has_outcome: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_trade_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome_closed_at: Mapped[datetime] = mapped_column(nullable=False, default=timezone_now)
    outcome_holding_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_pnl_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_was_profit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_exit_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # RAW payloads
    raw_dexscreener: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
