export type Phase = 'OPEN' | 'PARTIAL' | 'CLOSED' | 'STALED';
export type Side = 'BUY' | 'SELL';
export type TradeMode = 'LIVE' | 'PAPER';
export type DcaStrategyStatus = 'ACTIVE' | 'PAUSED' | 'COMPLETED' | 'CANCELLED';
export type DcaOrderStatus = 'PENDING' | 'WAITING_USER_APPROVAL' | 'APPROVED' | 'WITHDRAWN_FROM_AAVE' | 'SWAPPED' | 'EXECUTED' | 'SKIPPED' | 'FAILED';

export interface EquityCurvePoint {
    timestamp: number;
    equity: number;
}

export interface Position {
    id: number;
    symbol: string;
    tokenAddress: string;
    pairAddress: string;
    qty: number;
    entry: number;
    tp1: number;
    tp2: number;
    stop: number;
    phase: Phase;
    chain: string;
    opened_at: string;
    updated_at: string;
    closed_at?: string | null;
    last_price: number;
}

export interface Trade {
    id: number;
    side: Side;
    symbol: string;
    chain: string;
    price: number;
    qty: number;
    fee: number;
    status: TradeMode;
    tokenAddress: string;
    pairAddress: string;
    created_at: string;
    pnl?: number | null;
    tx_hash?: string;
}

export interface Portfolio {
    equity: number;
    cash: number;
    holdings: number;
    updated_at: string;
    equity_curve: EquityCurvePoint[];
    unrealized_pnl: number;
    realized_pnl_24h: number;
    realized_pnl_total: number;
}

export interface AnalyticsScores {
    quality: number;
    statistics: number;
    entry: number;
    final: number;
}

export interface AnalyticsAi {
    probabilityTp1BeforeSl: number;
    qualityScoreDelta: number;
}

export interface AnalyticsFundamentals {
    tokenAgeHours: number;
    volume5mUsd: number;
    volume1hUsd: number;
    volume6hUsd: number;
    volume24hUsd: number;
    liquidityUsd: number;
    pct5m: number;
    pct1h: number;
    pct6h: number;
    pct24h: number;
    tx5m: number;
    tx1h: number;
    tx6h: number;
    tx24h: number;
}

export interface AnalyticsDecision {
    action: string;
    reason: string;
    sizingMultiplier: number;
    orderNotionalUsd: number;
    freeCashBeforeUsd: number;
    freeCashAfterUsd: number;
}

export interface AnalyticsOutcome {
    hasOutcome: boolean;
    tradeId: number;
    closedAt: string;
    holdingMinutes: number;
    pnlPct: number;
    pnlUsd: number;
    wasProfit: boolean;
    exitReason: string;
}

export interface Analytics {
    id: number;
    symbol: string;
    chain: string;
    tokenAddress: string;
    pairAddress: string;
    evaluatedAt: string;
    rank: number;
    scores: AnalyticsScores;
    ai: AnalyticsAi;
    fundamentals: AnalyticsFundamentals;
    decision: AnalyticsDecision;
    outcome: AnalyticsOutcome;
    rawScreener: any;
    rawSettings: any;
}

export interface DcaBacktestSeriesPoint {
    timestamp_iso: string;
    execution_price: number;
    average_purchase_price: number;
    cumulative_spent: number;
    dry_powder_remaining: number;
}

export interface DcaBacktestMetadata {
    symbol: string;
    total_budget: number;
    executions: number;
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
    strategy_id: number;
    planned_date: string;
    planned_amount: number;
    executed_amount_in?: number;
    executed_amount_out?: number;
    status: DcaOrderStatus;
    transaction_hash?: string;
    execution_price?: number;
    executed_at?: string;
}

export interface DcaStrategy {
    id: number;
    chain: string;
    asset_in_symbol: string;
    asset_in_address: string;
    asset_in_decimals: number;
    asset_in_currency_symbol: string;
    asset_out_symbol: string;
    asset_out_address: string;
    asset_out_currency_symbol: string;
    binance_pair: string;
    total_budget: number;
    total_executions: number;
    amount_per_order: number;
    slippage: number;
    pru_elasticity_factor: number;
    cycle_index: number;
    previous_ath: number;
    previous_bull_amplitude_pct: number;
    flattening_factor: number;
    bear_bottom_multiplier: number;
    minimum_bull_multiplier: number;
    aave_estimated_apy: number;
    realized_aave_yield: number;
    last_yield_calculation_at: string;
    start_date: string;
    end_date: string;
    status: DcaStrategyStatus;
    bypass_approval: boolean;
    dry_powder: number;
    deployed_amount: number;
    average_purchase_price: number;
    backtest_payload: DcaBacktestPayload;
    created_at: string;
    updated_at: string;
    orders: DcaOrder[];
    live_aave_apy: number;
    live_market_price: number;
    asset_in_accrued_yield: number;
}

export interface CreateDcaPayload {
    chain: string;
    asset_in_symbol: string;
    asset_in_address: string;
    asset_in_decimals: number;
    asset_out_symbol: string;
    asset_out_address: string;
    binance_pair: string;
    total_budget: number;
    total_executions: number;
    start_date: string;
    end_date: string;
    bypass_approval: boolean;
    slippage: number;
    pru_elasticity_factor: number;
    bear_market_start_date: string;
    bear_market_end_date: string;
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
