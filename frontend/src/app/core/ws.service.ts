import { Injectable, effect, signal } from '@angular/core';

type WsMsg =
    | { type: 'init'; payload: any }
    | { type: 'portfolio'; payload: any }
    | { type: 'positions'; payload: any[] }
    | { type: 'trade'; payload: any }
    | { type: string; payload?: any };

@Injectable({ providedIn: 'root' })
export class WsService {
    private socket?: WebSocket;

    status = signal<'connecting' | 'open' | 'closed'>('closed');
    meta = signal<any | null>(null);
    portfolio = signal<any | null>(null);
    positions = signal<any[]>([]);
    trades = signal<any[]>([]);

    connect(url = `ws://${location.hostname}:8000/ws`) {
        if (this.socket && (this.socket.readyState === 0 || this.socket.readyState === 1)) return;

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
            case 'positions':
                this.positions.set(msg.payload ?? []);
                break;
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
