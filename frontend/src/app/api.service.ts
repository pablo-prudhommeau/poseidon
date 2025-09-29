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

}
