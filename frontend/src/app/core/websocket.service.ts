import {Injectable, signal} from '@angular/core';
import {
    DcaStrategyPayload,
    ShadowVerdictChronicleDeltaPayload,
    ShadowVerdictChronicleResponse,
    TradingEvaluationPayload,
    TradingLiquidityPayload,
    TradingPortfolioPayload,
    TradingPositionPricePayload,
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
    /** Price ticks received before the positions snapshot is applied (initial sync / race). */
    private pendingPositionPriceUpdates: TradingPositionPricePayload[] = [];

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
                this.reconcilePositions(message.payload as TradingPositionPayload[]);
                break;
            }
            case WebsocketMessageType.POSITION_PRICES: {
                this.mergeIncomingPositionPrices(message.payload as TradingPositionPricePayload[]);
                break;
            }
            case WebsocketMessageType.TRADES: {
                this.reconcileTrades(message.payload as TradingTradePayload[]);
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

    private mergeIncomingPositionPrices(priceUpdates: TradingPositionPricePayload[]): void {
        if (!Array.isArray(priceUpdates) || priceUpdates.length === 0) {
            return;
        }
        const currentPositions = this.positions();
        if (!Array.isArray(currentPositions) || currentPositions.length === 0) {
            this.pendingPositionPriceUpdates.push(...priceUpdates);
            return;
        }
        this.applyPositionPriceUpdatesToRows(currentPositions, priceUpdates);
    }

    private flushPendingPositionPriceUpdates(): void {
        if (this.pendingPositionPriceUpdates.length === 0) {
            return;
        }
        const pending = this.pendingPositionPriceUpdates;
        this.pendingPositionPriceUpdates = [];
        const currentPositions = this.positions();
        if (!Array.isArray(currentPositions) || currentPositions.length === 0) {
            this.pendingPositionPriceUpdates.push(...pending);
            return;
        }
        this.applyPositionPriceUpdatesToRows(currentPositions, pending);
    }

    private applyPositionPriceUpdatesToRows(
        currentPositions: TradingPositionPayload[],
        rawUpdates: TradingPositionPricePayload[],
    ): void {
        if (rawUpdates.length === 0) {
            return;
        }

        const updateByPositionId = new Map<number, TradingPositionPricePayload>();
        const updateByPairAddress = new Map<string, TradingPositionPricePayload>();
        for (const update of rawUpdates) {
            const id = Number(update.position_id);
            if (Number.isFinite(id)) {
                updateByPositionId.set(id, update);
            }
            const pair = update.pair_address;
            if (pair) {
                updateByPairAddress.set(pair, update);
            }
        }

        let hasAnyChange = false;
        const nextPositions = currentPositions.map((position) => {
            const id = Number(position.id);
            const update =
                (Number.isFinite(id) ? updateByPositionId.get(id) : undefined)
                ?? (position.pair_address ? updateByPairAddress.get(position.pair_address) : undefined);
            if (!update) {
                return position;
            }

            const previousPrice = Number(position.last_price ?? 0);
            const nextPrice =
                update.last_price == null
                    ? position.last_price
                    : Number(update.last_price);
            const nextDeltaPercent =
                update.delta_percent == null
                    ? undefined
                    : Number(update.delta_percent);

            const nextDirection: 'up' | 'down' | null =
                update.last_price == null || !Number.isFinite(previousPrice) || !Number.isFinite(nextPrice)
                    ? null
                    : nextPrice > previousPrice
                        ? 'up'
                        : nextPrice < previousPrice
                            ? 'down'
                            : null;

            const didChange =
                nextPrice !== position.last_price
                || (nextDeltaPercent ?? null) !== ((position as any).priceChangePercent ?? null)
                || nextDirection !== ((position as any).lastPriceDirection ?? null);
            if (didChange) {
                hasAnyChange = true;
            }

            return {
                ...position,
                last_price: nextPrice,
                priceChangePercent: nextDeltaPercent ?? (position as any).priceChangePercent ?? null,
                lastPriceDirection: nextDirection,
            };
        });

        if (hasAnyChange) {
            this.positions.set(nextPositions);
        }
    }

    private reconcilePositions(nextPayload: TradingPositionPayload[]): void {
        if (!Array.isArray(nextPayload)) {
            return;
        }

        const currentPositions = this.positions();
        if (!Array.isArray(currentPositions) || currentPositions.length === 0) {
            this.positions.set(nextPayload);
            this.flushPendingPositionPriceUpdates();
            return;
        }

        const currentById = new Map<number, TradingPositionPayload>(
            currentPositions.map((position) => [position.id, position])
        );
        let hasAnyChange = nextPayload.length !== currentPositions.length;

        const reconciled = nextPayload.map((incomingPosition) => {
            const current = currentById.get(incomingPosition.id);
            if (!current) {
                hasAnyChange = true;
                return incomingPosition;
            }

            const direction = (current as any).lastPriceDirection ?? null;
            const changePct = (current as any).priceChangePercent ?? null;
            const mergedLastPrice =
                incomingPosition.last_price != null
                    ? incomingPosition.last_price
                    : current.last_price;
            const incomingWithUiState = {
                ...incomingPosition,
                last_price: mergedLastPrice,
                lastPriceDirection: direction,
                priceChangePercent: changePct,
            };

            if (this.positionsAreEquivalent(current, incomingWithUiState)) {
                return current;
            }

            hasAnyChange = true;
            return incomingWithUiState as TradingPositionPayload;
        });

        if (hasAnyChange) {
            this.positions.set(reconciled);
        }
        this.flushPendingPositionPriceUpdates();
    }

    private positionsAreEquivalent(left: TradingPositionPayload, right: TradingPositionPayload): boolean {
        return this.arePlainObjectsEquivalent(
            left as unknown as Record<string, unknown>,
            right as unknown as Record<string, unknown>
        );
    }

    private reconcileTrades(nextPayload: TradingTradePayload[]): void {
        if (!Array.isArray(nextPayload)) {
            return;
        }

        const currentTrades = this.trades();
        if (!Array.isArray(currentTrades) || currentTrades.length === 0) {
            this.trades.set(nextPayload);
            return;
        }

        const currentById = new Map<number, TradingTradePayload>(
            currentTrades.map((trade) => [trade.id, trade])
        );
        let hasAnyChange = nextPayload.length !== currentTrades.length;

        const reconciled = nextPayload.map((incomingTrade) => {
            const current = currentById.get(incomingTrade.id);
            if (!current) {
                hasAnyChange = true;
                return incomingTrade;
            }

            if (this.tradesAreEquivalent(current, incomingTrade)) {
                return current;
            }

            hasAnyChange = true;
            return incomingTrade;
        });

        if (hasAnyChange) {
            this.trades.set(reconciled);
        }
    }

    private tradesAreEquivalent(left: TradingTradePayload, right: TradingTradePayload): boolean {
        return this.arePlainObjectsEquivalent(
            left as unknown as Record<string, unknown>,
            right as unknown as Record<string, unknown>
        );
    }

    private arePlainObjectsEquivalent(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
        if (left === right) {
            return true;
        }

        const leftKeys = Object.keys(left);
        const rightKeys = Object.keys(right);
        if (leftKeys.length !== rightKeys.length) {
            return false;
        }

        for (const key of leftKeys) {
            if (!(key in right)) {
                return false;
            }
            if (!Object.is(left[key], right[key])) {
                return false;
            }
        }
        return true;
    }
}