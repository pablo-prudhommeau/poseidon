from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Enum as SqlAchemyEnum, Float, Integer, String, JSON, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.structures.structures import DcaStrategyStatus, DcaOrderStatus
from src.core.utils.date_utils import get_current_local_datetime
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
    opened_at: Mapped[datetime] = mapped_column(default=get_current_local_datetime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=get_current_local_datetime, onupdate=get_current_local_datetime, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(default=None, nullable=True)

    def __repr__(self) -> str:
        return f"<Position {self.symbol} {self.tokenAddress[-6:]} qty={self.open_quantity} phase={self.phase}>"


class Trade(Base):
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
    created_at: Mapped[datetime] = mapped_column(default=get_current_local_datetime, nullable=False)

    def __repr__(self) -> str:
        return f"<Trade {self.side} {self.symbol} qty={self.qty} px={self.price}>"


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    holdings: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=get_current_local_datetime, nullable=False)

    def __repr__(self) -> str:
        return f"<Snapshot equity={self.equity} cash={self.cash} holdings={self.holdings}>"


class Analytics(Base):
    __tablename__ = "analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    chain: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    tokenAddress: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    pairAddress: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    priceUsd: Mapped[float] = mapped_column(Float, nullable=False)
    priceNative: Mapped[float] = mapped_column(Float, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    statistics_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ai_probability_tp1_before_sl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ai_quality_score_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
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
    decision: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    decision_reason: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    sizing_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    order_notional_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    free_cash_before_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    free_cash_after_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    has_outcome: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_trade_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome_closed_at: Mapped[datetime] = mapped_column(nullable=False, default=get_current_local_datetime)
    outcome_holding_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_pnl_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_was_profit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_exit_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    raw_dexscreener: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class DcaStrategy(Base):
    __tablename__ = "dca_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_in_symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    asset_in_address: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_in_decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_out_symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    asset_out_address: Mapped[str] = mapped_column(String(128), nullable=False)
    binance_pair: Mapped[str] = mapped_column(String(24), nullable=False)
    total_budget: Mapped[float] = mapped_column(Float, nullable=False)
    total_executions: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_per_order: Mapped[float] = mapped_column(Float, nullable=False)
    slippage: Mapped[float] = mapped_column(Float, nullable=False)
    pru_elasticity_factor: Mapped[float] = mapped_column(Float, nullable=False)
    cycle_index: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_ath: Mapped[float] = mapped_column(Float, nullable=False)
    previous_bull_amplitude_pct: Mapped[float] = mapped_column(Float, nullable=False)
    flattening_factor: Mapped[float] = mapped_column(Float, nullable=False)
    bear_bottom_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_bull_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    aave_estimated_apy: Mapped[float] = mapped_column(Float, nullable=False)
    realized_aave_yield: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_yield_calculation_at: Mapped[datetime] = mapped_column(nullable=False)
    start_date: Mapped[datetime] = mapped_column(nullable=False)
    end_date: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[DcaStrategyStatus] = mapped_column(SqlAchemyEnum(DcaStrategyStatus), nullable=False)
    bypass_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    dry_powder: Mapped[float] = mapped_column(Float, nullable=False)
    deployed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    average_purchase_price: Mapped[float] = mapped_column(Float, nullable=False)
    backtest_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
    orders: Mapped[list["DcaOrder"]] = relationship("DcaOrder", back_populates="strategy", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<DcaStrategy {self.id} {self.chain} {self.asset_in_symbol}->{self.asset_out_symbol}>"


class DcaOrder(Base):
    __tablename__ = "dca_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("dca_strategies.id"), nullable=False)
    planned_date: Mapped[datetime] = mapped_column(nullable=False)
    planned_amount: Mapped[float] = mapped_column(Float, nullable=False)
    executed_amount_in: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_amount_out: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[DcaOrderStatus] = mapped_column(SqlAchemyEnum(DcaOrderStatus), nullable=False)
    transaction_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    execution_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    strategy: Mapped["DcaStrategy"] = relationship("DcaStrategy", back_populates="orders")
