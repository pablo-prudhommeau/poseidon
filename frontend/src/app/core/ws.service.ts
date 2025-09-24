import {effect, Injectable, signal} from '@angular/core';

type WsMsg =
    | { type: 'init'; payload: any }
    | { type: 'portfolio'; payload: any }
    | { type: 'positions'; payload: any[] }
    | { type: 'trade'; payload: any }
    | { type: string; payload?: any };

export type MoveDir = 'up' | 'down' | 'flat';

export interface PositionView {
    id: string;
    address: string;
    symbol: string;
    qty: number;
    entry: number;
    tp1: number;
    tp2: number;
    stop: number;
    phase: string;
    is_open: boolean;
    updated_at?: string;
    last_price?: number | null;
    _lastDir?: MoveDir;
    _changePct?: number | null;
}

@Injectable({providedIn: 'root'})
export class WsService {
    private prevLastByAddress: Record<string, number> = {};
    private socket?: WebSocket;

    status = signal<'connecting' | 'open' | 'closed'>('closed');
    meta = signal<any | null>(null);
    portfolio = signal<any | null>(null);
    positions = signal<PositionView[]>([]);
    trades = signal<any[]>([]);

    private toNumOrNull(v: any): number | null {
        if (v === null || v === undefined) return null;
        const n = Number(v);
        return Number.isFinite(n) ? n : null;
    }

    connect(url = `ws://${location.hostname}:8000/ws`) {
        if (this.socket && (this.socket.readyState === 0 || this.socket.readyState === 1)) {
            return;
        }

        this.status.set('connecting');
        this.socket = new WebSocket(url);

        this.socket.onopen = () => this.status.set('open');

        this.socket.onmessage = (ev) => {
            try {
                const msg = JSON.parse(ev.data) as WsMsg;
                this.apply(msg);
            } catch {
                // frames "ping" non JSON
            }
        };

        this.socket.onerror = () => this.status.set('closed');

        this.socket.onclose = () => {
            this.status.set('closed');
            this.socket = undefined;
            setTimeout(() => this.connect(url), 3000);
        };
    }

    private apply(msg: WsMsg) {
        switch (msg.type) {
            case 'init':
                this.meta.set(msg.payload?.meta ?? null);
                this.portfolio.set(msg.payload?.portfolio ?? null);
                this.positions.set(msg.payload?.positions ?? []);
                this.trades.set(msg.payload?.trades ?? []);
                break;
            case 'portfolio':
                this.portfolio.set(msg.payload ?? null);
                break;
            case 'positions': {
                const incoming: PositionView[] = (msg.payload ?? []).map((p: any) => {
                    const last = this.toNumOrNull(p.last_price);
                    const entry = this.toNumOrNull(p.entry);
                    const prev  = this.prevLastByAddress[p.address];

                    let dir: 'up' | 'down' | 'flat' = 'flat';
                    if (last !== null) {
                        if (prev !== undefined) dir = last > prev ? 'up' : (last < prev ? 'down' : 'flat');
                        this.prevLastByAddress[p.address] = last;
                    }

                    let changePct: number | null = null;
                    if (last !== null && entry !== null && entry > 0) {
                        changePct = ((last - entry) / entry) * 100;
                    }

                    return { ...p, last_price: last, _lastDir: dir, _changePct: changePct } as PositionView;
                });

                this.positions.set(incoming);
                break;
            }
            case 'trade':
                this.trades.update(t => [msg.payload, ...t].slice(0, 100));
                break;
        }
    }

    constructor() {
        // DEBUG signals
        effect(() => console.log('[SIG] ws status:', this.status()));
        effect(() => console.log('[SIG] positions:', this.positions().length));
    }
}
