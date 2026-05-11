from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from pydantic import Field

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.shadowing.trading_shadowing_structures import ShadowIntelligenceSnapshotSummaryPayload


class SystemHealthComponentPayload(BaseModel):
    ok: bool


class SystemHealthComponentsPayload(BaseModel):
    database: SystemHealthComponentPayload


class SystemHealthPayload(BaseModel):
    status: str
    timestamp: str
    components: SystemHealthComponentsPayload


class WebsocketStatusPayload(BaseModel):
    paper_mode: bool
    interval_seconds: int


class WebsocketInitializationPayload(BaseModel):
    status: WebsocketStatusPayload


class WebsocketEventPayload(BaseModel):
    type: str
    payload: dict[str, object]


class TradingPaperResetPayload(BaseModel):
    ok: bool


class DcaStrategyCreatePayload(BaseModel):
    blockchain_network: BlockchainNetwork
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
    current_cycle_index: int
    previous_all_time_high_price: float
    previous_bull_market_amplitude_percentage: float
    curve_flattening_factor: float
    bear_market_bottom_multiplier: float
    minimum_bull_market_multiplier: float
    aave_estimated_annual_percentage_yield: float


class DcaStrategyCreateResponse(BaseModel):
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


class DcaBacktestPayload(BaseModel):
    metadata: DcaBacktestMetadataPayload
    dumb_dca_series: List[DcaBacktestSeriesPointPayload]
    smart_dca_series: List[DcaBacktestSeriesPointPayload]


class DcaStrategyPayload(BaseModel):
    id: int
    blockchain_network: BlockchainNetwork
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
    historical_backtest_payload: DcaBacktestPayload
    created_at: str
    updated_at: str
    execution_orders: List[DcaOrderPayload] = []
    live_aave_apy: float
    live_market_price: float


class DcaStrategiesResponse(BaseModel):
    strategies: List[DcaStrategyPayload]


class DcaOrdersResponse(BaseModel):
    orders: List[DcaOrderPayload]


class TradingTradePayload(BaseModel):
    id: int
    evaluation_id: int
    trade_side: str
    token_symbol: str
    blockchain_network: BlockchainNetwork
    execution_price: float
    execution_quantity: float
    transaction_fee: float
    execution_status: str
    token_address: str
    pair_address: str
    created_at: str
    dex_id: str
    realized_profit_and_loss: Optional[float] = None
    transaction_hash: Optional[str] = None


class TradingPositionPayload(BaseModel):
    id: int
    evaluation_id: int
    token_symbol: str
    token_address: str
    pair_address: str
    open_quantity: float
    entry_price: float
    take_profit_tier_1_price: float
    take_profit_tier_2_price: float
    stop_loss_price: float
    position_phase: str
    blockchain_network: BlockchainNetwork
    dex_id: str
    opened_at: str
    updated_at: str
    closed_at: Optional[str] = None
    last_price: Optional[float] = None


class TradingPositionPricePayload(BaseModel):
    position_id: int
    pair_address: str
    last_price: Optional[float] = None
    delta_percent: Optional[float] = None


class TradingEquityCurvePointPayload(BaseModel):
    timestamp_milliseconds: int
    total_equity_value: float


class BlockchainCashBalancePayload(BaseModel):
    blockchain_network: BlockchainNetwork
    stablecoin_symbol: str
    stablecoin_address: str
    stablecoin_currency_symbol: str
    balance_raw: float
    native_token_symbol: str
    native_token_balance_raw: float
    native_token_balance_usd: float = 0.0


class TradingLiquidityPayload(BaseModel):
    mode: str
    available_cash_balance: float
    stablecoin_currency_symbol: str
    maximum_chain_count: int
    blockchain_balances: List[BlockchainCashBalancePayload] = Field(default_factory=list)
    updated_at: str


class TradingShadowMetaPayload(BaseModel):
    is_enabled: bool
    is_activated: bool
    phase: str
    total_outcomes_analyzed: int
    resolved_outcome_count: int
    elapsed_hours: float
    win_rate_percentage: float
    expected_value_usd: float
    capital_velocity: float
    global_profit_factor: float
    empirical_profit_factor: float
    empirical_profit_factor_threshold: float
    empirical_profit_factor_window_verdict_count: int
    chronicle_profit_factor: float
    chronicle_profit_factor_threshold: float
    chronicle_profit_factor_lookback_days: float
    chronicle_profit_factor_bucket_width_seconds: int
    chronicle_profit_factor_moving_average_period: int
    sparse_expected_value_usd: float
    sparse_expected_value_usd_threshold: float
    sparse_expected_value_lookback_days: float
    sparse_expected_value_bucket_width_seconds: int
    sparse_expected_value_moving_average_period: int


class TradingPortfolioPayload(BaseModel):
    total_equity_value: float
    available_cash_balance: float
    active_holdings_value: float
    created_at: str
    equity_curve: List[TradingEquityCurvePointPayload]
    unrealized_profit_and_loss: float
    realized_profit_and_loss_24h: float
    realized_profit_and_loss_total: float
    shadow_intelligence_status: ShadowIntelligenceStatusPayload
    blockchain_balances: List[BlockchainCashBalancePayload] = Field(default_factory=list)


class TradingEvaluationScoresPayload(BaseModel):
    quality_score: float
    ai_adjusted_quality_score: float


class TradingEvaluationAiPayload(BaseModel):
    ai_probability_take_profit_before_stop_loss: float
    ai_quality_score_delta: float


class TradingEvaluationDecisionPayload(BaseModel):
    execution_decision: str
    sizing_multiplier: float
    order_notional_value_usd: float
    free_cash_before_execution_usd: float
    free_cash_after_execution_usd: float


class TradingEvaluationShadowIntelligenceSnapshotMetricPayload(BaseModel):
    metric_key: str
    candidate_value: Optional[float] = None
    bucket_index: int
    bucket_win_rate: float
    bucket_average_pnl: float
    bucket_average_holding_time: float = 0.0
    bucket_capital_velocity: float = 0.0
    bucket_outlier_hit_rate: float = 0.0
    bucket_sample_count: int = 0
    is_toxic: bool
    is_golden: bool
    normalized_influence: float


class TradingEvaluationShadowIntelligenceSnapshotPayload(BaseModel):
    summary: ShadowIntelligenceSnapshotSummaryPayload
    evaluated_metrics: List[TradingEvaluationShadowIntelligenceSnapshotMetricPayload] = Field(default_factory=list)


class TradingEvaluationShadowDiagnosticsPayload(BaseModel):
    intelligence_snapshot: TradingEvaluationShadowIntelligenceSnapshotPayload


class TradingEvaluationShadowSimulationPayload(BaseModel):
    id: int
    take_profit_tier_1_price: float
    take_profit_tier_2_price: float
    stop_loss_price: float
    take_profit_tier_1_hit_at: Optional[str] = None
    take_profit_tier_2_hit_at: Optional[str] = None
    stop_loss_hit_at: Optional[str] = None
    exit_reason: Optional[str] = None
    realized_pnl_percentage: Optional[float] = None
    realized_pnl_usd: Optional[float] = None
    holding_duration_minutes: Optional[float] = None
    is_profitable: Optional[bool] = None
    resolved_at: Optional[str] = None


class ShadowIntelligenceStatusPayload(BaseModel):
    is_enabled: bool
    phase: str
    resolved_outcome_count: int
    required_outcome_count: int
    elapsed_hours: float
    required_hours: float
    outcome_progress_percentage: float
    hours_progress_percentage: float


class TradingEvaluationFundamentalsPayload(BaseModel):
    token_age_hours: Optional[float] = None
    volume_m5_usd: Optional[float] = None
    volume_h1_usd: Optional[float] = None
    volume_h6_usd: Optional[float] = None
    volume_h24_usd: Optional[float] = None
    liquidity_usd: Optional[float] = None
    price_change_percentage_m5: Optional[float] = None
    price_change_percentage_h1: Optional[float] = None
    price_change_percentage_h6: Optional[float] = None
    price_change_percentage_h24: Optional[float] = None
    transaction_count_m5: Optional[int] = None
    transaction_count_h1: Optional[int] = None
    transaction_count_h6: Optional[int] = None
    transaction_count_h24: Optional[int] = None
    buy_to_sell_ratio: Optional[float] = None
    market_cap_usd: Optional[float] = None
    fully_diluted_valuation_usd: Optional[float] = None
    dexscreener_boost: Optional[float] = None


class TradingEvaluationPayload(BaseModel):
    id: int
    token_symbol: str
    blockchain_network: BlockchainNetwork
    token_address: str
    pair_address: str
    evaluated_at: str
    candidate_rank: int
    scores: TradingEvaluationScoresPayload
    ai: TradingEvaluationAiPayload
    fundamentals: TradingEvaluationFundamentalsPayload
    decision: TradingEvaluationDecisionPayload
    shadow_diagnostics: TradingEvaluationShadowDiagnosticsPayload
    raw_dexscreener_payload: dict[str, object]
    raw_configuration_settings: dict[str, object]


class TradingPositionsResponse(BaseModel):
    positions: List[TradingPositionPayload]


class AnalyticsHeatmapCellPayload(BaseModel):
    range_label: str
    range_min: float
    range_max: float
    average_pnl: float
    average_holding_time_minutes: float
    capital_velocity: float
    quartile_1_pnl: float
    quartile_3_pnl: float
    sample_count: int
    win_count: int
    win_rate_percentage: float
    outlier_hit_rate_percentage: float
    is_optimal: bool
    is_golden: bool
    is_toxic: bool


class AnalyticsHeatmapSeriesPayload(BaseModel):
    metric_key: str
    metric_label: str
    cells: List[AnalyticsHeatmapCellPayload]


class AnalyticsTimelinePointPayload(BaseModel):
    date_iso: str
    cumulative_pnl_usd: float
    cumulative_pnl_percentage: float
    rolling_win_rate: float
    trade_count: int


class AnalyticsScatterPointPayload(BaseModel):
    metric_value: float
    pnl_percentage: float
    pnl_usd: float
    token_symbol: str
    exit_reason: str


class AnalyticsScatterSeriesPayload(BaseModel):
    metric_key: str
    metric_label: str
    points: List[AnalyticsScatterPointPayload]


class AnalyticsKpiPayload(BaseModel):
    total_evaluations: int
    total_outcomes: int
    win_count: int
    loss_count: int
    win_rate_percentage: float
    total_pnl_usd: float
    average_pnl_percentage: float
    average_holding_duration_minutes: float
    best_trade_pnl_percentage: float
    worst_trade_pnl_percentage: float
    profit_factor: float
    expected_value_usd: float
    capital_velocity: float


class AnalyticsResponse(BaseModel):
    kpis: AnalyticsKpiPayload
    pnl_drivers_series: List[AnalyticsHeatmapSeriesPayload]
    timeline: List[AnalyticsTimelinePointPayload]
    scatter_series: List[AnalyticsScatterSeriesPayload]


class ShadowVerdictChronicleMetricPointPayload(BaseModel):
    timestamp_milliseconds: int
    average_pnl_percentage: float
    average_win_rate_percentage: float
    expected_value_per_trade_usd: float
    capital_velocity_per_hour: float
    profit_factor: float


class ShadowVerdictChronicleVolumePointPayload(BaseModel):
    timestamp_milliseconds: int
    verdict_count: int


class ShadowVerdictChronicleVerdictPointPayload(BaseModel):
    verdict_id: int
    timestamp_milliseconds: int
    pnl_percentage: float
    pnl_usd: float
    exit_reason: str
    order_notional_usd: float
    point_size: float
    is_profitable: bool


class ShadowVerdictChronicleBucketPayload(BaseModel):
    bucket_label: str
    granularity_seconds: int
    from_iso: str
    to_iso: str
    metrics: List[ShadowVerdictChronicleMetricPointPayload] = Field(default_factory=list)
    volumes: List[ShadowVerdictChronicleVolumePointPayload] = Field(default_factory=list)
    verdict_cloud: List[ShadowVerdictChronicleVerdictPointPayload] = Field(default_factory=list)


class ShadowVerdictChroniclePayload(BaseModel):
    generated_at_iso: str
    as_of_iso: str
    from_iso: str
    to_iso: str
    total_verdicts_considered: int
    source: str
    series_end_lag_seconds: int
    buckets: List[ShadowVerdictChronicleBucketPayload] = Field(default_factory=list)


class ShadowVerdictChronicleDeltaBucketPayload(BaseModel):
    bucket_label: str
    drop_metrics_before_ms: Optional[int] = None
    drop_volumes_before_ms: Optional[int] = None
    metrics_remove_timestamps_ms: List[int] = Field(default_factory=list)
    volumes_remove_timestamps_ms: List[int] = Field(default_factory=list)
    metrics_upsert: List[ShadowVerdictChronicleMetricPointPayload] = Field(default_factory=list)
    volumes_upsert: List[ShadowVerdictChronicleVolumePointPayload] = Field(default_factory=list)
    verdict_cloud_replace: Optional[List[ShadowVerdictChronicleVerdictPointPayload]] = None


class ShadowVerdictChronicleDeltaVerdictPayload(BaseModel):
    id: int
    resolved_at: datetime
    realized_pnl_percentage: float
    realized_pnl_usd: float
    is_profitable: bool
    exit_reason: str
    order_notional_value_usd: float


class ShadowVerdictChronicleDeltaPayload(BaseModel):
    generated_at_iso: str
    as_of_iso: str
    from_iso: str
    to_iso: str
    total_verdicts_considered: int
    source: str
    series_end_lag_seconds: int
    buckets: List[ShadowVerdictChronicleDeltaBucketPayload]
    verdicts: List[ShadowVerdictChronicleDeltaVerdictPayload]
