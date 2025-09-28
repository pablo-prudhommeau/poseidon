import {DatePipe, NgFor, NgIf} from '@angular/common';
import {HttpClient} from '@angular/common/http';
import {Component, OnInit, signal} from '@angular/core';
import {FormsModule} from '@angular/forms';
import {ApiService} from '../api.service';

type TradeItem = {
    id: string;
    symbol: string;
    chain: string;
    address: string;
    side?: string;
    price?: number;
    qty?: number;
    timestamp?: string | number;
    status?: string;
};

@Component({
    standalone: true,
    selector: 'app-tools',
    imports: [NgIf, NgFor, FormsModule, DatePipe],
    templateUrl: './tools.component.html'
})
export class ToolsComponent implements OnInit {
    readonly recentTrades = signal<TradeItem[]>([]);
    readonly isLoadingTrades = signal<boolean>(false);
    readonly tradesErrorMessage = signal<string>('');

    poolAddress = '';
    chainIdentifier = 'ETH';
    timeframe = '1m';
    startEpochMilliseconds = '';
    endEpochMilliseconds = '';

    constructor(private readonly http: HttpClient, private readonly apiService: ApiService) {}

    ngOnInit(): void {
        this.loadRecentTrades();
    }

    private loadRecentTrades(): void {
        this.isLoadingTrades.set(true);
        this.tradesErrorMessage.set('');
        console.info('[Tools] Fetching recent trades…');
        this.http.get<TradeItem[]>(`/api/trades?limit=100`).subscribe({
            next: trades => {
                console.info('[Tools] Recent trades received:', trades.length);
                console.debug('[Tools] First trade sample:', trades?.[0]);
                const sorted = (trades ?? []).slice().sort((a, b) => {
                    const at = typeof a.timestamp === 'string' ? Date.parse(a.timestamp) : Number(a.timestamp ?? 0);
                    const bt = typeof b.timestamp === 'string' ? Date.parse(b.timestamp) : Number(b.timestamp ?? 0);
                    return bt - at;
                });
                this.recentTrades.set(sorted);
            },
            error: err => {
                console.error('[Tools] Failed to fetch trades:', err);
                this.tradesErrorMessage.set('Failed to fetch recent trades.');
            },
            complete: () => this.isLoadingTrades.set(false)
        });
    }

    private downloadJson(data: unknown, fileName: string): void {
        const json = JSON.stringify(data, null, 2);
        const blob = new Blob([json], {type: 'application/json;charset=utf-8'});
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.download = fileName;
        link.href = url;
        link.click();
        URL.revokeObjectURL(url);
    }

    exportChartByTradeId(
        tradeId: string,
        minutesBefore: number = 720,
        minutesAfter: number = 720,
        timeframe: string = '1m'
    ): void {
        if (!tradeId) {
            alert('Missing trade id.');
            return;
        }
        console.info('[Tools] Exporting chart JSON for trade_id=', tradeId, {
            minutesBefore, minutesAfter, timeframe
        });

        this.apiService.exportChartByTrade(tradeId, minutesBefore, minutesAfter, timeframe)
            .subscribe({
                next: (payload) => {
                    const fileName = `${tradeId}_chart_${timeframe}.json`;
                    this.downloadJson(payload, fileName);
                    console.info('[Tools] Chart JSON downloaded:', fileName);
                },
                error: (err) => {
                    console.error('[Tools] Export chart by trade failed:', err);
                    alert('Export failed. See console for details.');
                }
            });
    }

    exportOhlcv(): void {
        if (!this.poolAddress || !this.chainIdentifier || !this.timeframe) {
            alert('Please fill address, chain and timeframe.');
            return;
        }

        const params: {
            address: string;
            chain: string;
            timeframe: string;
            start_ms?: string | number;
            end_ms?: string | number;
        } = {
            address: this.poolAddress.trim(),
            chain: this.chainIdentifier.trim(),
            timeframe: this.timeframe.trim()
        };
        if (this.startEpochMilliseconds) {
            params.start_ms = this.startEpochMilliseconds.trim();
        }
        if (this.endEpochMilliseconds) {
            params.end_ms = this.endEpochMilliseconds.trim();
        }

        console.info('[Tools] Exporting OHLCV', params);
        this.apiService.exportOhlcv(params).subscribe({
            next: (payload) => {
                const fileName = `ohlcv_${params.address}_${params.chain}_${params.timeframe}.json`;
                const json = JSON.stringify(payload, null, 2);
                const blob = new Blob([json], {type: 'application/json;charset=utf-8'});
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.download = fileName;
                link.href = url;
                link.click();
                URL.revokeObjectURL(url);
                console.info('[Tools] OHLCV JSON downloaded:', fileName);
            },
            error: (err) => {
                console.error('[Tools] Export OHLCV failed:', err);
                alert('Export failed. See console for details.');
            }
        });
    }
}
