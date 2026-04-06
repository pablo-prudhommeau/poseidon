from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class HealthComponentPayload(BaseModel):
    ok: bool


class HealthComponentsPayload(BaseModel):
    database: HealthComponentPayload


class HealthPayload(BaseModel):
    status: str
    timestamp: str
    components: HealthComponentsPayload


class PaperResetPayload(BaseModel):
    ok: bool


class CreateDcaPayload(BaseModel):
    blockchain_network: str
    source_asset_symbol: str
    source_asset_address: str
    source_asset_decimals: int
    target_asset_symbol: str
    target_asset_address: str
    binance_trading_pair: str
    total_allocated_budget: float
    total_planned_executions: int
    strategy_start_date: datetime
    strategy_end_date: datetime
    bypass_security_approval: bool = False
    slippage_tolerance: float
    average_unit_price_elasticity_factor: float
    bear_market_start_date: datetime
    bear_market_end_date: datetime


class CreateDcaStrategyResponse(BaseModel):
    message: str
    strategy_id: int
    orders_count: int


class DcaOrderPayload(BaseModel):
    id: int
    strategy_id: int
    planned_execution_date: str
    planned_source_asset_amount: float
    executed_source_asset_amount: Optional[float] = None
    executed_target_asset_amount: Optional[float] = None
    order_status: str
    transaction_hash: Optional[str] = None
    actual_execution_price: Optional[float] = None
    executed_at: Optional[str] = None
    allocation_decision_description: Optional[str] = None


class DcaBacktestSeriesPointPayload(BaseModel):
    timestamp_iso: str
    execution_price: float
    average_purchase_price: float
    cumulative_spent: float
    dry_powder_remaining: float


class DcaBacktestMetadataPayload(BaseModel):
    source_asset_symbol: str
    total_allocated_budget: float
    total_planned_executions: int
    final_dumb_average_unit_price: float
    final_smart_average_unit_price: float
    total_overheat_retentions: int


class DcaBacktestPayloadModel(BaseModel):
    metadata: DcaBacktestMetadataPayload
    dumb_dca_series: List[DcaBacktestSeriesPointPayload]
    smart_dca_series: List[DcaBacktestSeriesPointPayload]


class DcaStrategyPayload(BaseModel):
    id: int
    blockchain_network: str
    source_asset_symbol: str
    source_asset_address: str
    source_asset_decimals: int
    source_asset_currency_symbol: str
    target_asset_symbol: str
    target_asset_address: str
    target_asset_currency_symbol: str
    binance_trading_pair: str
    total_allocated_budget: float
    total_planned_executions: int
    amount_per_execution_order: float
    slippage_tolerance: float
    average_unit_price_elasticity_factor: float
    current_cycle_index: int
    previous_all_time_high_price: float
    previous_bull_market_amplitude_percentage: float
    curve_flattening_factor: float
    bear_market_bottom_multiplier: float
    minimum_bull_market_multiplier: float
    aave_estimated_annual_percentage_yield: float
    realized_aave_yield_amount: float
    last_yield_calculation_timestamp: str
    strategy_start_date: str
    strategy_end_date: str
    strategy_status: str
    bypass_security_approval: bool
    available_dry_powder: float
    total_deployed_amount: float
    average_purchase_price: float
    historical_backtest_payload: DcaBacktestPayloadModel
    created_at: str
    updated_at: str
    execution_orders: List[DcaOrderPayload] = []
    live_aave_apy: float
    live_market_price: float


class DcaStrategiesResponse(BaseModel):
    strategies: List[DcaStrategyPayload]


class DcaOrdersResponse(BaseModel):
    orders: List[DcaOrderPayload]


class TradePayload(BaseModel):
    id: int
    trade_side: str
    token_symbol: str
    blockchain_network: str
    execution_price: float
    execution_quantity: float
    transaction_fee: float
    execution_status: str
    token_address: str
    pair_address: str
    created_at: str
    realized_profit_and_loss: Optional[float] = None
    transaction_hash: Optional[str] = None


class PositionPayload(BaseModel):
    id: int
    token_symbol: str
    token_address: str
    pair_address: str
    open_quantity: float
    entry_price: float
    take_profit_tier_1_price: float
    take_profit_tier_2_price: float
    stop_loss_price: float
    position_phase: str
    blockchain_network: str
    opened_at: str
    updated_at: str
    closed_at: Optional[str] = None
    last_price: float


class EquityCurvePointPayload(BaseModel):
    timestamp_milliseconds: int
    total_equity_value: float


class PortfolioPayload(BaseModel):
    total_equity_value: float
    available_cash_balance: float
    active_holdings_value: float
    created_at: str
    equity_curve: List[EquityCurvePointPayload]
    unrealized_profit_and_loss: float
    realized_profit_and_loss_24h: float
    realized_profit_and_loss_total: float


class AnalyticsScoresPayload(BaseModel):
    quality_score: float
    statistics_score: float
    entry_score: float
    final_score: float


class AnalyticsAiPayload(BaseModel):
    ai_probability_take_profit_before_stop_loss: float
    ai_quality_score_delta: float


class AnalyticsDecisionPayload(BaseModel):
    execution_decision: str
    execution_decision_reason: str
    sizing_multiplier: float
    order_notional_value_usd: float
    free_cash_before_execution_usd: float
    free_cash_after_execution_usd: float


class EvaluationOutcomePayload(BaseModel):
    id: int
    trade_id: Optional[int]
    exit_reason: str
    realized_profit_and_loss_percentage: float
    realized_profit_and_loss_usd: float
    holding_duration_minutes: float
    is_profitable: bool
    occurred_at: str


class AnalyticsFundamentalsPayload(BaseModel):
    token_age_hours: float
    volume_m5_usd: float
    volume_h1_usd: float
    volume_h6_usd: float
    volume_h24_usd: float
    liquidity_usd: float
    price_change_percentage_m5: float
    price_change_percentage_h1: float
    price_change_percentage_h6: float
    price_change_percentage_h24: float
    transaction_count_m5: int
    transaction_count_h1: int
    transaction_count_h6: int
    transaction_count_h24: int


class EvaluationPayload(BaseModel):
    id: int
    token_symbol: str
    blockchain_network: str
    token_address: str
    pair_address: str
    evaluated_at: str
    candidate_rank: int
    scores: AnalyticsScoresPayload
    ai: AnalyticsAiPayload
    fundamentals: AnalyticsFundamentalsPayload
    decision: AnalyticsDecisionPayload
    outcomes: List[EvaluationOutcomePayload]
    raw_dexscreener_payload: dict[str, Any]
    raw_configuration_settings: dict[str, Any]


class AnalyticsResponse(BaseModel):
    evaluations: List[EvaluationPayload]


class PositionsResponse(BaseModel):
    positions: List[PositionPayload]


class WebsocketStatusPayload(BaseModel):
    paper_mode: bool
    interval_seconds: int


class WebsocketInitializationPayload(BaseModel):
    status: WebsocketStatusPayload


class WebsocketEventPayload(BaseModel):
    type: str
    payload: dict[str, Any]
