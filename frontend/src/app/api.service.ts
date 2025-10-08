import {HttpClient} from '@angular/common/http';
import {inject, Injectable} from '@angular/core';
import {TradeMode} from './core/models';

export interface AppStatus {
    mode: TradeMode;
    interval: number;
    prices_interval: number;
}

export interface AppStatusResponse {
    ok: boolean;
    status: AppStatus;
}

@Injectable({providedIn: 'root'})
export class ApiService {
    private http = inject(HttpClient);

    getStatus() { return this.http.get<AppStatusResponse>('/api/status'); }

    resetPaper() { return this.http.post<{ ok: boolean }>('/api/paper/reset', {}); }

}
