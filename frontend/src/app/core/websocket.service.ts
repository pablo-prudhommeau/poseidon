import {Injectable, signal} from '@angular/core';
import {
    DcaStrategyPayload,
    ShadowVerdictChronicleDeltaPayload,
    ShadowVerdictChronicleResponse,
    TradingEvaluationPayload,
    TradingLiquidityPayload,
    TradingPortfolioPayload,
    TradingPositionPayload,
    TradingShadowMetaPayload,
    TradingTradePayload,
    WebsocketMessageType,
    WebsocketMessageUnion
} from './models';
import {ShadowVerdictChronicleMergeService} from '../pages/trading/shadow-verdict-chronicle/services/shadow-verdict-chronicle-merge.service';

export type WebsocketConnectionStatus = 'connecting' | 'open' | 'closed';

@Injectable({providedIn: 'root'})
export class WebSocketService {
    private socket?: WebSocket;

    constructor(private readonly shadowHistoryMerge: ShadowVerdictChronicleMergeService) {}

    public readonly status = signal<WebsocketConnectionStatus>('closed');
    public readonly portfolio = signal<TradingPortfolioPayload | null>(null);
    public readonly liquidity = signal<TradingLiquidityPayload | null>(null);
    public readonly shadowMeta = signal<TradingShadowMetaPayload | null>(null);
    public readonly positions = signal<TradingPositionPayload[]>([]);
    public readonly trades = signal<TradingTradePayload[]>([]);
    public readonly analytics = signal<TradingEvaluationPayload[]>([]);
    public readonly dcaStrategies = signal<DcaStrategyPayload[]>([]);
    public readonly shadowHistory = signal<ShadowVerdictChronicleResponse | null>(null);

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
        };

        socket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data) as WebsocketMessageUnion;
                this.apply(message);
            } catch {
            }
        };

        socket.onerror = () => {
            this.status.set('closed');
        };

        socket.onclose = () => {
            this.status.set('closed');
            this.socket = undefined;
            setTimeout(() => this.connect(url), 3000);
        };
    }

    public requestCachedStateRefresh(): void {
        if (this.socket?.readyState !== WebSocket.OPEN) {
            return;
        }
        this.socket.send(JSON.stringify({type: WebsocketMessageType.REFRESH}));
    }

    private apply(message: WebsocketMessageUnion): void {
        switch (message.type) {
            case WebsocketMessageType.INITIALIZATION: {
                break;
            }
            case WebsocketMessageType.PORTFOLIO: {
                this.portfolio.set(message.payload);
                break;
            }
            case WebsocketMessageType.LIQUIDITY: {
                this.liquidity.set(message.payload);
                break;
            }
            case WebsocketMessageType.SHADOW_META: {
                this.shadowMeta.set(message.payload);
                break;
            }
            case WebsocketMessageType.SHADOW_VERDICT_CHRONICLE: {
                this.shadowHistory.set(message.payload);
                break;
            }
            case WebsocketMessageType.SHADOW_VERDICT_CHRONICLE_DELTA: {
                const baseline = this.shadowHistory();
                const patch = message.payload as ShadowVerdictChronicleDeltaPayload;
                if (!baseline) {
                    this.requestCachedStateRefresh();
                    break;
                }
                this.shadowHistory.set(this.shadowHistoryMerge.mergeShadowVerdictChronicleDelta(baseline, patch));
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
            case WebsocketMessageType.DCA_STRATEGIES: {
                this.dcaStrategies.set(message.payload);
                break;
            }
            case WebsocketMessageType.PONG:
                break;
            case WebsocketMessageType.ERROR:
                break;
            default:
                break;
        }
    }
}