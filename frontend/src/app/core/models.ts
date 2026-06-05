export type PositionPhase = 'OPEN' | 'PARTIAL' | 'CLOSING' | 'CLOSED' | 'STALED';
export type PositionExitTriggerReason =
    | 'TAKE_PROFIT_1'
    | 'TAKE_PROFIT_2'
    | 'STOP_LOSS'
    | 'MANUAL'
    | 'KILLED'
    | 'HONEYPOT'
    | 'CIRCUIT_BREAKER'
    | 'WALLET_BALANCE_EMPTY';
export type TradingShadowingPhase = 'DISABLED' | 'SYNCING' | 'SHADOWING' | 'CORTEXING' | 'BEAR' | 'TRADABLE';
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
    linked_position_id: number;
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
    exit_reason?: PositionExitTriggerReason | null;
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

export interface TradingShadowingRegimePayload {
    phase: TradingShadowingPhase;
    edge_gate_enabled: boolean;
    cortex_gate_enabled: boolean;
    fundamentals_gate_enabled: boolean;
    toxic_metrics_gate_enabled: boolean;
    resolved_outcome_count?: number | null;
    required_outcome_count?: number | null;
    elapsed_hours?: number | null;
    required_hours?: number | null;
    edge_eligible_outcome_count?: number | null;
    edge_required_outcome_count?: number | null;
    edge_chronicle_profit_factor?: number | null;
    edge_chronicle_profit_factor_threshold?: number | null;
    edge_chronicle_profit_factor_lookback_days?: number | null;
    edge_chronicle_profit_factor_bucket_width_seconds?: number | null;
    edge_chronicle_profit_factor_moving_average_period?: number | null;
    edge_sparse_expected_value_usd?: number | null;
    edge_sparse_expected_value_usd_threshold?: number | null;
    edge_sparse_expected_value_lookback_days?: number | null;
    edge_sparse_expected_value_bucket_width_seconds?: number | null;
    edge_sparse_expected_value_moving_average_period?: number | null;
    metrics_meta_win_rate?: number | null;
    metrics_meta_average_pnl?: number | null;
    metrics_meta_average_holding_time_hours?: number | null;
    metrics_meta_expected_pnl_velocity?: number | null;
    metrics_meta_profit_factor?: number | null;
    metrics_meta_expected_value_usd?: number | null;
    cortex_training_eligible_outcome_count?: number | null;
    cortex_training_required_outcome_count?: number | null;
}

export interface SolanaTokenAccountRentPayload {
    active_usd: number;
    closable_usd: number;
    pending_reclaim_usd: number;
    locked_sol: number;
    active_account_count: number;
    closable_account_count: number;
    pending_reclaim_account_count: number;
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
    solana_token_account_rent?: SolanaTokenAccountRentPayload;
}

export interface TradingLiquidityPayload {
    mode: TradeMode;
    available_cash_balance: number;
    stablecoin_currency_symbol: string;
    maximum_chain_count: number;
    blockchain_balances: BlockchainCashBalancePayload[];
    updated_at: string;
}

export interface TradingPortfolioPayload {
    total_equity_value: number;
    deployable_cash_usd: number;
    holdings_mark_to_market_usd: number;
    wallet_auxiliary_assets_usd: number;
    sizing_capital_usd: number;
    cumulative_swap_fees_usd: number;
    created_at: string;
    equity_curve: TradingEquityCurvePointPayload[];
    unrealized_profit_and_loss: number;
    realized_profit_and_loss_24h: number;
    realized_profit_and_loss_7d: number;
    realized_profit_and_loss_30d: number;
    realized_profit_and_loss_total: number;
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

export interface TradingEvaluationShadowingMetricEvaluationPayload {
    metric_key: string;
    candidate_value: number;
    bucket_index: number;
    bucket_win_rate: number;
    bucket_average_pnl: number;
    bucket_average_holding_time: number;
    bucket_expected_pnl_velocity: number;
    bucket_outlier_hit_rate: number;
    bucket_sample_count: number;
    is_toxic: boolean;
    is_golden: boolean;
    normalized_influence: number;
}

export interface TradingFilterVerdictPayload {
    is_accepted: boolean;
    rejection_reasons: string[];
}

export interface TradingCortexInferenceSnapshotPayload {
    success_probability: number;
    toxicity_probability: number;
    expected_profit_and_loss_percentage: number;
    predicted_holding_time_minutes: number;
    final_trade_score: number;
    model_version: string;
    model_ready: boolean;
    gate_verdict: TradingFilterVerdictPayload;
}

export interface TradingEvaluationShadowingSnapshotPayload {
    regime: TradingShadowingRegimePayload;
    metrics: TradingEvaluationShadowingMetricEvaluationPayload[];
    cortex_inference?: TradingCortexInferenceSnapshotPayload | null;
}

export interface TradingEvaluationShadowingDiagnosticsPayload {
    cortex_inference_summary: Record<string, unknown> | null;
    shadowing_regime: TradingShadowingRegimePayload | null;
    shadowing_metrics: TradingEvaluationShadowingMetricEvaluationPayload[] | null;
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
    promotion_score?: number | null;
}

export interface TradingScreenerEnvelopePayload {
    provider_id: string;
    payload: Record<string, object>;
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
    shadowing_diagnostics: TradingEvaluationShadowingDiagnosticsPayload;
    screener_envelope: TradingScreenerEnvelopePayload;
    raw_configuration_settings: Record<string, object>;
    linked_position?: TradingPositionPayload | null;
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
    TRADING_PORTFOLIO = 'trading_portfolio',
    TRADING_LIQUIDITY = 'trading_liquidity',
    TRADING_SHADOWING_REGIME = 'trading_shadowing_regime',
    TRADING_SHADOWING_VERDICT_CHRONICLE = 'trading_shadowing_verdict_chronicle',
    TRADING_POSITIONS = 'trading_positions',
    TRADING_POSITION_PRICES = 'trading_position_prices',
    TRADING_TRADES = 'trading_trades',
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

export interface WebsocketTradingPortfolioMessage extends BaseWebsocketMessage<TradingPortfolioPayload> {
    type: WebsocketMessageType.TRADING_PORTFOLIO;
}

export interface WebsocketTradingLiquidityMessage extends BaseWebsocketMessage<TradingLiquidityPayload> {
    type: WebsocketMessageType.TRADING_LIQUIDITY;
}

export interface WebsocketTradingShadowingRegimeMessage extends BaseWebsocketMessage<TradingShadowingRegimePayload> {
    type: WebsocketMessageType.TRADING_SHADOWING_REGIME;
}

export interface WebsocketTradingShadowingVerdictChronicleMessage extends BaseWebsocketMessage<TradingShadowingVerdictChroniclePayload> {
    type: WebsocketMessageType.TRADING_SHADOWING_VERDICT_CHRONICLE;
}

export interface WebsocketTradingPositionsMessage extends BaseWebsocketMessage<TradingPositionPayload[]> {
    type: WebsocketMessageType.TRADING_POSITIONS;
}

export interface WebsocketTradingPositionPricesMessage extends BaseWebsocketMessage<TradingPositionPricePayload[]> {
    type: WebsocketMessageType.TRADING_POSITION_PRICES;
}

export interface WebsocketTradingTradesMessage extends BaseWebsocketMessage<TradingTradePayload[]> {
    type: WebsocketMessageType.TRADING_TRADES;
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
    | WebsocketTradingPortfolioMessage
    | WebsocketTradingLiquidityMessage
    | WebsocketTradingShadowingRegimeMessage
    | WebsocketTradingShadowingVerdictChronicleMessage
    | WebsocketTradingPositionsMessage
    | WebsocketTradingPositionPricesMessage
    | WebsocketTradingTradesMessage
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

export interface TradingAnalyticsHeatmapCellPayload {
    range_label: string;
    range_min: number;
    range_max: number;
    average_pnl: number;
    average_holding_time_minutes: number;
    expected_pnl_velocity: number;
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

export interface TradingAnalyticsHeatmapSeriesPayload {
    metric_key: string;
    metric_label: string;
    cells: TradingAnalyticsHeatmapCellPayload[];
}

export interface TradingAnalyticsTimelinePointPayload {
    date_iso: string;
    cumulative_pnl_usd: number;
    cumulative_pnl_percentage: number;
    rolling_win_rate: number;
    trade_count: number;
}

export interface TradingAnalyticsScatterPointPayload {
    metric_value: number;
    pnl_percentage: number;
    pnl_usd: number;
    token_symbol: string;
    exit_reason: string;
}

export interface TradingAnalyticsScatterSeriesPayload {
    metric_key: string;
    metric_label: string;
    points: TradingAnalyticsScatterPointPayload[];
}

export interface TradingAnalyticsKpiPayload {
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
    expected_pnl_velocity: number;
}

export interface TradingAnalyticsResponse {
    kpis: TradingAnalyticsKpiPayload;
    pnl_drivers_series: TradingAnalyticsHeatmapSeriesPayload[];
    timeline: TradingAnalyticsTimelinePointPayload[];
    scatter_series: TradingAnalyticsScatterSeriesPayload[];
}

export interface TradingShadowingVerdictChronicleMetricPointPayload {
    timestamp_milliseconds: number;
    average_pnl_percentage: number;
    average_win_rate_percentage: number;
    expected_value_per_trade_usd: number;
    total_wallet_value_usd: number;
    closed_verdicts_per_hour: number;
    profit_factor: number;
    average_cortex_prediction_win_rate_percentage?: number | null;
    average_cortex_predicted_holding_time_minutes?: number | null;
    cortex_skill_score_percentage?: number | null;
    cortex_calibration_gap_percentage_points?: number | null;
    cortex_high_conviction_accuracy_percentage?: number | null;
    cortex_high_conviction_share_percentage?: number | null;
    cortex_gate_precision_percentage?: number | null;
    cortex_gate_pass_rate_percentage?: number | null;
}

export interface TradingShadowingVerdictChronicleVolumePointPayload {
    timestamp_milliseconds: number;
    verdict_count: number;
}

export interface TradingShadowingVerdictChronicleVerdictPointPayload {
    verdict_id: number;
    timestamp_milliseconds: number;
    pnl_percentage: number;
    pnl_usd: number;
    exit_reason: string;
    order_notional_usd: number;
    point_size: number;
    is_profitable: boolean;
    cortex_probability?: number | null;
}

export interface TradingShadowingVerdictChronicleCortexReliabilityBinPayload {
    predicted_probability_bin_center: number;
    mean_predicted_probability: number;
    empirical_win_rate: number;
    verdict_count: number;
}

export interface TradingShadowingVerdictChronicleRegimeGatePointPayload {
    timestamp_milliseconds: number;
    regime_profit_factor_sma?: number | null;
    regime_sparse_expected_value_usd_sma?: number | null;
    profit_factor_gate_open: boolean;
    sparse_expected_value_gate_open: boolean;
    hard_gate_open: boolean;
}

export interface TradingShadowingVerdictChronicleCortexModelRolloutPayload {
    activated_at_milliseconds: number;
    model_version: string;
    feature_set_version: string;
    training_record_count: number;
    validation_record_count: number;
    success_probability_accuracy: number;
    is_active: boolean;
    label: string;
}

export interface TradingShadowingVerdictChronicleBucketPayload {
    bucket_label: string;
    granularity_seconds: number;
    from_iso: string;
    to_iso: string;
    metrics: TradingShadowingVerdictChronicleMetricPointPayload[];
    volumes: TradingShadowingVerdictChronicleVolumePointPayload[];
    verdict_cloud: TradingShadowingVerdictChronicleVerdictPointPayload[];
    cortex_reliability_diagram?: TradingShadowingVerdictChronicleCortexReliabilityBinPayload[];
    regime_gate?: TradingShadowingVerdictChronicleRegimeGatePointPayload[];
}

export interface TradingShadowingVerdictChroniclePayload {
    generated_at_iso: string;
    as_of_iso: string;
    from_iso: string;
    to_iso: string;
    total_verdicts_considered: number;
    source: string;
    buckets: TradingShadowingVerdictChronicleBucketPayload[];
    cortex_model_rollouts?: TradingShadowingVerdictChronicleCortexModelRolloutPayload[];
}
