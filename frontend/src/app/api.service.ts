import {HttpClient} from '@angular/common/http';
import {inject, Injectable} from '@angular/core';
import {map, Observable} from 'rxjs';
import {Analytics, CreateDcaPayload, DcaOrder, DcaStrategy, Position, TradeMode} from './core/models';

export interface AppStatus {
    mode: TradeMode;
    interval: number;
    prices_interval: number;
}

export interface AppStatusResponse {
    ok: boolean;
    status: AppStatus;
}

interface AnalyticsResponse {analytics: Analytics[];}

interface PositionsResponse {positions: Position[];}

interface DcaStrategiesResponse {strategies: DcaStrategy[];}

interface DcaOrdersResponse {orders: DcaOrder[];}

@Injectable({providedIn: 'root'})
export class ApiService {
    private http = inject(HttpClient);

    getStatus(): Observable<AppStatusResponse> {
        return this.http.get<AppStatusResponse>('/api/status');
    }

    resetPaper(): Observable<{ ok: boolean }> {
        return this.http.post<{ ok: boolean }>('/api/paper/reset', {});
    }

    getAnalytics(): Observable<Analytics[]> {
        return this.http
            .get<AnalyticsResponse>('/api/analytics')
            .pipe(map(response => response.analytics));
    }

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