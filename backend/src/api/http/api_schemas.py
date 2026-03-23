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
    chain: str
    asset_in_symbol: str
    asset_in_address: str
    asset_in_decimals: int
    asset_out_symbol: str
    asset_out_address: str
    binance_pair: str
    total_budget: float
    total_executions: int
    start_date: datetime
    end_date: datetime
    bypass_approval: bool
    slippage: float
    pru_elasticity_factor: float
    bear_market_start_date: datetime
    bear_market_end_date: datetime


class CreateDcaStrategyResponse(BaseModel):
    message: str
    strategy_id: int
    orders_count: int


class DcaOrderPayload(BaseModel):
    id: int
    strategy_id: int
    planned_date: str
    planned_amount: float
    executed_amount_in: Optional[float] = None
    executed_amount_out: Optional[float] = None
    status: str
    transaction_hash: Optional[str] = None
    execution_price: Optional[float] = None
    executed_at: Optional[str] = None


class DcaBacktestSeriesPointPayload(BaseModel):
    timestamp_iso: str
    execution_price: float
    average_purchase_price: float
    cumulative_spent: float
    dry_powder_remaining: float


class DcaBacktestMetadataPayload(BaseModel):
    symbol: str
    total_budget: float
    executions: int
    final_dumb_average_unit_price: float
    final_smart_average_unit_price: float
    total_overheat_retentions: int


class DcaBacktestPayloadModel(BaseModel):
    metadata: DcaBacktestMetadataPayload
    dumb_dca_series: List[DcaBacktestSeriesPointPayload]
    smart_dca_series: List[DcaBacktestSeriesPointPayload]


class DcaStrategyPayload(BaseModel):
    id: int
    chain: str
    asset_in_symbol: str
    asset_in_address: str
    asset_in_decimals: int
    asset_in_currency_symbol: str
    asset_out_symbol: str
    asset_out_address: str
    asset_out_currency_symbol: str
    binance_pair: str
    total_budget: float
    total_executions: int
    amount_per_order: float
    slippage: float
    pru_elasticity_factor: float
    cycle_index: int
    previous_ath: float
    previous_bull_amplitude_pct: float
    flattening_factor: float
    bear_bottom_multiplier: float
    minimum_bull_multiplier: float
    aave_estimated_apy: float
    realized_aave_yield: float
    last_yield_calculation_at: str
    start_date: str
    end_date: str
    status: str
    bypass_approval: bool
    dry_powder: float
    deployed_amount: float
    average_purchase_price: float
    backtest_payload: DcaBacktestPayloadModel
    created_at: str
    updated_at: str
    orders: List[DcaOrderPayload] = []
    live_aave_apy: float
    live_market_price: float


class DcaStrategiesResponse(BaseModel):
    strategies: List[DcaStrategyPayload]


class DcaOrdersResponse(BaseModel):
    orders: List[DcaOrderPayload]


class TradePayload(BaseModel):
    id: int
    side: str
    symbol: str
    chain: str
    price: float
    qty: float
    fee: float
    status: str
    tokenAddress: str
    pairAddress: str
    created_at: str
    pnl: Optional[float] = None
    tx_hash: Optional[str] = None


class PositionPayload(BaseModel):
    id: int
    symbol: str
    tokenAddress: str
    pairAddress: str
    qty: float
    entry: float
    tp1: float
    tp2: float
    stop: float
    phase: str
    chain: str
    opened_at: str
    updated_at: str
    closed_at: str
    last_price: float


class EquityCurvePointPayload(BaseModel):
    timestamp: int
    equity: float


class PortfolioPayload(BaseModel):
    equity: float
    cash: float
    holdings: float
    updated_at: str
    equity_curve: List[EquityCurvePointPayload]
    unrealized_pnl: float
    realized_pnl_24h: float
    realized_pnl_total: float


class AnalyticsScoresPayload(BaseModel):
    quality: float
    statistics: float
    entry: float
    final: float


class AnalyticsAiPayload(BaseModel):
    probabilityTp1BeforeSl: float
    qualityScoreDelta: float


class AnalyticsDecisionPayload(BaseModel):
    action: str
    reason: str
    sizingMultiplier: float
    orderNotionalUsd: float
    freeCashBeforeUsd: float
    freeCashAfterUsd: float


class AnalyticsOutcomePayload(BaseModel):
    hasOutcome: bool
    tradeId: int
    closedAt: str
    holdingMinutes: float
    pnlPct: float
    pnlUsd: float
    wasProfit: bool
    exitReason: str


class AnalyticsFundamentalsPayload(BaseModel):
    tokenAgeHours: float
    volume5mUsd: float
    volume1hUsd: float
    volume6hUsd: float
    volume24hUsd: float
    liquidityUsd: float
    pct5m: float
    pct1h: float
    pct6h: float
    pct24h: float
    tx5m: int
    tx1h: int
    tx6h: int
    tx24h: int


class AnalyticsPayload(BaseModel):
    id: int
    symbol: str
    chain: str
    tokenAddress: str
    pairAddress: str
    evaluatedAt: str
    rank: int
    scores: AnalyticsScoresPayload
    ai: AnalyticsAiPayload
    fundamentals: AnalyticsFundamentalsPayload
    decision: AnalyticsDecisionPayload
    outcome: AnalyticsOutcomePayload
    rawScreener: Any
    rawSettings: Any


class AnalyticsResponse(BaseModel):
    analytics: List[AnalyticsPayload]


class PositionsResponse(BaseModel):
    positions: List[PositionPayload]


class WsStatusPayload(BaseModel):
    paperMode: bool
    interval: int


class WsInitPayload(BaseModel):
    status: WsStatusPayload
    portfolio: PortfolioPayload
    positions: List[PositionPayload]
    trades: List[TradePayload]
    analytics: List[AnalyticsPayload]
    dca_strategies: List[DcaStrategyPayload]


class WsEventPayload(BaseModel):
    type: str
    payload: Any
