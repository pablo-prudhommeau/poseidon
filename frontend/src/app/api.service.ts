import {HttpClient} from '@angular/common/http';
import {inject, Injectable} from '@angular/core';
import {map, Observable} from 'rxjs';
import {Analytics, CreateDcaPayload, DcaOrder, DcaStrategy, Position, TradeMode} from './core/models';

/** Backend application status payload. */
export interface AppStatus {
    mode: TradeMode;
    interval: number;
    prices_interval: number;
}

export interface AppStatusResponse {
    ok: boolean;
    status: AppStatus;
}

/** Response shape for /api/analytics. */
interface AnalyticsResponse {analytics: Analytics[];}

/** Response shape for /api/positions. */
interface PositionsResponse {positions: Position[];}

/** Response shape for /api/dca/strategies. */
interface DcaStrategiesResponse {strategies: DcaStrategy[];}

/** Response shape for /api/dca/strategies/{id}/orders. */
interface DcaOrdersResponse {orders: DcaOrder[];}

@Injectable({providedIn: 'root'})
export class ApiService {
    private http = inject(HttpClient);

    /** Fetch orchestrator status and heartbeat. */
    getStatus(): Observable<AppStatusResponse> {
        return this.http.get<AppStatusResponse>('/api/status');
    }

    /** Reset paper mode state (server side). */
    resetPaper(): Observable<{ ok: boolean }> {
        return this.http.post<{ ok: boolean }>('/api/paper/reset', {});
    }

    /** Fetch recent analytics rows via HTTP (replaces WS stream for analytics). */
    getAnalytics(): Observable<Analytics[]> {
        return this.http
            .get<AnalyticsResponse>('/api/analytics')
            .pipe(map(response => response.analytics));
    }

    /** Fetch open positions merged with latest prices via HTTP (replaces WS stream for positions). */
    getOpenPositions(): Observable<Position[]> {
        return this.http
            .get<PositionsResponse>('/api/positions')
            .pipe(map(response => response.positions));
    }

    createDcaStrategy(payload: CreateDcaPayload): Observable<{ message: string; strategy_id: number; orders_count: number }> {
        return this.http.post<{ message: string; strategy_id: number; orders_count: number }>('/api/dca/strategies', payload);
    }

    getDcaStrategies(): Observable<DcaStrategy[]> {
        return this.http
            .get<DcaStrategiesResponse>('/api/dca/strategies')
            .pipe(map(response => response.strategies));
    }

    getDcaOrders(strategyId: number): Observable<DcaOrder[]> {
        return this.http
            .get<DcaOrdersResponse>(`/api/dca/strategies/${strategyId}/orders`)
            .pipe(map(response => response.orders));
    }
}