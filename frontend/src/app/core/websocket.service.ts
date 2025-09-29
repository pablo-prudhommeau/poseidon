import {Injectable, signal} from '@angular/core';
import {Portfolio, Position, Trade} from './models';

type WebsocketMessage =
    | { type: 'init'; payload: any }
    | { type: 'portfolio'; payload: any }
    | { type: 'positions'; payload: any[] }
    | { type: 'trade'; payload: any }
    | { type: string; payload?: any };

export type Status = 'connecting' | 'open' | 'closed';

@Injectable({providedIn: 'root'})
export class WebSocketService {
    private prevLastByAddress: Record<string, number> = {};
    private socket?: WebSocket;

    status = signal<Status>('closed');
    portfolio = signal<Portfolio | null>(null);
    positions = signal<Position[]>([]);
    trades = signal<Trade[]>([]);

    private toNumOrNull(v: any): number | null {
        if (v === null || v === undefined) {
            return null;
        }
        const n = Number(v);
        return Number.isFinite(n) ? n : null;
    }

    private defaultWsUrl(): string {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${proto}//${location.host}/ws`;
    }

    connect(url = this.defaultWsUrl()) {
        if (this.socket && (this.socket.readyState === 0 || this.socket.readyState === 1)) {
            return;
        }

        this.status.set('connecting');
        this.socket = new WebSocket(url);

        this.socket.onopen = () => this.status.set('open');

        this.socket.onmessage = (ev) => {
            try {
                const msg = JSON.parse(ev.data) as WebsocketMessage;
                this.apply(msg);
            } catch {
                console.debug('Invalid WS message', ev.data);
            }
        };

        this.socket.onerror = () => this.status.set('closed');

        this.socket.onclose = () => {
            this.status.set('closed');
            this.socket = undefined;
            setTimeout(() => this.connect(url), 3000);
        };
    }

    private apply(msg: WebsocketMessage) {
        switch (msg.type) {
            case 'init':
                this.portfolio.set(msg.payload?.portfolio ?? null);
                this.positions.set(msg.payload?.positions ?? []);
                this.trades.set(msg.payload?.trades ?? []);
                break;
            case 'portfolio':
                this.portfolio.set(msg.payload ?? null);
                break;
            case 'positions': {
                const incoming: Position[] = (msg.payload ?? []).map((p: any) => {
                    const last = this.toNumOrNull(p.last_price);
                    const entry = this.toNumOrNull(p.entry);
                    const prev = this.prevLastByAddress[p.address];

                    let dir: 'up' | 'down' | 'flat' = 'flat';
                    if (last !== null) {
                        if (prev !== undefined) {
                            dir = last > prev ? 'up' : (last < prev ? 'down' : 'flat');
                        }
                        this.prevLastByAddress[p.address] = last;
                    }

                    let changePct: number | null = null;
                    if (last !== null && entry !== null && entry > 0) {
                        changePct = ((last - entry) / entry) * 100;
                    }

                    return {...p, last_price: last, _lastDir: dir, _changePct: changePct} as Position;
                });

                this.positions.set(incoming);
                break;
            }
            case 'trade':
                this.trades.update(t => [msg.payload, ...t].slice(0, 100));
                break;
        }
    }
}
