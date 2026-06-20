import { CommonModule } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { ApiService, AppStatusResponse } from '../../api.service';
import { TradeMode } from '../../core/models';
import { WebSocketService } from '../../core/websocket.service';

@Component({
    standalone: true,
    selector: 'app-paper-mode-control',
    imports: [CommonModule],
    templateUrl: 'paper-mode-control.component.html',
    styleUrl: 'paper-mode-control.component.css'
})
export class PaperModeControlComponent implements OnInit {
    public readonly isApplicationInitialLoading = signal<boolean>(true);

    private readonly webSocketService = inject(WebSocketService);

    public readonly isModeResolved = computed<boolean>(() => this.webSocketService.paperTradingModeActive() !== null || !this.isApplicationInitialLoading());

    private readonly statusTradingMode = signal<TradeMode | null>(null);

    public readonly isPaperTradingModeActive = computed<boolean>(() => {
        const websocketPaperTradingMode = this.webSocketService.paperTradingModeActive();
        if (websocketPaperTradingMode !== null) {
            return websocketPaperTradingMode;
        }
        return this.statusTradingMode() === 'PAPER';
    });
    private readonly apiService = inject(ApiService);

    public ngOnInit(): void {
        this.fetchApplicationStatus();
    }

    private fetchApplicationStatus(): void {
        this.apiService.getStatus().subscribe({
            next: (response: AppStatusResponse) => {
                this.statusTradingMode.set(response.status.mode);
                this.isApplicationInitialLoading.set(false);
            },
            error: (error: unknown) => {
                this.isApplicationInitialLoading.set(false);
                console.error('Failed to synchronize application status', error);
            }
        });
    }
}
