export type Phase = 'OPEN' | 'TP1' | 'TP2' | 'CLOSED';
export type Side = 'BUY' | 'SELL';
export type TradeMode = 'LIVE' | 'PAPER';

/** Equity curve: points [timestamp, value] */
export type EquityCurvePoint = [number, number];

export interface Position {
    id?: number;
    symbol: string;
    address: string;
    qty: number;
    entry: number;
    tp1: number;
    tp2: number;
    stop: number;
    phase: Phase;
    chain?: string;
    opened_at?: string;
    updated_at?: string;
    closed_at?: string | null;
    last_price?: number | null;
    _lastDir?: 'up' | 'down' | null;
    _changePct?: number | null;
}

export interface Trade {
    id: number;
    side: Side;
    symbol: string;
    chain: string;
    price: number;
    qty: number;
    fee: number;
    pnl?: number | null;
    status: TradeMode;
    address?: string;
    tx_hash?: string | null;
    created_at: string;
}

export interface Portfolio {
    equity: number;
    cash: number;
    holdings: number;
    win_rate?: number;
    updated_at?: string;
    equity_curve?: EquityCurvePoint[];
    unrealized_pnl?: number;
    realized_pnl_24h?: number;
    realized_pnl_total?: number;
}

export interface Analytics {
    id: number;
    symbol: string;
    chain: string;
    address: string;
    evaluatedAt: string;
    rank: number;
    scores: {
        quality: number;
        statistics: number;
        entry: number;
        final: number;
    };
    ai: {
        probabilityTp1BeforeSl: number;
        qualityScoreDelta: number;
    };
    rawMetrics: {
        tokenAgeHours: number;
        volume24hUsd: number;
        liquidityUsd: number;
        pct5m: number;
        pct1h: number;
        pct24h: number;
    };
    pricing: {
        dex: number;
        quoted: number
    };
    decision: {
        action: string;
        reason: string;
        sizingMultiplier: number;
        orderNotionalUsd: number
        freeCashBeforeUsd: number;
        freeCashAfterUsd: number;
    };
    outcome: {
        hasOutcome: boolean;
        tradeId: number;
        closedAt: string;
        holdingMinutes: number;
        pnlPct: number;
        pnlUsd: number;
        wasProfit: boolean;
        exitReason: string;
    };
    raw: {
        dexscreener: any;
        ai: any;
        risk: any;
        pricing: any;
        settings: any;
        order: any;
    };
}


