export type Phase = 'OPEN' | 'TP1' | 'TP2' | 'CLOSED';

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
    side: 'BUY' | 'SELL';
    symbol: string;
    price: number;
    qty: number;
    fee?: number | null;
    pnl?: number | null;
    status: 'LIVE' | 'PAPER';
    address?: string;
    tx_hash?: string | null;
    notes?: string | null;
}

export interface Portfolio {
    equity: number;              // total = cash + holdings_value
    cash: number;
    holdings: number;
    win_rate?: number;           // optionnel
    updated_at?: string;
    equity_curve?: { t: number; v: number }[];
    pnl_daily?: { t: number; v: number }[];
}

export interface WsEnvelope<T = any> {
    type: 'init'|'status'|'portfolio'|'positions'|'trades'|'snapshots'|'pong';
    payload: T;
}

export interface StatusPayload {
    mode: 'PAPER'|'LIVE';
    web3_ok: boolean;
    interval: number; // seconds
}
