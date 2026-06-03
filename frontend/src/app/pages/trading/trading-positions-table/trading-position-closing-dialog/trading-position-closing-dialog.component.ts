import { CommonModule } from '@angular/common';
import { Component, DestroyRef, ElementRef, ViewChild, computed, effect, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { ICellRendererParams } from 'ag-grid-community';
import { DialogModule } from 'primeng/dialog';

import { ApiService } from '../../../../api.service';
import { DefiIconsService } from '../../../../core/defi-icons.service';
import { TradingPositionPayload } from '../../../../core/models';
import { NumberFormattingService } from '../../../../core/number-formatting.service';
import { positionPhasePillNgClasses } from '../../trading-position-phase-pill.utils';
import {
    computeTradingPositionDeltaPercent,
    formatDeltaPercentLabel,
    remainingTradingPositionNotionalUsd,
    resolveDeltaTickVariant,
    type DeltaTickVariant
} from '../../trading-position-grid-metrics';

@Component({
    standalone: true,
    selector: 'trading-position-closing-dialog',
    imports: [CommonModule, DialogModule],
    templateUrl: './trading-position-closing-dialog.component.html',
    styleUrl: './trading-position-closing-dialog.component.css'
})
export class TradingPositionClosingDialogComponent {
    @ViewChild('symbolChipHost', { static: false }) private symbolChipHost?: ElementRef<HTMLElement>;

    public readonly closeSubmitFinished = output<{ positionId: number; success: boolean }>();
    public readonly closeSubmitStarted = output<number>();
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
    private readonly numberFormattingService = inject(NumberFormattingService);
    public readonly deltaPercentValue = computed<number | null>(() => computeTradingPositionDeltaPercent(this.livePosition(), this.numberFormattingService));

    public readonly deltaPercentLabel = computed<string>(() => formatDeltaPercentLabel(this.deltaPercentValue(), this.numberFormattingService));
    public readonly deltaTickPulseKey = computed<string>(() => {
        const position = this.livePosition();
        if (!position) {
            return 'idle';
        }
        return `${position.last_price ?? ''}:${this.deltaPercentValue() ?? ''}`;
    });
    public readonly deltaTickVariant = computed<DeltaTickVariant>(() => resolveDeltaTickVariant(this.deltaPercentValue()));
    public readonly liveNotionalLabel = computed<string>(() => {
        const value = remainingTradingPositionNotionalUsd(this.livePosition(), 'last', this.numberFormattingService);
        if (value == null) {
            return '—';
        }
        return this.numberFormattingService.formatCurrency(value, 'USD', 2, 2);
    });

    public readonly visible = input<boolean>(false);

    private readonly metricsRefreshedAt = signal<number>(Date.now());

    private readonly nowMilliseconds = signal<number>(Date.now());

    public readonly refreshAgeNumeric = computed<string>(() => {
        if (!this.visible()) {
            return '--';
        }
        const refreshedAt = this.metricsRefreshedAt();
        const elapsedSeconds = Math.max(0, Math.floor((this.nowMilliseconds() - refreshedAt) / 1000));
        if (elapsedSeconds < 2) {
            return 'now';
        }
        if (elapsedSeconds < 60) {
            return `${elapsedSeconds}s`;
        }
        return `${Math.floor(elapsedSeconds / 60)}m`;
    });

    public readonly submitInProgress = input<boolean>(false);

    public readonly unrealizedPnlUsdValue = computed<number | null>(() => {
        const position = this.livePosition();
        if (!position) {
            return null;
        }
        const liveNotional = remainingTradingPositionNotionalUsd(position, 'last', this.numberFormattingService);
        const costBasis = remainingTradingPositionNotionalUsd(position, 'entry', this.numberFormattingService);
        if (liveNotional == null || costBasis == null) {
            return null;
        }
        return liveNotional - costBasis;
    });

    public readonly unrealizedPnlUsdLabel = computed<string>(() => {
        const value = this.unrealizedPnlUsdValue();
        if (value == null) {
            return '—';
        }
        return this.numberFormattingService.formatCurrency(value, 'USD', 2, 2);
    });

    public readonly visibleChange = output<boolean>();
    private readonly apiService = inject(ApiService);
    private readonly defiIconsService = inject(DefiIconsService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly dialogOpenEffect = effect(() => {
        if (this.visible()) {
            this.metricsRefreshedAt.set(Date.now());
        }
    });

    private readonly liveMetricsSyncEffect = effect(() => {
        if (!this.visible()) {
            return;
        }
        const position = this.livePosition();
        if (!position) {
            return;
        }
        if (this.liveMetricsFingerprint(position)) {
            this.metricsRefreshedAt.set(Date.now());
        }
    });

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

    constructor() {
        const relativeTimeTickInterval = window.setInterval(() => this.nowMilliseconds.set(Date.now()), 1000);
        this.destroyRef.onDestroy(() => window.clearInterval(relativeTimeTickInterval));
    }

    public closingPreviewClasses(): Record<string, boolean> {
        const pillClass = this.resolveClosingPreviewPillClass(this.livePosition());
        return { [pillClass]: true };
    }

    public confirmClose(): void {
        const position = this.livePosition();
        if (!position || this.submitInProgress()) {
            return;
        }

        const positionId = position.id;
        this.closeSubmitStarted.emit(positionId);

        this.apiService
            .closePosition(positionId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.visibleChange.emit(false);
                    this.closeSubmitFinished.emit({ positionId, success: true });
                },
                error: (error: HttpErrorResponse) => {
                    console.error('[UI][POSITIONS][CLOSE] Manual close failed', error);
                    this.closeSubmitFinished.emit({ positionId, success: false });
                }
            });
    }

    public currentPhaseClasses(): Record<string, boolean> {
        return this.phaseClassesForPosition(this.livePosition());
    }

    public formatCompactQuantity(value: unknown): string {
        return this.numberFormattingService.formatQuantityHumanReadable(value) || '—';
    }

    public formatCompactUsd(value: unknown): string {
        return this.numberFormattingService.formatUsdCompactForGrid(value) || '—';
    }

    public formatCurrency(value: unknown, code: string, min: number, max: number): string {
        return this.numberFormattingService.formatCurrency(value as number, code, min, max);
    }

    public liveNotionalMetricClasses(): Record<string, boolean> {
        const delta = this.deltaPercentValue() ?? 0;
        return {
            'poseidon-grid-notional-live': true,
            'poseidon-grid-notional-live--positive': delta > 0,
            'poseidon-grid-notional-live--negative': delta < 0,
            'poseidon-grid-notional-live--neutral': delta === 0,
            'poseidon-grid-emphasized-metric': true
        };
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

    public pnlUsdMetricClasses(): Record<string, boolean> {
        const pnlUsd = this.unrealizedPnlUsdValue() ?? 0;
        return {
            'poseidon-grid-notional-live': true,
            'poseidon-grid-notional-live--positive': pnlUsd > 0,
            'poseidon-grid-notional-live--negative': pnlUsd < 0,
            'poseidon-grid-notional-live--neutral': pnlUsd === 0,
            'poseidon-grid-emphasized-metric': true
        };
    }

    public remainingCostBasisUsd(row: TradingPositionPayload | null): number | null {
        return remainingTradingPositionNotionalUsd(row, 'entry', this.numberFormattingService);
    }

    private liveMetricsFingerprint(position: TradingPositionPayload): string {
        return [position.current_quantity, position.last_price, position.updated_at, position.position_phase].join('\u0000');
    }

    private phaseClassesForPosition(position: TradingPositionPayload | null | undefined): Record<string, boolean> {
        const phase = position?.position_phase;
        return positionPhasePillNgClasses(phase, {
            closingPreviewClass: phase === 'CLOSING' ? this.resolveClosingPreviewPillClass(position) : undefined
        });
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

    private resolveClosingPreviewPillClass(position: TradingPositionPayload | null | undefined): string {
        const delta = computeTradingPositionDeltaPercent(position ?? null, this.numberFormattingService) ?? 0;
        return delta < 0 ? 'poseidon-grid-pill--closing-negative' : 'poseidon-grid-pill--closing-positive';
    }
}
