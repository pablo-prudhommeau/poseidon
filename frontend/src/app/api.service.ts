import {HttpClient} from '@angular/common/http';
import {inject, Injectable} from '@angular/core';
import {map, Observable} from 'rxjs';
import {
    AnalyticsResponse,
    DcaOrderPayload,
    DcaOrdersResponse,
    DcaStrategiesResponse,
    DcaStrategyCreatePayload,
    DcaStrategyCreateResponse,
    DcaStrategyPayload,
    TradeMode,
    TradingEvaluationPayload,
    TradingPaperResetPayload,
    TradingPositionPayload,
    TradingPositionsResponse
} from './core/models';

export interface AppStatus {
    mode: TradeMode;
    interval: number;
    display_broadcast_interval: number;
}

export interface AppStatusResponse {
    ok: boolean;
    status: AppStatus;
}

@Injectable({providedIn: 'root'})
export class ApiService {
    private http = inject(HttpClient);

    getStatus(): Observable<AppStatusResponse> {
        return this.http.get<AppStatusResponse>('/api/status');
    }

    resetPaper(): Observable<TradingPaperResetPayload> {
        return this.http.post<TradingPaperResetPayload>('/api/paper/reset', {});
    }

    getAnalytics(realm: 'qualified' | 'shadow' = 'qualified'): Observable<AnalyticsResponse> {
        if (realm === 'shadow') {
            return this.http.get<AnalyticsResponse>('/api/analytics/shadow');
        }
        return this.http.get<AnalyticsResponse>('/api/analytics');
    }

    getEvaluationById(evaluationId: number): Observable<TradingEvaluationPayload | null> {
        return this.http.get<TradingEvaluationPayload | null>(`/api/analytics/evaluation/${evaluationId}`);
    }

    getShadowTradesForPair(pairAddress: string): Observable<TradingEvaluationPayload[]> {
        return this.http.get<TradingEvaluationPayload[]>(`/api/analytics/shadow/${pairAddress}`);
    }

    getOpenPositions(): Observable<TradingPositionPayload[]> {
        return this.http
            .get<TradingPositionsResponse>('/api/positions')
            .pipe(map(response => response.positions));
    }

    createDcaStrategy(payload: DcaStrategyCreatePayload): Observable<DcaStrategyCreateResponse> {
        return this.http.post<DcaStrategyCreateResponse>('/api/dca/strategies', payload);
    }

    getDcaStrategies(): Observable<DcaStrategyPayload[]> {
        return this.http
            .get<DcaStrategiesResponse>('/api/dca/strategies')
            .pipe(map(response => response.strategies));
    }

    getDcaOrders(strategyId: number): Observable<DcaOrderPayload[]> {
        return this.http
            .get<DcaOrdersResponse>(`/api/dca/strategies/${strategyId}/orders`)
            .pipe(map(response => response.orders));
    }
}