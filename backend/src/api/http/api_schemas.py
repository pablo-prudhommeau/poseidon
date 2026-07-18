from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict
from pydantic import Field

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingPhase
from src.core.trading.trading_structures import GasRefillBudgetDetailScope


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


class AaveDcaStrategyCreatePayload(BaseModel):
    blockchain_network: BlockchainNetwork
    source_asset_symbol: str
    source_asset_address: str
    source_asset_decimals: int
    target_asset_symbol: str
    target_asset_address: str
    target_asset_decimals: int
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


class AaveDcaStrategyCreateResponse(BaseModel):
    message: str
    strategy_id: int
    orders_count: int


class AaveDcaPipelineOperationPayload(BaseModel):
    step: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    transaction_hash: Optional[str] = None
    route_tool: Optional[str] = None
    source_amount_base_units: Optional[int] = None
    expected_output_base_units: Optional[int] = None
    minimum_output_base_units: Optional[int] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    pipeline_attempt_number: Optional[int] = None


class AaveDcaOrderPipelineOperationsPayload(BaseModel):
    initialized_at: Optional[str] = None
    last_updated_at: Optional[str] = None
    pipeline_operations: list[AaveDcaPipelineOperationPayload]


class AaveDcaOrderPayload(BaseModel):
    id: int
    strategy_id: int
    planned_execution_date: str
    planned_source_asset_amount: float
    executed_source_asset_amount: Optional[float] = None
    executed_target_asset_amount: Optional[float] = None
    order_status: str
    actual_execution_price: Optional[float] = None
    executed_at: Optional[str] = None
    allocation_decision: Optional[str] = None
    allocation_multiplier: Optional[float] = None
    dry_powder_delta: Optional[float] = None
    reference_market_price: Optional[float] = None
    pipeline_operations: Optional[AaveDcaOrderPipelineOperationsPayload] = None
    pipeline_attempt_count: int
    next_attempt_at: Optional[str] = None
    suspension_reason: Optional[str] = None


class AaveDcaBacktestSeriesPointPayload(BaseModel):
    timestamp_iso: str
    execution_price: float
    average_purchase_price: float
    cumulative_spent: float
    dry_powder_remaining: float


class AaveDcaBacktestMetadataPayload(BaseModel):
    source_asset_symbol: str
    total_allocated_budget: float
    total_planned_executions: int
    final_dumb_average_unit_price: float
    final_smart_average_unit_price: float
    total_overheat_retentions: int


class AaveDcaBacktestPayload(BaseModel):
    metadata: AaveDcaBacktestMetadataPayload
    dumb_dca_series: List[AaveDcaBacktestSeriesPointPayload]
    smart_dca_series: List[AaveDcaBacktestSeriesPointPayload]


class AaveDcaStrategyPayload(BaseModel):
    id: int
    blockchain_network: BlockchainNetwork
    source_asset_symbol: str
    source_asset_address: str
    source_asset_decimals: int
    source_asset_currency_symbol: str
    target_asset_symbol: str
    target_asset_address: str
    target_asset_decimals: int
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
    historical_backtest_payload: AaveDcaBacktestPayload
    created_at: str
    updated_at: str
    execution_orders: List[AaveDcaOrderPayload] = []
    live_aave_apy: float
    live_market_price: float


class AaveDcaStrategiesResponse(BaseModel):
    strategies: List[AaveDcaStrategyPayload]


class AaveDcaOrdersResponse(BaseModel):
    orders: List[AaveDcaOrderPayload]


class TradingPositionPayload(BaseModel):
    id: int
    evaluation_id: int
    token_symbol: str
    token_address: str
    pair_address: str
    open_quantity: float
    current_quantity: float
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
    exit_reason: Optional[str] = None
    evaluation_order_notional_value_usd: float
    realized_profit_and_loss_usd: float


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
    linked_position_id: int
    evaluation_order_notional_value_usd: float


class TradingPositionPricePayload(BaseModel):
    position_id: int
    pair_address: str
    last_price: Optional[float] = None
    delta_percent: Optional[float] = None


class TradingEquityCurvePointPayload(BaseModel):
    timestamp_milliseconds: int
    total_equity_value: float


class SolanaTokenAccountRentPayload(BaseModel):
    active_usd: float
    closable_usd: float
    pending_reclaim_usd: float
    locked_sol: float
    active_account_count: int
    closable_account_count: int
    pending_reclaim_account_count: int


class GasRefillLockedBreakdownPayload(BaseModel):
    per_position_cycle_cost_usd: float
    per_position_cycle_cost_native_raw: float
    max_open_positions: int
    portfolio_cycle_cost_usd: float
    portfolio_cycle_cost_native_raw: float
    refill_target_cycle_count: int
    refill_target_budget_usd: float
    refill_target_budget_native_raw: float
    native_gas_balance_usd: float
    native_gas_balance_raw: float
    refill_trigger_cycle_count: int
    refill_trigger_threshold_usd: float
    refill_trigger_threshold_native_raw: float
    locked_stablecoin_usd: float


class BlockchainCashBalancePayload(BaseModel):
    blockchain_network: BlockchainNetwork
    stablecoin_symbol: str
    stablecoin_address: str
    wallet_address: str
    stablecoin_currency_symbol: str
    balance_raw: float
    native_token_symbol: str
    native_token_balance_raw: float
    native_token_balance_usd: float = 0.0
    solana_token_account_rent: Optional[SolanaTokenAccountRentPayload] = None
    gas_refill_locked_stablecoin_usd: float
    gas_refill_locked_breakdown: Optional[GasRefillLockedBreakdownPayload] = None
    gas_refill_budget_detail_scope: Optional[GasRefillBudgetDetailScope] = None


class TradingLiquidityPayload(BaseModel):
    mode: str
    available_cash_balance: float
    stablecoin_currency_symbol: str
    maximum_chain_count: int
    blockchain_balances: List[BlockchainCashBalancePayload] = Field(default_factory=list)
    updated_at: str


class TradingPortfolioPayload(BaseModel):
    total_equity_value: float
    deployable_cash_usd: float
    holdings_mark_to_market_usd: float
    wallet_auxiliary_assets_usd: float
    total_gas_refill_locked_stablecoin_usd: float
    sizing_capital_usd: float
    cumulative_swap_fees_usd: float
    created_at: str
    equity_curve: List[TradingEquityCurvePointPayload]
    unrealized_profit_and_loss: float
    realized_profit_and_loss_24h: float
    realized_profit_and_loss_7d: float
    realized_profit_and_loss_30d: float
    realized_profit_and_loss_total: float
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


class TradingCandidateShadowingMetricEvaluationPayload(BaseModel):
    metric_key: str
    candidate_value: Optional[float] = None
    bucket_index: Optional[int] = None
    bucket_win_rate: Optional[float] = None
    bucket_average_pnl: Optional[float] = None
    bucket_average_holding_time: Optional[float] = None
    bucket_expected_pnl_velocity: Optional[float] = None
    bucket_outlier_hit_rate: Optional[float] = None
    bucket_sample_count: Optional[int] = None
    is_toxic: bool = False
    is_golden: bool = False
    normalized_influence: Optional[float] = None


class TradingEvaluationShadowingSnapshotPayload(BaseModel):
    regime: TradingShadowingRegimePayload
    metrics: List[TradingCandidateShadowingMetricEvaluationPayload] = Field(default_factory=list)


class TradingEvaluationShadowingDiagnosticsPayload(BaseModel):
    cortex_inference_summary: Optional[dict] = None
    shadowing_regime: Optional[TradingShadowingRegimePayload] = None
    shadowing_metrics: Optional[list] = None


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
    promotion_score: Optional[float] = None


class TradingScreenerEnvelopePayload(BaseModel):
    provider_id: str
    payload: dict[str, object] = Field(default_factory=dict)


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
    shadowing_diagnostics: TradingEvaluationShadowingDiagnosticsPayload
    screener_envelope: TradingScreenerEnvelopePayload
    raw_configuration_settings: dict[str, object]
    linked_position: Optional[TradingPositionPayload] = None


class TradingPositionsResponse(BaseModel):
    positions: List[TradingPositionPayload]


class AnalyticsHeatmapCellPayload(BaseModel):
    range_label: str
    range_min: float
    range_max: float
    average_pnl: float
    average_holding_time_minutes: float
    expected_pnl_velocity: float
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
    expected_pnl_velocity: float


class AnalyticsResponse(BaseModel):
    kpis: AnalyticsKpiPayload
    pnl_drivers_series: List[AnalyticsHeatmapSeriesPayload]
    timeline: List[AnalyticsTimelinePointPayload]
    scatter_series: List[AnalyticsScatterSeriesPayload]


class TradingShadowingVerdictChronicleMetricPointPayload(BaseModel):
    timestamp_milliseconds: int
    average_pnl_percentage: float
    average_win_rate_percentage: float
    expected_value_per_trade_usd: float
    total_wallet_value_usd: float
    closed_verdicts_per_hour: float
    profit_factor: float
    average_cortex_prediction_win_rate_percentage: Optional[float] = None
    average_cortex_predicted_holding_time_minutes: Optional[float] = None
    cortex_skill_score_percentage: Optional[float] = None
    cortex_calibration_gap_percentage_points: Optional[float] = None
    cortex_high_conviction_accuracy_percentage: Optional[float] = None
    cortex_high_conviction_share_percentage: Optional[float] = None
    cortex_gate_precision_percentage: Optional[float] = None
    cortex_gate_pass_rate_percentage: Optional[float] = None


class TradingShadowingVerdictChronicleVolumePointPayload(BaseModel):
    timestamp_milliseconds: int
    verdict_count: int


class TradingShadowingVerdictChronicleVerdictPointPayload(BaseModel):
    verdict_id: int
    timestamp_milliseconds: int
    pnl_percentage: float
    pnl_usd: float
    exit_reason: str
    order_notional_usd: float
    point_size: float
    is_profitable: bool
    cortex_probability: Optional[float] = None


class TradingShadowingVerdictChronicleCortexReliabilityBinPayload(BaseModel):
    predicted_probability_bin_center: float
    mean_predicted_probability: float
    empirical_win_rate: float
    verdict_count: int


class TradingShadowingVerdictChronicleRegimeGatePointPayload(BaseModel):
    timestamp_milliseconds: int
    regime_profit_factor_sma: Optional[float] = None
    regime_sparse_expected_value_usd_sma: Optional[float] = None
    profit_factor_gate_open: bool = False
    sparse_expected_value_gate_open: bool = False
    hard_gate_open: bool = False


class TradingShadowingVerdictChronicleCortexModelRolloutPayload(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    activated_at_milliseconds: int
    model_version: str
    feature_set_version: str
    training_record_count: int
    validation_record_count: int
    success_probability_accuracy: float
    is_active: bool
    label: str


class TradingShadowingVerdictChronicleBucketPayload(BaseModel):
    bucket_label: str
    granularity_seconds: int
    from_iso: str
    to_iso: str
    metrics: List[TradingShadowingVerdictChronicleMetricPointPayload] = Field(default_factory=list)
    volumes: List[TradingShadowingVerdictChronicleVolumePointPayload] = Field(default_factory=list)
    verdict_cloud: List[TradingShadowingVerdictChronicleVerdictPointPayload] = Field(default_factory=list)
    cortex_reliability_diagram: List[TradingShadowingVerdictChronicleCortexReliabilityBinPayload] = Field(default_factory=list)
    regime_gate: List[TradingShadowingVerdictChronicleRegimeGatePointPayload] = Field(default_factory=list)


class TradingShadowingVerdictChroniclePayload(BaseModel):
    generated_at_iso: str
    as_of_iso: str
    from_iso: str
    to_iso: str
    total_verdicts_considered: int
    source: str
    buckets: List[TradingShadowingVerdictChronicleBucketPayload] = Field(default_factory=list)
    cortex_model_rollouts: List[TradingShadowingVerdictChronicleCortexModelRolloutPayload] = Field(default_factory=list)


class TradingShadowingRegimePayload(BaseModel):
    phase: TradingShadowingPhase
    edge_gate_enabled: bool
    cortex_gate_enabled: bool
    fundamentals_gate_enabled: bool
    toxic_metrics_gate_enabled: bool
    resolved_outcome_count: Optional[int] = None
    required_outcome_count: Optional[int] = None
    elapsed_hours: Optional[float] = None
    required_hours: Optional[float] = None
    edge_eligible_outcome_count: Optional[int] = None
    edge_required_outcome_count: Optional[int] = None
    edge_chronicle_profit_factor: Optional[float] = None
    edge_chronicle_profit_factor_threshold: Optional[float] = None
    edge_chronicle_profit_factor_lookback_days: Optional[float] = None
    edge_chronicle_profit_factor_bucket_width_seconds: Optional[int] = None
    edge_chronicle_profit_factor_moving_average_period: Optional[int] = None
    edge_sparse_expected_value_usd: Optional[float] = None
    edge_sparse_expected_value_usd_threshold: Optional[float] = None
    edge_sparse_expected_value_lookback_days: Optional[float] = None
    edge_sparse_expected_value_bucket_width_seconds: Optional[int] = None
    edge_sparse_expected_value_moving_average_period: Optional[int] = None
    metrics_meta_win_rate: Optional[float] = None
    metrics_meta_average_pnl: Optional[float] = None
    metrics_meta_average_holding_time_hours: Optional[float] = None
    metrics_meta_expected_pnl_velocity: Optional[float] = None
    metrics_meta_profit_factor: Optional[float] = None
    metrics_meta_expected_value_usd: Optional[float] = None
    cortex_training_eligible_outcome_count: Optional[int] = None
    cortex_training_required_outcome_count: Optional[int] = None
