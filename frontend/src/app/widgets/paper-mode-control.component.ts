import {CommonModule} from '@angular/common';
import {Component, computed, OnInit, signal} from '@angular/core';
import {ApiService, AppStatusResponse} from '../api.service';
import {TradeMode} from '../core/models';
import {WebSocketService} from '../core/websocket.service';

@Component({
    standalone: true,
    selector: 'app-paper-mode-control',
    imports: [CommonModule],
    templateUrl: 'paper-mode-control.component.html'
})
export class PaperModeControlComponent implements OnInit {

    private readonly mode = signal<TradeMode>('LIVE');
    public readonly isPaperMode = computed(() => this.mode() === 'PAPER');

    public readonly isLoading = signal<boolean>(true);
    public readonly isResetting = signal<boolean>(false);

    constructor(
        private readonly api: ApiService,
        private readonly webSocketService: WebSocketService
    ) {}

    ngOnInit(): void {
        console.info('poseidon.ui.paper-mode-control — fetching app status…');
        this.api.getStatus().subscribe({
            next: (response: AppStatusResponse) => {
                this.mode.set(response.status.mode);
                this.isLoading.set(false);
                console.debug('poseidon.ui.paper-mode-control — status received', response.status);
            },
            error: (error) => {
                this.isLoading.set(false);
                console.error('poseidon.ui.paper-mode-control — failed to get status', error);
            }
        });
    }

    /**
     * Reset the paper portfolio to $10,000 with a confirmation guard.
     */
    public resetPaperPortfolio(): void {
        this.isResetting.set(true);
        this.api.resetPaper().subscribe({
            next: () => {
                (this.webSocketService as any)['socket']?.send(JSON.stringify({type: 'refresh'}));
                this.isResetting.set(false);
            },
            error: (error) => {
                this.isResetting.set(false);
            }
        });
    }
}
