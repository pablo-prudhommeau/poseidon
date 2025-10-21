import { Injectable, signal } from '@angular/core';
import { Analytics, Portfolio, Position, Trade } from './models';

type InitMsg = { type: 'init'; payload: any };
type PortfolioMsg = { type: 'portfolio'; payload: any };
type PositionsMsg = { type: 'positions'; payload: any[] };
type TradeListMsg = { type: 'trades'; payload: any[] };
type TradeMsg = { type: 'trade'; payload: any };
type AnalyticsMsg = { type: 'analytics'; payload: any };
type PongMsg = { type: 'pong' };
type ErrorMsg = { type: 'error'; payload?: any };

type WsMsg =
    | InitMsg
    | PortfolioMsg
    | PositionsMsg
    | TradeListMsg
    | TradeMsg
    | AnalyticsMsg
    | PongMsg
    | ErrorMsg
    | { type: string; payload?: any };

export type Status = 'connecting' | 'open' | 'closed';

@Injectable({ providedIn: 'root' })
export class WebSocketService {
    private socket?: WebSocket;

    public readonly status = signal<Status>('closed');
    public readonly portfolio = signal<Portfolio | null>(null);
    public readonly positions = signal<Position[]>([]);
    public readonly trades = signal<Trade[]>([]);
    public readonly analytics = signal<Analytics[]>([]);

    private defaultWsUrl(): string {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${location.host}/ws`;
    }

    public connect(url = this.defaultWsUrl()): void {
        if (this.socket && (this.socket.readyState === WebSocket.CONNECTING || this.socket.readyState === WebSocket.OPEN)) {
            return;
        }

        this.status.set('connecting');
        const socket = new WebSocket(url);
        this.socket = socket;

        socket.onopen = () => {
            this.status.set('open');
            console.info('[WS][OPEN] WebSocket connection established');
        };

        socket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data) as WsMsg;
                this.apply(message);
            } catch {
                console.debug('[WS][ERROR] Invalid WS message payload', event.data);
            }
        };

        socket.onerror = () => {
            this.status.set('closed');
            console.debug('[WS][ERROR] Socket error');
        };

        socket.onclose = () => {
            this.status.set('closed');
            this.socket = undefined;
            console.info('[WS][CLOSE] Socket closed — attempting reconnect soon');
            setTimeout(() => this.connect(url), 3000);
        };
    }

    private apply(message: WsMsg): void {
        switch (message.type) {
            case 'init': {
                const payload = (message as InitMsg).payload;
                this.portfolio.set(payload?.portfolio ?? null);
                this.positions.set(payload?.positions ?? []);
                this.trades.set(payload?.trades ?? []);
                const rows: Analytics[] = Array.isArray(payload?.analytics) ? payload.analytics : [];
                const sorted = [...rows].sort((a, b) => (b.evaluatedAt || '').localeCompare(a.evaluatedAt || ''));
                this.analytics.set(sorted.slice(0, 5000));
                console.debug('[WS][INIT] State initialized', {
                    trades: this.trades().length,
                    positions: this.positions().length,
                    analytics: this.analytics().length,
                });
                break;
            }
            case 'portfolio': {
                this.portfolio.set((message as PortfolioMsg).payload ?? null);
                break;
            }
            case 'positions': {
                this.positions.set((message as PositionsMsg).payload ?? []);
                break;
            }
            case 'trades': {
                const rows = (message as TradeListMsg).payload ?? [];
                this.trades.set(rows);
                break;
            }
            case 'trade': {
                const row = (message as TradeMsg).payload as Trade;
                this.trades.update((existing) => [row, ...existing].slice(0, 200));
                break;
            }
            case 'analytics': {
                const payload = (message as AnalyticsMsg).payload;
                if (Array.isArray(payload)) {
                    const rows: Analytics[] = payload;
                    const sorted = [...rows].sort((a, b) => (b.evaluatedAt || '').localeCompare(a.evaluatedAt || ''));
                    this.analytics.set(sorted.slice(0, 5000));
                } else if (payload) {
                    const row = payload as Analytics;
                    this.analytics.update((previous) => {
                        const index = previous.findIndex((r) => r.id === row.id);
                        if (index >= 0) {
                            const copy = [...previous];
                            copy[index] = row;
                            return copy;
                        }
                        return [row, ...previous].slice(0, 5000);
                    });
                }
                break;
            }
            case 'pong':
                break;
            case 'error':
                console.debug('[WS][SERVER][ERROR]', (message as ErrorMsg).payload);
                break;
            default:
                console.debug('[WS][WARN] Unhandled message type:', (message as any).type);
                break;
        }
    }
}
