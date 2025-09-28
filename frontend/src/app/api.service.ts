import {HttpClient} from '@angular/common/http';
import {inject, Injectable} from '@angular/core';
import {Observable, switchMap, timer} from 'rxjs';
import {Portfolio, Position, Trade} from './model';

@Injectable({providedIn: 'root'})
export class ApiService {
    private http = inject(HttpClient);

    getStatus() { return this.http.get<{ mode: string; web3_ok: boolean; interval: number }>('/api/status'); }

    getPortfolio() { return this.http.get<Portfolio>('/api/portfolio'); }

    getPositions() { return this.http.get<Position[]>('/api/positions'); }

    getTrades(n = 100) { return this.http.get<Trade[]>(`/api/trades?limit=${n}`); }

    resetPaper() { return this.http.post<{ ok: boolean }>('/api/paper/reset', {}); }

    // Polling simple
    pollPortfolio(ms = 6000): Observable<Portfolio> { return timer(0, ms).pipe(switchMap(() => this.getPortfolio())); }

    pollPositions(ms = 6000): Observable<Position[]> { return timer(0, ms).pipe(switchMap(() => this.getPositions())); }

    pollTrades(ms = 8000): Observable<Trade[]> { return timer(0, ms).pipe(switchMap(() => this.getTrades(100))); }

    exportChartByTrade(tradeId: string, minutesBefore = 720, minutesAfter = 720, timeframe = '1m') {
        const url = `/export/chart/${encodeURIComponent(tradeId)}?minutes_before=${minutesBefore}&minutes_after=${minutesAfter}&timeframe=${encodeURIComponent(timeframe)}`;
        return this.http.get(url);
    }

    exportOhlcv(params: { address: string; chain: string; timeframe: string; start_ms?: string | number; end_ms?: string | number; }) {
        const qp = new URLSearchParams({
            address: params.address,
            chain: params.chain,
            timeframe: params.timeframe
        });
        if (params.start_ms != null) {
            qp.set('start_ms', String(params.start_ms));
        }
        if (params.end_ms != null) {
            qp.set('end_ms', String(params.end_ms));
        }
        return this.http.get(`/ohlcv?${qp.toString()}`);
    }

}
