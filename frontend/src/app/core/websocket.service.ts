import {Injectable, signal} from '@angular/core';
import {
    TradingEvaluationPayload,
    DcaStrategyPayload,
    TradingPortfolioPayload,
    TradingPositionPayload,
    TradingTradePayload,
    WebsocketMessageType,
    WebsocketMessageUnion
} from './models';

export type WebsocketConnectionStatus = 'connecting' | 'open' | 'closed';

@Injectable({providedIn: 'root'})
export class WebSocketService {
    private socket?: WebSocket;

    public readonly status = signal<WebsocketConnectionStatus>('closed');
    public readonly portfolio = signal<TradingPortfolioPayload | null>(null);
    public readonly positions = signal<TradingPositionPayload[]>([]);
    public readonly trades = signal<TradingTradePayload[]>([]);
    public readonly analytics = signal<TradingEvaluationPayload[]>([]);
    public readonly dcaStrategies = signal<DcaStrategyPayload[]>([]);

    private defaultWebsocketUrl(): string {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${location.host}/ws`;
    }

    public connect(url = this.defaultWebsocketUrl()): void {
        if (this.socket && (this.socket.readyState === WebSocket.CONNECTING || this.socket.readyState === WebSocket.OPEN)) {
            return;
        }

        this.status.set('connecting');
        const socket = new WebSocket(url);
        this.socket = socket;

        socket.onopen = () => {
            this.status.set('open');
            console.info('[WEBSOCKET][CONNECTION][OPEN] WebSocket connection established');
        };

        socket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data) as WebsocketMessageUnion;
                this.apply(message);
            } catch {
                console.debug('[WEBSOCKET][MESSAGE][ERROR] Invalid WebSocket message payload received', event.data);
            }
        };

        socket.onerror = () => {
            this.status.set('closed');
            console.debug('[WEBSOCKET][CONNECTION][ERROR] WebSocket socket error encountered');
        };

        socket.onclose = () => {
            this.status.set('closed');
            this.socket = undefined;
            console.info('[WEBSOCKET][CONNECTION][CLOSE] Socket closed — attempting reconnection in 3 seconds');
            setTimeout(() => this.connect(url), 3000);
        };
    }

    private apply(message: WebsocketMessageUnion): void {
        switch (message.type) {
            case WebsocketMessageType.INITIALIZATION: {
                console.info('[WEBSOCKET][MESSAGE][INITIALIZATION] Handshake received. System ready for data streaming.');
                break;
            }
            case WebsocketMessageType.PORTFOLIO: {
                this.portfolio.set(message.payload);
                break;
            }
            case WebsocketMessageType.POSITIONS: {
                this.positions.set(message.payload);
                break;
            }
            case WebsocketMessageType.TRADES: {
                this.trades.set(message.payload);
                break;
            }
            case WebsocketMessageType.TRADE: {
                const incomingTrade = message.payload;
                this.trades.update((existingTrades) => [incomingTrade, ...existingTrades].slice(0, 200));
                break;
            }
            case WebsocketMessageType.ANALYTICS: {
                const incomingPayload = message.payload;
                if (Array.isArray(incomingPayload)) {
                    const sortedAnalytics = [...incomingPayload].sort((a, b) => (b.evaluated_at || '').localeCompare(a.evaluated_at || ''));
                    this.analytics.set(sortedAnalytics.slice(0, 5000));
                } else {
                    const incomingAnalyticsCycle = incomingPayload;
                    this.analytics.update((existingAnalytics) => {
                        const existingRecordIndex = existingAnalytics.findIndex((record) => record.id === incomingAnalyticsCycle.id);
                        if (existingRecordIndex >= 0) {
                            const updatedAnalytics = [...existingAnalytics];
                            updatedAnalytics[existingRecordIndex] = incomingAnalyticsCycle;
                            return updatedAnalytics;
                        }
                        return [incomingAnalyticsCycle, ...existingAnalytics].slice(0, 5000);
                    });
                }
                break;
            }
            case WebsocketMessageType.DCA_STRATEGIES: {
                this.dcaStrategies.set(message.payload);
                break;
            }
            case WebsocketMessageType.PONG:
                console.debug('[WEBSOCKET][MESSAGE][PONG] Heartbeat acknowledged by server');
                break;
            case WebsocketMessageType.ERROR:
                console.error('[WEBSOCKET][MESSAGE][ERROR] Server-side error reported:', message.payload);
                break;
            default:
                console.warn('[WEBSOCKET][MESSAGE][WARN] Unhandled message type received:', (message as any).type);
                break;
        }
    }
}