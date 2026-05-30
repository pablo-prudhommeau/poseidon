import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { map, Observable } from 'rxjs';
import {
    DcaOrderPayload,
    DcaOrdersResponse,
    DcaStrategiesResponse,
    DcaStrategyCreatePayload,
    DcaStrategyCreateResponse,
    DcaStrategyPayload,
    TradeMode,
    TradingAnalyticsResponse,
    TradingEvaluationPayload,
    TradingPaperResetPayload,
    TradingPositionPayload,
    TradingPositionsResponse
} from './core/models';

export interface AppStatus {
    mode: TradeMode;
    trading_enabled: boolean;
    dca_enabled: boolean;
    trading_interval_seconds: number;
    position_guard_interval_seconds: number;
    shadowing_enabled: boolean;
    aave_sentinel_enabled: boolean;
    trading_wallet_maintenance_enabled: boolean;
}

export interface AppStatusResponse {
    ok: boolean;
    status: AppStatus;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
    private http = inject(HttpClient);

    createDcaStrategy(payload: DcaStrategyCreatePayload): Observable<DcaStrategyCreateResponse> {
        return this.http.post<DcaStrategyCreateResponse>('/api/dca/strategies', payload);
    }

    getDcaOrders(strategyId: number): Observable<DcaOrderPayload[]> {
        return this.http.get<DcaOrdersResponse>(`/api/dca/strategies/${strategyId}/orders`).pipe(map((response) => response.orders));
    }

    getDcaStrategies(): Observable<DcaStrategyPayload[]> {
        return this.http.get<DcaStrategiesResponse>('/api/dca/strategies').pipe(map((response) => response.strategies));
    }

    getEvaluationById(evaluationId: number): Observable<TradingEvaluationPayload | null> {
        return this.http.get<TradingEvaluationPayload | null>(`/api/trading/evaluations/${evaluationId}`);
    }

    getOpenPositions(): Observable<TradingPositionPayload[]> {
        return this.http.get<TradingPositionsResponse>('/api/trading/positions').pipe(map((response) => response.positions));
    }

    getPositionByEvaluationId(evaluationId: number): Observable<TradingPositionPayload> {
        return this.http.get<TradingPositionPayload>(`/api/trading/positions/by-evaluation/${evaluationId}`);
    }

    getShadowTradesForPair(pairAddress: string): Observable<TradingEvaluationPayload[]> {
        return this.http.get<TradingEvaluationPayload[]>(`/api/trading/shadowing/evaluations/${pairAddress}`);
    }

    getStatus(): Observable<AppStatusResponse> {
        return this.http.get<AppStatusResponse>('/api/status');
    }

    getTradingAnalytics(realm: 'qualified' | 'shadow' = 'qualified'): Observable<TradingAnalyticsResponse> {
        if (realm === 'shadow') {
            return this.http.get<TradingAnalyticsResponse>('/api/trading/analytics/shadow');
        }
        return this.http.get<TradingAnalyticsResponse>('/api/trading/analytics');
    }

    resetPaper(): Observable<TradingPaperResetPayload> {
        return this.http.post<TradingPaperResetPayload>('/api/trading/paper/reset', {});
    }
}
