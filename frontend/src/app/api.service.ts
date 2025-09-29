import {HttpClient} from '@angular/common/http';
import {inject, Injectable} from '@angular/core';
import {Portfolio, Position, Trade} from './core/models';
import {Status} from './core/websocket.service';

@Injectable({providedIn: 'root'})
export class ApiService {
    private http = inject(HttpClient);

    getStatus() { return this.http.get<Status>('/api/status'); }

    getPortfolio() { return this.http.get<Portfolio>('/api/portfolio'); }

    getPositions() { return this.http.get<Position[]>('/api/positions'); }

    getTrades(n = 100) { return this.http.get<Trade[]>(`/api/trades?limit=${n}`); }

    resetPaper() { return this.http.post<{ ok: boolean }>('/api/paper/reset', {}); }

}
