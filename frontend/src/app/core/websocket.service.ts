import { Injectable, signal } from '@angular/core';
import {Analytics, Portfolio, Position, Trade} from './models';

type WsMsg =
    | { type: 'init'; payload: any }
    | { type: 'portfolio'; payload: any }
    | { type: 'positions'; payload: any[] }
    | { type: 'trade'; payload: any }
    | { type: 'analytics'; payload: any }
    | { type: string; payload?: any };

export type Status = 'connecting' | 'open' | 'closed';

@Injectable({ providedIn: 'root' })
export class WebSocketService {
    private sock?: WebSocket;

    status = signal<Status>('closed');
    portfolio = signal<Portfolio | null>(null);
    positions = signal<Position[]>([]);
    trades = signal<Trade[]>([]);
    analytics = signal<Analytics[]>([]);

    private defaultWsUrl(): string {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${proto}//${location.host}/ws`;
    }

    connect(url = this.defaultWsUrl()) {
        if (this.sock && (this.sock.readyState === 0 || this.sock.readyState === 1)) return;
        this.status.set('connecting');
        const s = new WebSocket(url);
        this.sock = s;

        s.onopen = () => this.status.set('open');

        s.onmessage = (ev) => {
            try {
                const msg = JSON.parse(ev.data) as WsMsg;
                this.apply(msg);
            } catch (e) {
                console.debug('Invalid WS message', ev.data);
            }
        };

        s.onerror = () => this.status.set('closed');

        s.onclose = () => {
            this.status.set('closed');
            this.sock = undefined;
            setTimeout(() => this.connect(url), 3000);
        };
    }

    private apply(msg: WsMsg) {
        switch (msg.type) {
            case 'init': {
                const p = msg.payload;
                this.portfolio.set(p?.portfolio ?? null);
                this.positions.set(p?.positions ?? []);
                this.trades.set(p?.trades ?? []);
                const rows: Analytics[] = Array.isArray(p?.analytics) ? p.analytics : [];
                const sorted = [...rows].sort((a, b) => (b.evaluatedAt || '').localeCompare(a.evaluatedAt || ''));
                this.analytics.set(sorted.slice(0, 5000));
                break;
            }
            case 'portfolio': this.portfolio.set(msg.payload ?? null); break;
            case 'positions': this.positions.set(msg.payload ?? []); break;
            case 'trade': this.trades.update(t => [msg.payload, ...t].slice(0, 200)); break;
            case 'analytics': {
                const row = msg.payload as Analytics;
                this.analytics.update(prev => {
                    const i = prev.findIndex(r => r.id === row.id);
                    if (i >= 0) { const cp = [...prev]; cp[i] = row; return cp; }
                    return [row, ...prev].slice(0, 5000);
                });
                break;
            }
        }
    }
}
