import { CommonModule } from '@angular/common';
import { Component, DestroyRef, ElementRef, ViewChild, computed, effect, inject, input, output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { ICellRendererParams } from 'ag-grid-community';
import { DialogModule } from 'primeng/dialog';

import { ApiService } from '../../../../api.service';
import { DefiIconsService } from '../../../../core/defi-icons.service';
import { TradingPositionPayload } from '../../../../core/models';
import { NumberFormattingService } from '../../../../core/number-formatting.service';
import { formatPositionExitReasonLabel } from '../../trading-position-exit-reason.utils';

export type StaledRecoverySubmitAction = 'kill' | 'reopen';

@Component({
    standalone: true,
    selector: 'trading-position-staled-recovery-dialog',
    imports: [CommonModule, DialogModule],
    templateUrl: './trading-position-staled-recovery-dialog.component.html',
    styleUrl: '../trading-position-closing-dialog/trading-position-closing-dialog.component.css'
})
export class TradingPositionStaledRecoveryDialogComponent {
    @ViewChild('symbolChipHost', { static: false }) private symbolChipHost?: ElementRef<HTMLElement>;

    public readonly livePositions = input<TradingPositionPayload[]>([]);
    public readonly positionId = input<number | null>(null);
    public readonly positionSnapshot = input<TradingPositionPayload | null>(null);
    public readonly livePosition = computed<TradingPositionPayload | null>(() => {
        const positionId = this.positionId();
        if (positionId === null) {
            return null;
        }
        const liveRow = this.livePositions().find((position) => position.id === positionId);
        return liveRow ?? this.positionSnapshot();
    });
    public readonly entryNotionalUsd = computed<number | null>(() => {
        const position = this.livePosition();
        if (!position) {
            return null;
        }
        const entryNotional = (position.open_quantity ?? 0) * (position.entry_price ?? 0);
        if (entryNotional <= 0) {
            return null;
        }
        return entryNotional;
    });
    private readonly numberFormattingService = inject(NumberFormattingService);
    public readonly entryNotionalLabel = computed<string>(() => {
        const entryNotional = this.entryNotionalUsd();
        if (entryNotional == null) {
            return '—';
        }
        return this.numberFormattingService.formatCurrency(entryNotional, 'USD', 2, 2);
    });
    public readonly submitAction = input<StaledRecoverySubmitAction | null>(null);
    public readonly isKillSubmitting = computed<boolean>(() => this.submitAction() === 'kill');
    public readonly isReopenSubmitting = computed<boolean>(() => this.submitAction() === 'reopen');

    public readonly killLossMetricClasses = computed<Record<string, boolean>>(() => ({
        'poseidon-grid-notional-live': true,
        'poseidon-grid-notional-live--negative': true,
        'poseidon-grid-emphasized-metric': true
    }));
    public readonly killLossPercentLabel = computed<string>(() => '-100%');
    public readonly killLossUsdLabel = computed<string>(() => {
        const entryNotional = this.entryNotionalUsd();
        if (entryNotional == null) {
            return '—';
        }
        return this.numberFormattingService.formatCurrency(-entryNotional, 'USD', 2, 2);
    });

    public readonly killSubmitFinished = output<{ positionId: number; success: boolean }>();

    public readonly killSubmitStarted = output<number>();

    public readonly reopenPhasePreview = computed<'OPEN' | 'PARTIAL'>(() => {
        const position = this.livePosition();
        if (!position) {
            return 'OPEN';
        }
        const openQuantity = position.open_quantity ?? 0;
        const currentQuantity = position.current_quantity ?? 0;
        if (currentQuantity >= openQuantity) {
            return 'OPEN';
        }
        return 'PARTIAL';
    });

    public readonly reopenPhasePillClasses = computed<Record<string, boolean>>(() => ({
        'poseidon-grid-pill--info': this.reopenPhasePreview() === 'OPEN',
        'poseidon-grid-pill--warn': this.reopenPhasePreview() === 'PARTIAL'
    }));

    public readonly reopenSubmitFinished = output<{ positionId: number; success: boolean }>();

    public readonly reopenSubmitStarted = output<number>();

    public readonly staledReasonLabel = computed<string>(() => formatPositionExitReasonLabel(this.livePosition()?.exit_reason));

    public readonly submitInProgress = computed<boolean>(() => this.submitAction() !== null);

    public readonly visible = input<boolean>(false);

    public readonly visibleChange = output<boolean>();
    private readonly apiService = inject(ApiService);
    private readonly defiIconsService = inject(DefiIconsService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly symbolChipEffect = effect(() => {
        if (!this.visible()) {
            return;
        }
        const position = this.livePosition();
        if (!position) {
            return;
        }
        queueMicrotask(() => this.renderSymbolChip(position));
    });

    public confirmKill(): void {
        const position = this.livePosition();
        if (!position || this.submitInProgress()) {
            return;
        }
        const positionId = position.id;
        this.killSubmitStarted.emit(positionId);
        this.apiService
            .killStaledPosition(positionId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.visibleChange.emit(false);
                    this.killSubmitFinished.emit({ positionId, success: true });
                },
                error: (error: HttpErrorResponse) => {
                    console.error('[UI][POSITIONS][KILL] Staled position kill failed', error);
                    this.killSubmitFinished.emit({ positionId, success: false });
                }
            });
    }

    public confirmReopen(): void {
        const position = this.livePosition();
        if (!position || this.submitInProgress()) {
            return;
        }
        const positionId = position.id;
        this.reopenSubmitStarted.emit(positionId);
        this.apiService
            .reopenStaledPosition(positionId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.visibleChange.emit(false);
                    this.reopenSubmitFinished.emit({ positionId, success: true });
                },
                error: (error: HttpErrorResponse) => {
                    console.error('[UI][POSITIONS][REOPEN] Staled position reopen failed', error);
                    this.reopenSubmitFinished.emit({ positionId, success: false });
                }
            });
    }

    public formatCompactQuantity(value: unknown): string {
        return this.numberFormattingService.formatQuantityHumanReadable(value) || '—';
    }

    public onDialogVisibleChange(nextVisible: boolean): void {
        this.visibleChange.emit(nextVisible);
    }

    public onDismiss(): void {
        if (this.submitInProgress()) {
            return;
        }
        this.visibleChange.emit(false);
    }

    private renderSymbolChip(position: TradingPositionPayload): void {
        const host = this.symbolChipHost?.nativeElement;
        if (!host) {
            return;
        }
        host.replaceChildren();
        const chipElement = this.defiIconsService.tokenChainChipRenderer({
            data: position,
            value: position.token_symbol
        } as ICellRendererParams);
        host.appendChild(chipElement);
    }
}
