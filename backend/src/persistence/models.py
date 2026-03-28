from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Enum as SQLAlchemyEnum, Float, Integer, String, JSON, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.structures.structures import DcaStrategyStatus, DcaOrderStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.persistence.db import DatabaseBaseModel


class PositionPhase(Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"
    STALED = "STALED"


class TradeSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionStatus(Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Position(DatabaseBaseModel):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_symbol: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    blockchain_network: Mapped[str] = mapped_column(String(32), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    pair_address: Mapped[str] = mapped_column(String(128), nullable=False)
    open_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    current_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit_tier_1_price: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit_tier_2_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss_price: Mapped[float] = mapped_column(Float, nullable=False)
    position_phase: Mapped[PositionPhase] = mapped_column(SQLAlchemyEnum(PositionPhase), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(default=get_current_local_datetime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=get_current_local_datetime, onupdate=get_current_local_datetime, nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(default=None, nullable=True)

    def __repr__(self) -> str:
        return f"<Position token_symbol={self.token_symbol} token_address={self.token_address[-6:]} open_quantity={self.open_quantity} position_phase={self.position_phase}>"


class Trade(DatabaseBaseModel):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_side: Mapped[TradeSide] = mapped_column(SQLAlchemyEnum(TradeSide), index=True)
    token_symbol: Mapped[str] = mapped_column(String(24), index=True)
    blockchain_network: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_price: Mapped[float] = mapped_column(Float, nullable=False)
    execution_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_fee: Mapped[float] = mapped_column(Float, nullable=False)
    realized_profit_and_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    execution_status: Mapped[ExecutionStatus] = mapped_column(SQLAlchemyEnum(ExecutionStatus), nullable=False)
    token_address: Mapped[str] = mapped_column(String(128), nullable=False)
    pair_address: Mapped[str] = mapped_column(String(128), nullable=False)
    transaction_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=get_current_local_datetime, nullable=False)

    def __repr__(self) -> str:
        return f"<Trade trade_side={self.trade_side} token_symbol={self.token_symbol} execution_quantity={self.execution_quantity} execution_price={self.execution_price}>"


class PortfolioSnapshot(DatabaseBaseModel):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    total_equity_value: Mapped[float] = mapped_column(Float, nullable=False)
    available_cash_balance: Mapped[float] = mapped_column(Float, nullable=False)
    active_holdings_value: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=get_current_local_datetime, nullable=False)

    def __repr__(self) -> str:
        return f"<PortfolioSnapshot total_equity_value={self.total_equity_value} available_cash_balance={self.available_cash_balance} active_holdings_value={self.active_holdings_value}>"


class Analytics(DatabaseBaseModel):
    __tablename__ = "analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_symbol: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    blockchain_network: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    token_address: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    pair_address: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    price_native: Mapped[float] = mapped_column(Float, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(nullable=False)
    candidate_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    statistics_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ai_probability_take_profit_before_stop_loss: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ai_quality_score_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    token_age_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume_m5_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume_h1_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume_h6_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    volume_h24_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    liquidity_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_change_percentage_m5: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_change_percentage_h1: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_change_percentage_h6: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_change_percentage_h24: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transaction_count_m5: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transaction_count_hour_1: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transaction_count_h6: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transaction_count_h24: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_decision: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    execution_decision_reason: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    sizing_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    order_notional_value_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    free_cash_before_execution_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    free_cash_after_execution_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    has_trade_outcome: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_trade_identifier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome_closed_at: Mapped[datetime] = mapped_column(nullable=False, default=get_current_local_datetime)
    outcome_holding_duration_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_realized_profit_and_loss_percentage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_realized_profit_and_loss_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outcome_was_profitable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome_exit_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    raw_dexscreener_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    raw_configuration_settings: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class DcaStrategy(DatabaseBaseModel):
    __tablename__ = "dca_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    blockchain_network: Mapped[str] = mapped_column(String(32), nullable=False)
    source_asset_symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    source_asset_address: Mapped[str] = mapped_column(String(128), nullable=False)
    source_asset_decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    target_asset_symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    target_asset_address: Mapped[str] = mapped_column(String(128), nullable=False)
    binance_trading_pair: Mapped[str] = mapped_column(String(24), nullable=False)
    total_allocated_budget: Mapped[float] = mapped_column(Float, nullable=False)
    total_planned_executions: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_per_execution_order: Mapped[float] = mapped_column(Float, nullable=False)
    slippage_tolerance: Mapped[float] = mapped_column(Float, nullable=False)
    average_unit_price_elasticity_factor: Mapped[float] = mapped_column(Float, nullable=False)
    current_cycle_index: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_all_time_high_price: Mapped[float] = mapped_column(Float, nullable=False)
    previous_bull_market_amplitude_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    curve_flattening_factor: Mapped[float] = mapped_column(Float, nullable=False)
    bear_market_bottom_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_bull_market_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    aave_estimated_annual_percentage_yield: Mapped[float] = mapped_column(Float, nullable=False)
    realized_aave_yield_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_yield_calculation_timestamp: Mapped[datetime] = mapped_column(nullable=False)
    strategy_start_date: Mapped[datetime] = mapped_column(nullable=False)
    strategy_end_date: Mapped[datetime] = mapped_column(nullable=False)
    strategy_status: Mapped[DcaStrategyStatus] = mapped_column(SQLAlchemyEnum(DcaStrategyStatus), nullable=False)
    bypass_security_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    available_dry_powder: Mapped[float] = mapped_column(Float, nullable=False)
    total_deployed_amount: Mapped[float] = mapped_column(Float, nullable=False)
    average_purchase_price: Mapped[float] = mapped_column(Float, nullable=False)
    historical_backtest_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
    execution_orders: Mapped[list[DcaOrder]] = relationship("DcaOrder", back_populates="parent_strategy", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<DcaStrategy identifier={self.id} blockchain_network={self.blockchain_network} routing={self.source_asset_symbol}->{self.target_asset_symbol}>"


class DcaOrder(DatabaseBaseModel):
    __tablename__ = "dca_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("dca_strategies.id"), nullable=False)
    planned_execution_date: Mapped[datetime] = mapped_column(nullable=False)
    planned_source_asset_amount: Mapped[float] = mapped_column(Float, nullable=False)
    executed_source_asset_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_target_asset_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    order_status: Mapped[DcaOrderStatus] = mapped_column(SQLAlchemyEnum(DcaOrderStatus), nullable=False)
    transaction_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    actual_execution_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    allocation_decision_description: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    parent_strategy: Mapped[DcaStrategy] = relationship("DcaStrategy", back_populates="execution_orders")
