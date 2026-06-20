import { inject, Injectable, signal } from '@angular/core';
import { ApiService } from '../../api.service';
import { WebSocketService } from '../../core/websocket.service';

@Injectable({ providedIn: 'root' })
export class PaperResetService {
    public readonly isResetInProgress = signal<boolean>(false);

    private readonly apiService = inject(ApiService);
    private readonly webSocketService = inject(WebSocketService);

    public resetPaperPortfolio(): void {
        if (this.isResetInProgress()) {
            return;
        }
        this.isResetInProgress.set(true);

        this.apiService.resetPaper().subscribe({
            next: () => {
                this.webSocketService.requestCachedStateRefresh();
                this.isResetInProgress.set(false);
                console.info('Paper portfolio has been successfully reset');
            },
            error: (error: unknown) => {
                this.isResetInProgress.set(false);
                console.error('An error occurred during paper portfolio reset', error);
            }
        });
    }
}
