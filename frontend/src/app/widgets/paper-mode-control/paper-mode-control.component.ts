import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { ApiService, AppStatusResponse } from '../../api.service';
import { TradeMode } from '../../core/models';
import { WebSocketService } from '../../core/websocket.service';

@Component({
    standalone: true,
    selector: 'app-paper-mode-control',
    imports: [CommonModule],
    templateUrl: 'paper-mode-control.component.html'
})
export class PaperModeControlComponent implements OnInit {
    public readonly isApplicationInitialLoading = signal<boolean>(true);

    private readonly tradingMode = signal<TradeMode>('LIVE');

    public readonly isPaperTradingModeActive = computed(() => {
        return this.tradingMode() === 'PAPER';
    });

    public readonly isPortfolioResetInProgress = signal<boolean>(false);

    private readonly apiService = inject(ApiService);
    private readonly webSocketService = inject(WebSocketService);

    public ngOnInit(): void {
        this.fetchApplicationStatus();
    }

    public resetPaperPortfolioToInitialState(): void {
        this.isPortfolioResetInProgress.set(true);

        this.apiService.resetPaper().subscribe({
            next: () => {
                this.notifyWebSocketRefresh();
                this.isPortfolioResetInProgress.set(false);
                console.info('Paper portfolio has been successfully reset');
            },
            error: (error: unknown) => {
                this.isPortfolioResetInProgress.set(false);
                console.error('An error occurred during paper portfolio reset', error);
            }
        });
    }

    private fetchApplicationStatus(): void {
        this.apiService.getStatus().subscribe({
            next: (response: AppStatusResponse) => {
                this.tradingMode.set(response.status.mode);
                this.isApplicationInitialLoading.set(false);
            },
            error: (error: unknown) => {
                this.isApplicationInitialLoading.set(false);
                console.error('Failed to synchronize application status', error);
            }
        });
    }

    private notifyWebSocketRefresh(): void {
        const socketReference = (this.webSocketService as any)['socket'];

        if (socketReference && socketReference.readyState === WebSocket.OPEN) {
            socketReference.send(JSON.stringify({ type: 'refresh' }));
            return;
        }
        console.debug('[WEBSOCKET][REFRESH] Refresh skipped because websocket is not open');
    }
}
