export type Phase = 'OPEN' | 'TP1' | 'TP2' | 'CLOSED';
export type Side = 'BUY' | 'SELL';
export type TradeMode = 'LIVE' | 'PAPER';

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
    opened_at?: string;
    updated_at?: string;
    closed_at?: string | null;
}

export interface Trade {
    id?: number;
    date: string;
    side: Side;
    symbol: string;
    price: number;
    qty: number;
    fee?: number | null;
    pnl?: number | null;
    status: TradeMode;
    address?: string;
    tx_hash?: string | null;
    notes?: string | null;
}

export interface Portfolio {
    equity: number;
    cash: number;
    holdings: number;
    win_rate?: number;
    updated_at?: string;
    equity_curve?: { t: number; v: number }[];
    pnl_daily?: { t: number; v: number }[];
}

export interface WsEnvelope<T = any> {
    type: 'init'|'status'|'portfolio'|'positions'|'trades'|'snapshots'|'pong';
    payload: T;
}

export interface StatusPayload {
    mode: TradeMode;
    web3_ok: boolean;
    interval: number;
}
