export type PositionPhase = 'OPEN' | 'PARTIAL' | 'CLOSED' | 'STALED';
export type TradeSide = 'BUY' | 'SELL';
export type ExecutionStatus = 'LIVE' | 'PAPER';
export type TradeMode = 'LIVE' | 'PAPER';
export type DcaStrategyStatus = 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'CANCELLED';
export type DcaOrderStatus = 'PENDING' | 'WAITING_USER_APPROVAL' | 'APPROVED' | 'WITHDRAWN_FROM_AAVE' | 'SWAPPED' | 'EXECUTED' | 'SKIPPED' | 'FAILED' | 'REJECTED';

export interface EquityCurvePoint {
    timestamp_milliseconds: number;
    total_equity_value: number;
}

export interface Position {
    id: number;
    token_symbol: string;
    token_address: string;
    pair_address: string;
    open_quantity: number;
    entry_price: number;
    take_profit_tier_1_price: number;
    take_profit_tier_2_price: number;
    stop_loss_price: number;
    position_phase: PositionPhase;
    blockchain_network: string;
    opened_at: string;
    updated_at: string;
    closed_at?: string | null;
    last_price: number;
}

export interface Trade {
    id: number;
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
    realized_profit_and_loss?: number | null;
    transaction_hash?: string | null;
}

export interface Portfolio {
    total_equity_value: number;
    available_cash_balance: number;
    active_holdings_value: number;
    created_at: string;
    equity_curve: EquityCurvePoint[];
    unrealized_profit_and_loss: number;
    realized_profit_and_loss_24h: number;
    realized_profit_and_loss_total: number;
}

export interface AnalyticsScores {
    quality_score: number;
    statistics_score: number;
    entry_score: number;
    final_score: number;
}

export interface AnalyticsAi {
    ai_probability_take_profit_before_stop_loss: number;
    ai_quality_score_delta: number;
}

export interface AnalyticsFundamentals {
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
    transaction_count_hour_1: number;
    transaction_count_h6: number;
    transaction_count_h24: number;
}

export interface AnalyticsDecision {
    execution_decision: string;
    execution_decision_reason: string;
    sizing_multiplier: number;
    order_notional_value_usd: number;
    free_cash_before_execution_usd: number;
    free_cash_after_execution_usd: number;
}

export interface AnalyticsOutcome {
    has_trade_outcome: boolean;
    outcome_trade_identifier: number;
    outcome_closed_at: string;
    outcome_holding_duration_minutes: number;
    outcome_realized_profit_and_loss_percentage: number;
    outcome_realized_profit_and_loss_usd: number;
    outcome_was_profitable: boolean;
    outcome_exit_reason: string;
}

export interface Analytics {
    id: number;
    token_symbol: string;
    blockchain_network: string;
    token_address: string;
    pair_address: string;
    evaluated_at: string;
    candidate_rank: number;
    scores: AnalyticsScores;
    ai: AnalyticsAi;
    fundamentals: AnalyticsFundamentals;
    decision: AnalyticsDecision;
    outcome: AnalyticsOutcome;
    raw_dexscreener_payload: any;
    raw_configuration_settings: any;
}

export interface DcaBacktestSeriesPoint {
    timestamp_iso: string;
    execution_price: number;
    average_purchase_price: number;
    cumulative_spent: number;
    dry_powder_remaining: number;
}

export interface DcaBacktestMetadata {
    source_asset_symbol: string;
    total_allocated_budget: number;
    total_planned_executions: number;
    final_dumb_average_unit_price: number;
    final_smart_average_unit_price: number;
    total_overheat_retentions: number;
}

export interface DcaBacktestPayload {
    metadata: DcaBacktestMetadata;
    dumb_dca_series: DcaBacktestSeriesPoint[];
    smart_dca_series: DcaBacktestSeriesPoint[];
}

export interface DcaOrder {
    id: number;
    strategy_identifier: number;
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

export interface DcaStrategy {
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
    execution_orders: DcaOrder[];
    live_aave_apy: number;
    live_market_price: number;
}

export interface CreateDcaPayload {
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
}

export interface WebsocketStatusPayload {
    paper_mode: boolean;
    interval_seconds: number;
}

export interface WebsocketInitializationPayload {
    status: WebsocketStatusPayload;
    portfolio: Portfolio;
    positions: Position[];
    trades: Trade[];
    analytics: Analytics[];
    dca_strategies: DcaStrategy[];
}

export interface WebsocketEventPayload {
    type: string;
    payload: any;
}

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
    orders: DcaOrder[];
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