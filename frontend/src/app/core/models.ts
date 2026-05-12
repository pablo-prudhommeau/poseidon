export type PositionPhase = 'OPEN' | 'PARTIAL' | 'CLOSED' | 'STALED';
export type TradeSide = 'BUY' | 'SELL';
export type ExecutionStatus = 'LIVE' | 'PAPER';
export type TradeMode = 'LIVE' | 'PAPER';
export type DcaStrategyStatus = 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'CANCELLED';
export type DcaOrderStatus =
    | 'PENDING'
    | 'WAITING_USER_APPROVAL'
    | 'APPROVED'
    | 'WITHDRAWN_FROM_AAVE'
    | 'SWAPPED'
    | 'EXECUTED'
    | 'SKIPPED'
    | 'FAILED'
    | 'REJECTED';

export interface SystemHealthComponentPayload {
    ok: boolean;
}

export interface SystemHealthComponentsPayload {
    database: SystemHealthComponentPayload;
}

export interface SystemHealthPayload {
    status: string;
    timestamp: string;
    components: SystemHealthComponentsPayload;
}

export interface TradingPaperResetPayload {
    ok: boolean;
}

export interface DcaStrategyCreatePayload {
    blockchain_network: string;
    source_asset_symbol: string;
    source_asset_address: string;
    source_asset_decimals: number;
    target_asset_symbol: string;
    target_asset_address: string;
    binance_trading_pair: string;
    total_allocated_budget: number;
    total_planned_executions: number;
    strategy_start_date: string;
    strategy_end_date: string;
    bypass_security_approval: boolean;
    slippage_tolerance: number;
    average_unit_price_elasticity_factor: number;
    bear_market_start_date: string;
    bear_market_end_date: string;
    current_cycle_index: number;
    previous_all_time_high_price: number;
    previous_bull_market_amplitude_percentage: number;
    curve_flattening_factor: number;
    bear_market_bottom_multiplier: number;
    minimum_bull_market_multiplier: number;
    aave_estimated_annual_percentage_yield: number;
}

export interface DcaStrategyCreateResponse {
    message: string;
    strategy_id: number;
    orders_count: number;
}

export interface DcaOrderPayload {
    id: number;
    strategy_id: number;
    planned_execution_date: string;
    planned_source_asset_amount: number;
    executed_source_asset_amount?: number | null;
    executed_target_asset_amount?: number | null;
    order_status: DcaOrderStatus;
    transaction_hash?: string | null;
    actual_execution_price?: number | null;
    executed_at?: string | null;
    allocation_decision_description?: string | null;
}

export interface DcaBacktestSeriesPointPayload {
    timestamp_iso: string;
    execution_price: number;
    average_purchase_price: number;
    cumulative_spent: number;
    dry_powder_remaining: number;
}

export interface DcaBacktestMetadataPayload {
    source_asset_symbol: string;
    total_allocated_budget: number;
    total_planned_executions: number;
    final_dumb_average_unit_price: number;
    final_smart_average_unit_price: number;
    total_overheat_retentions: number;
}

export interface DcaBacktestPayload {
    metadata: DcaBacktestMetadataPayload;
    dumb_dca_series: DcaBacktestSeriesPointPayload[];
    smart_dca_series: DcaBacktestSeriesPointPayload[];
}

export interface DcaStrategyPayload {
    id: number;
    blockchain_network: string;
    source_asset_symbol: string;
    source_asset_address: string;
    source_asset_decimals: number;
    source_asset_currency_symbol: string;
    target_asset_symbol: string;
    target_asset_address: string;
    target_asset_currency_symbol: string;
    binance_trading_pair: string;
    total_allocated_budget: number;
    total_planned_executions: number;
    amount_per_execution_order: number;
    slippage_tolerance: number;
    average_unit_price_elasticity_factor: number;
    current_cycle_index: number;
    previous_all_time_high_price: number;
    previous_bull_market_amplitude_percentage: number;
    curve_flattening_factor: number;
    bear_market_bottom_multiplier: number;
    minimum_bull_market_multiplier: number;
    aave_estimated_annual_percentage_yield: number;
    realized_aave_yield_amount: number;
    last_yield_calculation_timestamp: string;
    strategy_start_date: string;
    strategy_end_date: string;
    strategy_status: DcaStrategyStatus;
    bypass_security_approval: boolean;
    available_dry_powder: number;
    total_deployed_amount: number;
    average_purchase_price: number;
    historical_backtest_payload: DcaBacktestPayload;
    created_at: string;
    updated_at: string;
    execution_orders: DcaOrderPayload[];
    live_aave_apy: number;
    live_market_price: number;
}

export interface DcaStrategiesResponse {
    strategies: DcaStrategyPayload[];
}

export interface DcaOrdersResponse {
    orders: DcaOrderPayload[];
}

export interface TradingTradePayload {
    id: number;
    evaluation_id: number;
    trade_side: TradeSide;
    token_symbol: string;
    blockchain_network: string;
    execution_price: number;
    execution_quantity: number;
    transaction_fee: number;
    execution_status: ExecutionStatus;
    token_address: string;
    pair_address: string;
    created_at: string;
    dex_id: string;
    realized_profit_and_loss?: number | null;
    transaction_hash?: string | null;
    linked_position: TradingPositionPayload;
}

export interface TradingPositionPayload {
    id: number;
    evaluation_id: number;
    token_symbol: string;
    token_address: string;
    pair_address: string;
    open_quantity: number;
    current_quantity: number;
    entry_price: number;
    take_profit_tier_1_price: number;
    take_profit_tier_2_price: number;
    stop_loss_price: number;
    position_phase: PositionPhase;
    blockchain_network: string;
    dex_id: string;
    opened_at: string;
    updated_at: string;
    closed_at?: string | null;
    last_price?: number | null;
}

export interface TradingPositionPricePayload {
    position_id: number;
    pair_address: string;
    last_price?: number | null;
    delta_percent?: number | null;
}

export interface TradingEquityCurvePointPayload {
    timestamp_milliseconds: number;
    total_equity_value: number;
}

export interface ShadowIntelligenceStatusPayload {
    is_enabled: boolean;
    phase: string;
    resolved_outcome_count: number;
    required_outcome_count: number;
    elapsed_hours: number;
    required_hours: number;
    outcome_progress_percentage: number;
    hours_progress_percentage: number;
}

export interface BlockchainCashBalancePayload {
    blockchain_network: string;
    stablecoin_symbol: string;
    stablecoin_address: string;
    stablecoin_currency_symbol: string;
    balance_raw: number;
    native_token_symbol: string;
    native_token_balance_raw: number;
    native_token_balance_usd: number;
}

export interface TradingLiquidityPayload {
    mode: TradeMode;
    available_cash_balance: number;
    stablecoin_currency_symbol: string;
    maximum_chain_count: number;
    blockchain_balances: BlockchainCashBalancePayload[];
    updated_at: string;
}

export interface TradingShadowMetaPayload {
    is_enabled: boolean;
    is_activated: boolean;
    phase: string;
    total_outcomes_analyzed: number;
    resolved_outcome_count: number;
    elapsed_hours: number;
    win_rate_percentage: number;
    expected_value_usd: number;
    capital_velocity: number;
    global_profit_factor: number;
    empirical_profit_factor: number;
    empirical_profit_factor_threshold: number;
    empirical_profit_factor_window_verdict_count: number;
    chronicle_profit_factor: number;
    chronicle_profit_factor_threshold: number;
    chronicle_profit_factor_lookback_days: number;
    chronicle_profit_factor_bucket_width_seconds: number;
    chronicle_profit_factor_moving_average_period: number;
    sparse_expected_value_usd: number;
    sparse_expected_value_usd_threshold: number;
    sparse_expected_value_lookback_days: number;
    sparse_expected_value_bucket_width_seconds: number;
    sparse_expected_value_moving_average_period: number;
}

export interface TradingPortfolioPayload {
    total_equity_value: number;
    available_cash_balance: number;
    active_holdings_value: number;
    created_at: string;
    equity_curve: TradingEquityCurvePointPayload[];
    unrealized_profit_and_loss: number;
    realized_profit_and_loss_24h: number;
    realized_profit_and_loss_total: number;
    shadow_intelligence_status: ShadowIntelligenceStatusPayload;
    blockchain_balances: BlockchainCashBalancePayload[];
}

export interface TradingEvaluationScoresPayload {
    quality_score: number;
    ai_adjusted_quality_score: number;
}

export interface TradingEvaluationAiPayload {
    ai_probability_take_profit_before_stop_loss: number;
    ai_quality_score_delta: number;
}

export interface TradingEvaluationDecisionPayload {
    execution_decision: string;
    sizing_multiplier: number;
    order_notional_value_usd: number;
    free_cash_before_execution_usd: number;
    free_cash_after_execution_usd: number;
}

export interface TradingEvaluationShadowIntelligenceSnapshotSummaryPayload {
    is_activated: boolean;
    total_outcomes_analyzed: number;
    resolved_outcome_count: number;
    elapsed_hours: number;
    meta_win_rate: number;
    meta_average_pnl: number;
    meta_average_holding_time_hours: number;
    meta_capital_velocity: number;
    meta_profit_factor: number;
    meta_expected_value_usd: number;
    empirical_profit_factor: number;
    chronicle_profit_factor: number;
    chronicle_profit_factor_threshold: number;
    sparse_expected_value_usd: number;
}

export interface TradingEvaluationShadowIntelligenceSnapshotMetricPayload {
    metric_key: string;
    candidate_value: number;
    bucket_index: number;
    bucket_win_rate: number;
    bucket_average_pnl: number;
    bucket_average_holding_time: number;
    bucket_capital_velocity: number;
    bucket_outlier_hit_rate: number;
    bucket_sample_count: number;
    is_toxic: boolean;
    is_golden: boolean;
    normalized_influence: number;
}

export interface TradingEvaluationShadowIntelligenceSnapshotPayload {
    summary: TradingEvaluationShadowIntelligenceSnapshotSummaryPayload;
    evaluated_metrics: TradingEvaluationShadowIntelligenceSnapshotMetricPayload[];
}

export interface TradingEvaluationShadowDiagnosticsPayload {
    intelligence_snapshot: TradingEvaluationShadowIntelligenceSnapshotPayload;
}

export interface TradingEvaluationShadowSimulationPayload {
    id: number;
    take_profit_tier_1_price: number;
    take_profit_tier_2_price: number;
    stop_loss_price: number;
    take_profit_tier_1_hit_at?: string | null;
    take_profit_tier_2_hit_at?: string | null;
    stop_loss_hit_at?: string | null;
    exit_reason?: string | null;
    realized_pnl_percentage?: number | null;
    realized_pnl_usd?: number | null;
    holding_duration_minutes?: number | null;
    is_profitable?: boolean | null;
    resolved_at?: string | null;
}

export interface TradingEvaluationFundamentalsPayload {
    token_age_hours: number;
    volume_m5_usd: number;
    volume_h1_usd: number;
    volume_h6_usd: number;
    volume_h24_usd: number;
    liquidity_usd: number;
    price_change_percentage_m5: number;
    price_change_percentage_h1: number;
    price_change_percentage_h6: number;
    price_change_percentage_h24: number;
    transaction_count_m5: number;
    transaction_count_h1: number;
    transaction_count_h6: number;
    transaction_count_h24: number;
    buy_to_sell_ratio: number;
    market_cap_usd: number;
    fully_diluted_valuation_usd: number;
    dexscreener_boost?: number | null;
}

export interface TradingEvaluationPayload {
    id: number;
    token_symbol: string;
    blockchain_network: string;
    token_address: string;
    pair_address: string;
    evaluated_at: string;
    candidate_rank: number;
    scores: TradingEvaluationScoresPayload;
    ai: TradingEvaluationAiPayload;
    fundamentals: TradingEvaluationFundamentalsPayload;
    decision: TradingEvaluationDecisionPayload;
    shadow_diagnostics: TradingEvaluationShadowDiagnosticsPayload;
    raw_dexscreener_payload: Record<string, object>;
    raw_configuration_settings: Record<string, object>;
}

export interface TradingPositionsResponse {
    positions: TradingPositionPayload[];
}

export interface WebsocketStatusPayload {
    paper_mode: boolean;
    interval_seconds: number;
}

export interface WebsocketInitializationPayload {
    status: WebsocketStatusPayload;
}

export enum WebsocketMessageType {
    INITIALIZATION = 'initialization',
    PORTFOLIO = 'portfolio',
    LIQUIDITY = 'liquidity',
    SHADOW_META = 'shadow_meta',
    SHADOW_VERDICT_CHRONICLE = 'shadow_verdict_chronicle',
    SHADOW_VERDICT_CHRONICLE_DELTA = 'shadow_verdict_chronicle_delta',
    POSITIONS = 'positions',
    POSITION_PRICES = 'position_prices',
    TRADES = 'trades',
    DCA_STRATEGIES = 'dca_strategies',
    PONG = 'pong',
    ERROR = 'error',
    REFRESH = 'refresh',
    PING = 'ping'
}

export interface BaseWebsocketMessage<T> {
    type: WebsocketMessageType;
    payload: T;
}

export interface WebsocketInitializationMessage extends BaseWebsocketMessage<WebsocketInitializationPayload> {
    type: WebsocketMessageType.INITIALIZATION;
}

export interface WebsocketPortfolioMessage extends BaseWebsocketMessage<TradingPortfolioPayload> {
    type: WebsocketMessageType.PORTFOLIO;
}

export interface WebsocketLiquidityMessage extends BaseWebsocketMessage<TradingLiquidityPayload> {
    type: WebsocketMessageType.LIQUIDITY;
}

export interface WebsocketShadowMetaMessage extends BaseWebsocketMessage<TradingShadowMetaPayload> {
    type: WebsocketMessageType.SHADOW_META;
}

export interface WebsocketShadowVerdictChronicleMessage extends BaseWebsocketMessage<ShadowVerdictChronicleResponse> {
    type: WebsocketMessageType.SHADOW_VERDICT_CHRONICLE;
}

export interface WebsocketShadowVerdictChronicleDeltaMessage extends BaseWebsocketMessage<ShadowVerdictChronicleDeltaPayload> {
    type: WebsocketMessageType.SHADOW_VERDICT_CHRONICLE_DELTA;
}

export interface WebsocketPositionsMessage extends BaseWebsocketMessage<TradingPositionPayload[]> {
    type: WebsocketMessageType.POSITIONS;
}

export interface WebsocketPositionPricesMessage extends BaseWebsocketMessage<TradingPositionPricePayload[]> {
    type: WebsocketMessageType.POSITION_PRICES;
}

export interface WebsocketTradesMessage extends BaseWebsocketMessage<TradingTradePayload[]> {
    type: WebsocketMessageType.TRADES;
}

export interface WebsocketDcaStrategiesMessage extends BaseWebsocketMessage<DcaStrategyPayload[]> {
    type: WebsocketMessageType.DCA_STRATEGIES;
}

export interface WebsocketErrorMessage extends BaseWebsocketMessage<string | object> {
    type: WebsocketMessageType.ERROR;
}

export interface WebsocketPongMessage {
    type: WebsocketMessageType.PONG;
}

export interface WebsocketPingMessage {
    type: WebsocketMessageType.PING;
}

export interface WebsocketRefreshMessage {
    type: WebsocketMessageType.REFRESH;
}

export type WebsocketMessageUnion =
    | WebsocketInitializationMessage
    | WebsocketPortfolioMessage
    | WebsocketLiquidityMessage
    | WebsocketShadowMetaMessage
    | WebsocketShadowVerdictChronicleMessage
    | WebsocketShadowVerdictChronicleDeltaMessage
    | WebsocketPositionsMessage
    | WebsocketPositionPricesMessage
    | WebsocketTradesMessage
    | WebsocketDcaStrategiesMessage
    | WebsocketErrorMessage
    | WebsocketPongMessage
    | WebsocketPingMessage
    | WebsocketRefreshMessage;

export interface MacroProjectionSavings {
    live: number;
    bear: number;
    bull: number;
    bearPriceTarget: number;
    bullPriceTarget: number;
    livePrice: number;
    cryptoAmount: number;
}

export interface YieldMetrics {
    realized: number;
    projectedRemaining: number;
    apy: number;
}

export interface TimelineNode {
    identifier: string;
    timestamp: number;
    leftPositionPercent: number;
    isMajor: boolean;
    isMinor: boolean;
    isMonthBoundary: boolean;
    isProcessing: boolean;
    orders: DcaOrderPayload[];
    label: string;
    representativeStatus: string;
    totalPlannedAmount: number;
    totalExecutedAmount: number;
    totalAcquiredTargetAssetAmount: number;
    protectedOrderCount: number;
    skippedOrderCount: number;
    plannedExecutionDate: string;
    periodLabel: string;
    periodStartDate: number | null;
}

export interface OrderDueDateMarker {
    leftPositionPercent: number;
    status: string;
}

export interface AnalyticsHeatmapCellPayload {
    range_label: string;
    range_min: number;
    range_max: number;
    average_pnl: number;
    average_holding_time_minutes: number;
    capital_velocity: number;
    quartile_1_pnl: number;
    quartile_3_pnl: number;
    sample_count: number;
    win_count: number;
    win_rate_percentage: number;
    outlier_hit_rate_percentage: number;
    is_optimal: boolean;
    is_golden: boolean;
    is_toxic: boolean;
}

export interface AnalyticsHeatmapSeriesPayload {
    metric_key: string;
    metric_label: string;
    cells: AnalyticsHeatmapCellPayload[];
}

export interface AnalyticsTimelinePointPayload {
    date_iso: string;
    cumulative_pnl_usd: number;
    cumulative_pnl_percentage: number;
    rolling_win_rate: number;
    trade_count: number;
}

export interface AnalyticsScatterPointPayload {
    metric_value: number;
    pnl_percentage: number;
    pnl_usd: number;
    token_symbol: string;
    exit_reason: string;
}

export interface AnalyticsScatterSeriesPayload {
    metric_key: string;
    metric_label: string;
    points: AnalyticsScatterPointPayload[];
}

export interface AnalyticsKpiPayload {
    total_evaluations: number;
    total_outcomes: number;
    win_count: number;
    loss_count: number;
    win_rate_percentage: number;
    total_pnl_usd: number;
    average_pnl_percentage: number;
    average_holding_duration_minutes: number;
    best_trade_pnl_percentage: number;
    worst_trade_pnl_percentage: number;
    profit_factor: number;
    expected_value_usd: number;
    capital_velocity: number;
}

export interface AnalyticsResponse {
    kpis: AnalyticsKpiPayload;
    pnl_drivers_series: AnalyticsHeatmapSeriesPayload[];
    timeline: AnalyticsTimelinePointPayload[];
    scatter_series: AnalyticsScatterSeriesPayload[];
}

export interface ShadowVerdictChronicleMetricPointPayload {
    timestamp_milliseconds: number;
    average_pnl_percentage: number;
    average_win_rate_percentage: number;
    expected_value_per_trade_usd: number;
    capital_velocity_per_hour: number;
    profit_factor: number;
}

export interface ShadowVerdictChronicleVolumePointPayload {
    timestamp_milliseconds: number;
    verdict_count: number;
}

export interface ShadowVerdictChronicleVerdictPointPayload {
    verdict_id: number;
    timestamp_milliseconds: number;
    pnl_percentage: number;
    pnl_usd: number;
    exit_reason: string;
    order_notional_usd: number;
    point_size: number;
    is_profitable: boolean;
}

export interface ShadowVerdictChronicleBucketPayload {
    bucket_label: string;
    granularity_seconds: number;
    from_iso: string;
    to_iso: string;
    metrics: ShadowVerdictChronicleMetricPointPayload[];
    volumes: ShadowVerdictChronicleVolumePointPayload[];
    verdict_cloud: ShadowVerdictChronicleVerdictPointPayload[];
}

export interface ShadowVerdictChronicleResponse {
    generated_at_iso: string;
    as_of_iso: string;
    from_iso: string;
    to_iso: string;
    total_verdicts_considered: number;
    source: string;
    series_end_lag_seconds: number;
    buckets: ShadowVerdictChronicleBucketPayload[];
}

export interface ShadowVerdictChronicleBucketDeltaPayload {
    bucket_label: string;
    drop_metrics_before_ms?: number | null;
    drop_volumes_before_ms?: number | null;
    metrics_remove_timestamps_ms?: number[];
    volumes_remove_timestamps_ms?: number[];
    metrics_upsert: ShadowVerdictChronicleMetricPointPayload[];
    volumes_upsert: ShadowVerdictChronicleVolumePointPayload[];
    verdict_cloud_replace?: ShadowVerdictChronicleVerdictPointPayload[] | null;
}

export interface ShadowVerdictChronicleDeltaPayload {
    generated_at_iso: string;
    as_of_iso: string;
    from_iso: string;
    to_iso: string;
    total_verdicts_considered: number;
    source: string;
    series_end_lag_seconds: number;
    buckets: ShadowVerdictChronicleBucketDeltaPayload[];
}
