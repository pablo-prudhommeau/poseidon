import { CommonModule, DatePipe } from '@angular/common';
import { AfterViewInit, Component, computed, DestroyRef, effect, inject, signal, TemplateRef, ViewChild } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import {
    ColDef,
    GetRowIdParams,
    GridApi,
    GridReadyEvent,
    ICellRendererParams,
    ITooltipParams,
    ValueFormatterParams,
    ValueGetterParams
} from 'ag-grid-community';
import { NgApexchartsModule } from 'ng-apexcharts';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { DividerModule } from 'primeng/divider';
import { PanelModule } from 'primeng/panel';
import { ScrollPanelModule } from 'primeng/scrollpanel';
import { SkeletonModule } from 'primeng/skeleton';
import { TabsModule } from 'primeng/tabs';
import { TagModule } from 'primeng/tag';
import { TooltipModule } from 'primeng/tooltip';

import { balhamDarkThemeCompact } from '../../../ag-grid.theme';
import { ApiService } from '../../../api.service';
import { DatetimeDisplayService } from '../../../core/datetime-display.service';
import { DefiIconsService } from '../../../core/defi-icons.service';
import {
    TradingEvaluationPayload,
    TradingEvaluationShadowingDiagnosticsPayload,
    TradingEvaluationShadowingSnapshotPayload,
    TradingPositionPayload,
    PositionExitTriggerReason,
    TradingTradePayload
} from '../../../core/models';
import { NumberFormattingService } from '../../../core/number-formatting.service';
import { WebSocketService } from '../../../core/websocket.service';
import { IconHeaderRendererComponent } from '../../../renderers/icon-header.renderer';
import { SymbolChipRendererComponent } from '../../../renderers/symbol-chip.renderer';
import { TemplateCellRendererComponent } from '../../../renderers/template-cell.renderer';
import { tradingGridsLeadingColumnLayout } from '../trading.constants';
import {
    applyMobileTradingGridLayout,
    isTradingGridCompactViewport,
    resetGridColumnLayout,
    tradingGridCompactViewportQuery,
    tradingGridsMobileColumnLayout
} from '../trading-grid-viewport.utils';
import {
    computeTradingPositionDeltaPercent,
    computeTradingPositionEffectiveNotionalUsd,
    computeTradingPositionNetResultUsd,
    computeTradingPositionRealizedSecuredUsd,
    computeTradingPositionUnrealizedUsd,
    evaluationOrderNotionalUsd,
    formatDeltaPercentAndUsdCellHtml,
    formatPositionNotionalCellHtml,
    formatPositionQuantityCellHtml,
    orderTradingPositionNotionalUsd
} from '../trading-position-grid-metrics';
import { formatPositionExitReasonLabel } from '../trading-position-exit-reason.utils';
import { positionPhasePillNgClasses, resolvePositionPhaseIconClass, resolvePositionPhasePillClass } from '../trading-position-phase-pill.utils';
import { TradingPositionModalService } from '../trading-position-modal.service';
import { TradingShadowingSnapshotTabComponent } from '../trading-shadowing-snapshot-tab/trading-shadowing-snapshot-tab.component';
import { TradingPositionClosingDialogComponent } from './trading-position-closing-dialog/trading-position-closing-dialog.component';
import {
    StaledRecoverySubmitAction,
    TradingPositionStaledRecoveryDialogComponent
} from './trading-position-staled-recovery-dialog/trading-position-staled-recovery-dialog.component';

@Component({
    standalone: true,
    selector: 'trading-positions-table',
    imports: [
        CommonModule,
        DatePipe,
        AgGridAngular,
        DialogModule,
        ButtonModule,
        TagModule,
        DividerModule,
        ScrollPanelModule,
        TabsModule,
        CardModule,
        TooltipModule,
        PanelModule,
        SkeletonModule,
        NgApexchartsModule,
        TradingShadowingSnapshotTabComponent,
        TradingPositionClosingDialogComponent,
        TradingPositionStaledRecoveryDialogComponent
    ],
    templateUrl: './trading-positions-table.component.html',
    styleUrl: './trading-positions-table.component.css'
})
export class TradingPositionsTableComponent implements AfterViewInit {
    @ViewChild('actionsTemplate', { static: false }) private actionsTemplate?: TemplateRef<unknown>;

    public readonly agGridTheme = balhamDarkThemeCompact;
    public readonly closingPositionIds = signal<Set<number>>(new Set());
    public columnDefinitions: ColDef<TradingPositionPayload>[] = [];
    public readonly confirmCloseVisible = signal<boolean>(false);

    public readonly confirmRecoveryVisible = signal<boolean>(false);
    public readonly defaultColumnDefinition: ColDef<TradingPositionPayload> = {
        resizable: true,
        sortable: true,
        filter: true,
        suppressHeaderMenuButton: false,
        suppressMovable: true,
        flex: 1
    };
    public readonly detailsVisible = signal<boolean>(false);
    public readonly getRowId = (params: GetRowIdParams<TradingPositionPayload>): string => String(params.data?.id ?? '');
    public readonly gridOptions = {
        suppressMovableColumns: true
    };
    public readonly pendingClosePositionId = signal<number | null>(null);
    public readonly isCloseDialogSubmitInProgress = computed<boolean>(() => {
        const positionId = this.pendingClosePositionId();
        return positionId !== null && this.closingPositionIds().has(positionId);
    });
    public readonly pendingRecoverySubmitAction = signal<StaledRecoverySubmitAction | null>(null);
    public readonly isRecoveryDialogSubmitInProgress = computed<boolean>(() => this.pendingRecoverySubmitAction() !== null);
    public readonly pendingClosePositionSnapshot = signal<TradingPositionPayload | null>(null);

    public readonly pendingRecoveryPositionId = signal<number | null>(null);

    public readonly pendingRecoveryPositionSnapshot = signal<TradingPositionPayload | null>(null);

    private readonly webSocketService = inject(WebSocketService);

    public readonly positionsRowData = computed<TradingPositionPayload[]>(() => {
        const rows = this.webSocketService.tradingPositions() ?? [];
        return Array.isArray(rows) ? (rows as TradingPositionPayload[]) : [];
    });

    public readonly recoveryPositionIds = signal<Set<number>>(new Set());

    public readonly selectedAnalytics = signal<TradingEvaluationPayload | null>(null);
    private readonly selectedPositionId = signal<number | null>(null);
    private readonly selectedPositionSnapshot = signal<TradingPositionPayload | null>(null);

    public readonly selectedPosition = computed<TradingPositionPayload | null>(() => {
        const positionId = this.selectedPositionId();
        const snapshot = this.selectedPositionSnapshot();
        if (positionId === null) {
            return snapshot;
        }
        return this.positionsRowData().find((position) => position.id === positionId) ?? snapshot;
    });

    public selectedPositionChainIconCandidates: string[] = [];
    public selectedPositionChainIconIndex: number = 0;
    public selectedPositionDexIconCandidates: string[] = [];
    public selectedPositionDexIconIndex: number = 0;

    private readonly apiService = inject(ApiService);
    private readonly closingPositionCleanupEffect = effect(() => {
        const rows = this.positionsRowData();
        this.closingPositionIds.update((current) => {
            if (current.size === 0) {
                return current;
            }
            const next = new Set(current);
            let changed = false;
            for (const positionId of current) {
                const row = rows.find((position) => position.id === positionId);
                if (row && (row.position_phase === 'CLOSING' || row.position_phase === 'CLOSED')) {
                    next.delete(positionId);
                    changed = true;
                }
            }
            return changed ? next : current;
        });
    });
    private readonly datetimeDisplayService = inject(DatetimeDisplayService);
    private readonly defiIconsService = inject(DefiIconsService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly detailsSyncEffect = effect(() => {
        if (!this.detailsVisible()) {
            return;
        }
        this.selectedPosition();
        this.selectedAnalytics();
    });
    private readonly tradingPositionModalService = inject(TradingPositionModalService);
    private readonly externalPositionOpenEffect = effect(() => {
        const modalRequest = this.tradingPositionModalService.request();
        if (!modalRequest) {
            return;
        }
        this.openDetails(modalRequest.position, modalRequest.evaluation ?? null);
        this.tradingPositionModalService.clear();
    });
    private readonly numberFormattingService = inject(NumberFormattingService);
    private positionsGridApi: GridApi | null = null;

    public ngAfterViewInit(): void {
        this.columnDefinitions = [
            {
                headerName: 'symbol',
                colId: 'tokenSymbol',
                field: 'token_symbol',
                sortable: true,
                filter: true,
                cellRenderer: SymbolChipRendererComponent,
                comparator: (a, b) => String(a ?? '').localeCompare(String(b ?? ''), undefined, { sensitivity: 'base' }),
                ...tradingGridsLeadingColumnLayout.symbol,
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-coins' },
                cellClass: 'poseidon-grid-symbol-cell'
            },
            {
                headerName: 'opened',
                colId: 'openedAt',
                sortable: true,
                sort: 'desc',
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) => this.datetimeDisplayService.parseToDate((p.data as any)?.opened_at),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '' : this.datetimeDisplayService.formatShortForGrid(p.value as Date),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) => this.datetimeDisplayService.formatIsoForTooltip((p.data as any)?.opened_at),
                comparator: (valueA, valueB) => {
                    const timeA = valueA instanceof Date ? valueA.getTime() : (this.datetimeDisplayService.parseToDate(valueA)?.getTime() ?? 0);
                    const timeB = valueB instanceof Date ? valueB.getTime() : (this.datetimeDisplayService.parseToDate(valueB)?.getTime() ?? 0);
                    return timeA - timeB;
                },
                cellClass: 'whitespace-nowrap tabular-nums text-xs font-semibold text-slate-300',
                ...tradingGridsLeadingColumnLayout.dateTime,
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-clock' }
            },
            {
                headerName: 'phase',
                colId: 'positionPhase',
                field: 'position_phase' as unknown as keyof TradingPositionPayload,
                sortable: true,
                cellRenderer: (params: ValueFormatterParams<TradingPositionPayload>) => {
                    const value: string = String(params.value ?? '');
                    const pillClass = resolvePositionPhasePillClass(value, {
                        closingPreviewClass: value === 'CLOSING' ? this.resolveClosingPreviewPillClass(params.data) : undefined
                    });
                    const iconClass = resolvePositionPhaseIconClass(value);
                    return `<span class="poseidon-grid-pill ${pillClass}" title="${value}"><i class="fa-solid ${iconClass} poseidon-grid-pill-icon" aria-hidden="true"></i><span class="poseidon-grid-pill-label">${value}</span></span>`;
                },
                cellClass: 'poseidon-grid-phase-side-cell',
                ...tradingGridsLeadingColumnLayout.phaseOrSide,
                headerClass: 'poseidon-header-align-center',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-diagram-project', alignCenter: true }
            },
            {
                headerName: 'QTY',
                colId: 'currentQuantity',
                field: 'current_quantity',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) => this.numberFormattingService.toNumberSafe((p.data as any)?.current_quantity),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) => this.numberFormattingService.formatQuantityHumanReadable(p.value),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    formatPositionQuantityCellHtml(p.data ?? undefined, this.numberFormattingService),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatNumber((p.data as any)?.current_quantity, 2, 8),
                cellClass: 'text-right whitespace-nowrap tabular-nums font-bold text-slate-100 tracking-tight',
                ...tradingGridsLeadingColumnLayout.qty,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-layer-group', alignRight: true }
            },
            {
                headerName: 'delta',
                colId: 'deltaPercent',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) => computeTradingPositionDeltaPercent(p.data ?? null, this.numberFormattingService),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '—' : `${this.numberFormattingService.formatNumber(p.value, 2, 2)}%`,
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    formatDeltaPercentAndUsdCellHtml(p.data ?? null, this.numberFormattingService),
                cellClass: 'text-right whitespace-nowrap tabular-nums poseidon-grid-delta-stack-cell',
                ...tradingGridsLeadingColumnLayout.leadingFifthNumeric,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-chart-line', alignRight: true }
            },
            {
                headerName: 'last',
                colId: 'lastPrice',
                field: 'last_price' as unknown as keyof TradingPositionPayload,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.toNumberSafe((p.data as any)?.last_price as number | null),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '—' : this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    p.data == null ? '' : this.numberFormattingService.formatCurrency((p.data as any)?.last_price, 'USD', 4, 12),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) => {
                    const displayedValue = p.value == null ? '—' : this.numberFormattingService.formatUsdCompactForGrid(p.value);
                    const direction = (p.data as any)?.lastPriceDirection as 'up' | 'down' | null | undefined;
                    if (direction === 'up') {
                        return `<span class="last-price-tick last-price-tick-up"><span class="last-price-ripple"></span><span class="last-price-arrow" aria-hidden="true">↗</span><span class="last-price-value font-bold">${displayedValue}</span></span>`;
                    }
                    if (direction === 'down') {
                        return `<span class="last-price-tick last-price-tick-down"><span class="last-price-ripple"></span><span class="last-price-arrow" aria-hidden="true">↘</span><span class="last-price-value font-bold">${displayedValue}</span></span>`;
                    }
                    return `<span class="last-price-static font-semibold text-slate-200">${displayedValue}</span>`;
                },
                cellClass: 'text-right whitespace-nowrap tabular-nums',
                flex: 1.08,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-dollar-sign', alignRight: true }
            },
            {
                headerName: 'entry',
                colId: 'entryPrice',
                field: 'entry_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) => this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.entry_price, 'USD', 4, 12),
                cellClass: 'text-right whitespace-nowrap tabular-nums font-semibold text-slate-200',
                flex: 1.05,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-right-to-bracket', alignRight: true }
            },
            {
                headerName: 'TP1',
                colId: 'takeProfitTier1',
                field: 'take_profit_tier_1_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) => this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.take_profit_tier_1_price, 'USD', 4, 12),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.formatTakeProfitOrStopLossPriceStackCellHtml(p.data ?? undefined, p.value, 'take_profit_tier_one'),
                cellClass: 'text-right whitespace-nowrap poseidon-grid-price-stack-cell',
                flex: 1.05,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-flag', alignRight: true }
            },
            {
                headerName: 'TP2',
                colId: 'takeProfitTier2',
                field: 'take_profit_tier_2_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) => this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.take_profit_tier_2_price, 'USD', 4, 12),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.formatTakeProfitOrStopLossPriceStackCellHtml(p.data ?? undefined, p.value, 'take_profit_tier_two'),
                cellClass: 'text-right whitespace-nowrap poseidon-grid-price-stack-cell',
                flex: 1.05,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-flag-checkered', alignRight: true }
            },
            {
                headerName: 'stop',
                colId: 'stopLoss',
                field: 'stop_loss_price' as unknown as keyof TradingPositionPayload,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) => this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.stop_loss_price, 'USD', 4, 12),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.formatTakeProfitOrStopLossPriceStackCellHtml(p.data ?? undefined, p.value, 'stop_loss'),
                cellClass: 'text-right whitespace-nowrap poseidon-grid-price-stack-cell',
                flex: 1.05,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-shield-halved', alignRight: true }
            },
            {
                headerName: 'notional',
                colId: 'positionEntryNotional',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) =>
                    computeTradingPositionEffectiveNotionalUsd(p.data ?? null, this.numberFormattingService),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '—' : this.numberFormattingService.formatCurrency(p.value as number, 'USD', 0, 2),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) => {
                    const row = p.data;
                    if (row == null) {
                        return '';
                    }
                    const evaluationNotional = evaluationOrderNotionalUsd(row, this.numberFormattingService);
                    const realizedSecured = computeTradingPositionRealizedSecuredUsd(row, this.numberFormattingService);
                    const unrealized = computeTradingPositionUnrealizedUsd(row, this.numberFormattingService);
                    const netResult = computeTradingPositionNetResultUsd(row, this.numberFormattingService);
                    const effectiveNotional = computeTradingPositionEffectiveNotionalUsd(row, this.numberFormattingService);
                    const parts: string[] = [];
                    if (evaluationNotional != null) {
                        parts.push(`evaluation ${this.numberFormattingService.formatCurrency(evaluationNotional, 'USD', 2, 8)}`);
                    }
                    if (realizedSecured != null) {
                        parts.push(`secured ${this.numberFormattingService.formatCurrency(realizedSecured, 'USD', 2, 8)}`);
                    }
                    if (unrealized != null) {
                        parts.push(`unrealized ${this.numberFormattingService.formatCurrency(unrealized, 'USD', 2, 8)}`);
                    }
                    if (netResult != null) {
                        parts.push(`net ${this.numberFormattingService.formatCurrency(netResult, 'USD', 2, 8)}`);
                    }
                    if (effectiveNotional != null) {
                        parts.push(`effective ${this.numberFormattingService.formatCurrency(effectiveNotional, 'USD', 2, 8)}`);
                    }
                    return parts.join(' · ');
                },
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) => this.formatPositionNotionalCellHtml(p.data ?? undefined),
                cellClass: 'text-right whitespace-nowrap',
                flex: 0.95,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-coins', alignRight: true }
            },
            {
                headerName: 'actions',
                colId: 'actions',
                pinned: 'right',
                width: 132,
                suppressHeaderMenuButton: true,
                sortable: false,
                filter: false,
                headerClass: 'poseidon-header-align-center',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: { iconClass: 'fa-gear', alignCenter: true },
                cellRenderer: TemplateCellRendererComponent,
                cellRendererParams: { template: this.actionsTemplate }
            }
        ];
        queueMicrotask(() => {
            this.applyPositionsColumnVisibilityForViewport();
        });
    }

    public analyticsForSelected(): TradingEvaluationPayload | null {
        return this.selectedAnalytics();
    }

    public buildSnapshotFromDiagnostics(
        diagnostics: TradingEvaluationShadowingDiagnosticsPayload | null | undefined
    ): TradingEvaluationShadowingSnapshotPayload | null {
        if (!diagnostics || !diagnostics.shadowing_regime) {
            return null;
        }
        return {
            regime: diagnostics.shadowing_regime as TradingEvaluationShadowingSnapshotPayload['regime'],
            metrics: (diagnostics.shadowing_metrics ?? []) as TradingEvaluationShadowingSnapshotPayload['metrics'],
            cortex_inference: (diagnostics.cortex_inference_summary ?? null) as TradingEvaluationShadowingSnapshotPayload['cortex_inference']
        };
    }

    public canClosePosition(row: TradingPositionPayload | null | undefined): boolean {
        if (!row) {
            return false;
        }
        const phase = row.position_phase;
        if (phase !== 'OPEN' && phase !== 'PARTIAL') {
            return false;
        }
        return !this.closingPositionIds().has(row.id);
    }

    public canRecoverStaledPosition(row: TradingPositionPayload | null | undefined): boolean {
        if (!row) {
            return false;
        }
        if (row.position_phase !== 'STALED') {
            return false;
        }
        return !this.recoveryPositionIds().has(row.id);
    }

    public closePositionActionClasses(row: TradingPositionPayload | null | undefined): Record<string, boolean> {
        const canClose = this.canClosePosition(row);
        return {
            'poseidon-grid-action-btn--close-enabled': canClose,
            'poseidon-grid-action-btn--close-disabled': !canClose
        };
    }

    public async copyToClipboard(value: string | undefined | null): Promise<void> {
        if (!value) {
            return;
        }
        try {
            await navigator.clipboard.writeText(value);
        } catch {
            return;
        }
    }

    public currentPositionChainIcon(): string {
        return this.selectedPositionChainIconCandidates[this.selectedPositionChainIconIndex] ?? '';
    }

    public currentPositionDexIcon(): string | null {
        return this.selectedPositionDexIconCandidates[this.selectedPositionDexIconIndex] ?? null;
    }

    public deltaPercent(row: TradingPositionPayload | null): number {
        return computeTradingPositionDeltaPercent(row, this.numberFormattingService) ?? 0;
    }

    public dexUrlForPair(row: { blockchain_network?: string; pair_address?: string } | null): string {
        const chain = (row as any)?.blockchain_network as string | undefined;
        const pair = row?.pair_address;
        return chain && pair ? `https://dexscreener.com/${chain}/${pair}` : '';
    }

    public entryPositionPercentage(row: TradingPositionPayload | null): number {
        return this.pricePositionPercentage(row, this.numberFormattingService.toNumberSafe((row as any)?.entry_price));
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

    public formatExitReasonLabel(reason: PositionExitTriggerReason | null | undefined): string {
        return formatPositionExitReasonLabel(reason);
    }

    public formatNumber(value: unknown, min: number, max: number): string {
        return this.numberFormattingService.formatNumber(value as number, min, max);
    }

    public formatPercent(value: number | null | undefined): string {
        if (value == null) {
            return '—';
        }
        return `${this.numberFormattingService.formatNumber(value, 2, 2)}%`;
    }

    public handlePositionChainIconError(event: Event): void {
        this.advancePositionIconCandidate(event, this.selectedPositionChainIconCandidates, 'chain');
    }

    public handlePositionDexIconError(event: Event): void {
        this.advancePositionIconCandidate(event, this.selectedPositionDexIconCandidates, 'dex');
    }

    public isCloseRequestInProgress(row: TradingPositionPayload | null | undefined): boolean {
        if (!row) {
            return false;
        }
        return this.closingPositionIds().has(row.id);
    }

    public isRecoveryRequestInProgress(row: TradingPositionPayload | null | undefined): boolean {
        if (!row) {
            return false;
        }
        return this.recoveryPositionIds().has(row.id);
    }

    public nextPositionForSelected(): TradingPositionPayload | null {
        return this.getAdjacentPosition(1);
    }

    public onCloseSubmitFinished(event: { positionId: number; success: boolean }): void {
        if (!event.success) {
            this.closingPositionIds.update((current) => {
                const next = new Set(current);
                next.delete(event.positionId);
                return next;
            });
            return;
        }
        this.pendingClosePositionId.set(null);
        this.pendingClosePositionSnapshot.set(null);
    }

    public onCloseSubmitStarted(positionId: number): void {
        this.closingPositionIds.update((current) => new Set(current).add(positionId));
    }

    public onClosingDialogVisibleChange(visible: boolean): void {
        this.confirmCloseVisible.set(visible);
        if (!visible) {
            this.pendingClosePositionId.set(null);
            this.pendingClosePositionSnapshot.set(null);
        }
    }

    public onKillSubmitFinished(event: { positionId: number; success: boolean }): void {
        this.onRecoverySubmitFinished(event);
    }

    public onKillSubmitStarted(positionId: number): void {
        this.pendingRecoverySubmitAction.set('kill');
        this.recoveryPositionIds.update((current) => new Set(current).add(positionId));
    }

    public onPositionsFirstDataRendered(): void {
        this.applyPositionsColumnVisibilityForViewport();
    }

    public onPositionsGridReady(event: GridReadyEvent): void {
        this.positionsGridApi = event.api;
        this.applyPositionsColumnVisibilityForViewport();
        const handler = (): void => {
            this.applyPositionsColumnVisibilityForViewport();
        };
        const mediaCompact = window.matchMedia(tradingGridCompactViewportQuery);
        mediaCompact.addEventListener('change', handler);
        this.destroyRef.onDestroy(() => {
            mediaCompact.removeEventListener('change', handler);
        });
    }

    public onPositionsGridSizeChanged(): void {
        if (!isTradingGridCompactViewport()) {
            return;
        }
        this.applyPositionsColumnVisibilityForViewport();
    }

    public onRecoveryDialogVisibleChange(visible: boolean): void {
        this.confirmRecoveryVisible.set(visible);
        if (!visible) {
            this.pendingRecoveryPositionId.set(null);
            this.pendingRecoveryPositionSnapshot.set(null);
            this.pendingRecoverySubmitAction.set(null);
        }
    }

    public onRecoverySubmitFinished(event: { positionId: number; success: boolean }): void {
        this.pendingRecoverySubmitAction.set(null);
        this.recoveryPositionIds.update((current) => {
            const next = new Set(current);
            next.delete(event.positionId);
            return next;
        });
        if (event.success) {
            this.pendingRecoveryPositionId.set(null);
            this.pendingRecoveryPositionSnapshot.set(null);
        }
    }

    public onReopenSubmitFinished(event: { positionId: number; success: boolean }): void {
        this.onRecoverySubmitFinished(event);
    }

    public onReopenSubmitStarted(positionId: number): void {
        this.pendingRecoverySubmitAction.set('reopen');
        this.recoveryPositionIds.update((current) => new Set(current).add(positionId));
    }

    public openCloseConfirm(row: TradingPositionPayload | null): void {
        if (!row || !this.canClosePosition(row)) {
            return;
        }
        this.pendingClosePositionId.set(row.id);
        this.pendingClosePositionSnapshot.set(row);
        this.confirmCloseVisible.set(true);
    }

    public openDetails(row: TradingPositionPayload | null, preloadedEvaluation: TradingEvaluationPayload | null = null): void {
        this.selectedPositionId.set(row?.id ?? null);
        this.selectedPositionSnapshot.set(row ?? null);
        this.selectedAnalytics.set(preloadedEvaluation);
        this.resetSelectedPositionIcons(row);
        this.detailsVisible.set(true);

        if (!preloadedEvaluation && row && row.evaluation_id) {
            this.apiService.getEvaluationById(row.evaluation_id).subscribe({
                next: (evalData) => {
                    this.selectedAnalytics.set(evalData);
                },
                error: (error) => {
                    console.error('[UI][POSITIONS][DETAILS] Failed to load analytics for pair', error);
                }
            });
        }
    }

    public openNextPosition(): void {
        const position = this.nextPositionForSelected();
        if (!position) {
            return;
        }
        this.openDetails(position);
    }

    public openPreviousPosition(): void {
        const position = this.previousPositionForSelected();
        if (!position) {
            return;
        }
        this.openDetails(position);
    }

    public openStaledRecoveryConfirm(row: TradingPositionPayload | null): void {
        if (!row || !this.canRecoverStaledPosition(row)) {
            return;
        }
        this.pendingRecoveryPositionId.set(row.id);
        this.pendingRecoveryPositionSnapshot.set(row);
        this.confirmRecoveryVisible.set(true);
    }

    public orderNotionalUsd(row: TradingPositionPayload | null, priceBasis: 'entry' | 'last'): number | null {
        return orderTradingPositionNotionalUsd(row, priceBasis, this.numberFormattingService);
    }

    public previousPositionForSelected(): TradingPositionPayload | null {
        return this.getAdjacentPosition(-1);
    }

    public priceDistanceFromEntryPercent(row: TradingPositionPayload | null, targetPrice: number | null | undefined): number | null {
        if (!row || targetPrice == null) {
            return null;
        }
        const entryPrice = this.numberFormattingService.toNumberSafe(row.entry_price);
        const levelPrice = this.numberFormattingService.toNumberSafe(targetPrice);
        if (entryPrice === null || levelPrice === null || entryPrice === 0) {
            return null;
        }
        return ((levelPrice - entryPrice) / Math.abs(entryPrice)) * 100;
    }

    public pricePositionPercentage(row: TradingPositionPayload | null, targetPrice?: number | null): number {
        if (!row) {
            return 50;
        }
        const lastPrice = targetPrice !== undefined ? targetPrice : this.numberFormattingService.toNumberSafe((row as any).last_price as number | null);
        const stopLossPrice = this.numberFormattingService.toNumberSafe((row as any).stop_loss_price);
        const takeProfitTier2Price = this.numberFormattingService.toNumberSafe((row as any).take_profit_tier_2_price);
        if (lastPrice === null || stopLossPrice === null || takeProfitTier2Price === null || takeProfitTier2Price === stopLossPrice) {
            return 50;
        }
        const rawPercentage = ((lastPrice - stopLossPrice) / (takeProfitTier2Price - stopLossPrice)) * 100;
        return Math.max(0, Math.min(100, rawPercentage));
    }

    public recoveryPositionActionClasses(row: TradingPositionPayload | null | undefined): Record<string, boolean> {
        const canRecover = this.canRecoverStaledPosition(row);
        return {
            'poseidon-grid-action-btn--recovery-enabled': canRecover,
            'poseidon-grid-action-btn--recovery-disabled': !canRecover
        };
    }

    public resolveClosingPreviewPillClass(row: TradingPositionPayload | null | undefined): string {
        const delta = computeTradingPositionDeltaPercent(row ?? null, this.numberFormattingService) ?? 0;
        return delta < 0 ? 'poseidon-grid-pill--closing-negative' : 'poseidon-grid-pill--closing-positive';
    }

    public selectedPositionPhaseClasses(): Record<string, boolean> {
        return this.phaseClassesForPosition(this.selectedPosition());
    }

    public tp1PositionPercentage(row: TradingPositionPayload | null): number {
        return this.pricePositionPercentage(row, this.numberFormattingService.toNumberSafe((row as any)?.take_profit_tier_1_price));
    }

    private advancePositionIconCandidate(event: Event, candidates: string[], kind: 'chain' | 'dex'): void {
        const imageElement = event.target as HTMLImageElement | null;
        if (!imageElement) {
            return;
        }
        if (kind === 'chain') {
            this.selectedPositionChainIconIndex += 1;
            const nextCandidate = candidates[this.selectedPositionChainIconIndex];
            if (nextCandidate) {
                imageElement.src = nextCandidate;
                return;
            }
        } else {
            this.selectedPositionDexIconIndex += 1;
            const nextCandidate = candidates[this.selectedPositionDexIconIndex];
            if (nextCandidate) {
                imageElement.src = nextCandidate;
                return;
            }
        }
        imageElement.style.display = 'none';
    }

    private applyPositionsColumnVisibilityForViewport(): void {
        if (this.positionsGridApi === null) {
            return;
        }
        const isCompactViewport = isTradingGridCompactViewport();
        if (isCompactViewport) {
            applyMobileTradingGridLayout(this.positionsGridApi, {
                columnOrder: ['tokenSymbol', 'deltaPercent', 'positionPhase', 'actions'],
                layoutByColumnIdentifier: {
                    tokenSymbol: tradingGridsMobileColumnLayout.symbol,
                    deltaPercent: tradingGridsMobileColumnLayout.deltaOrProfitAndLoss,
                    positionPhase: tradingGridsMobileColumnLayout.phaseOrSide,
                    actions: tradingGridsMobileColumnLayout.openPositionsActions
                }
            });
            return;
        }
        resetGridColumnLayout(this.positionsGridApi);
        this.positionsGridApi.setColumnsVisible(
            ['openedAt', 'positionPhase', 'currentQuantity', 'lastPrice', 'entryPrice', 'deltaPercent', 'positionEntryNotional'],
            true
        );
        this.positionsGridApi.setColumnsVisible(['takeProfitTier1', 'takeProfitTier2', 'stopLoss'], true);
    }

    private findOriginBuyTrade(position: TradingPositionPayload | null): TradingTradePayload | null {
        if (!position) {
            return null;
        }
        const trades = (this.webSocketService.tradingTrades() ?? []) as TradingTradePayload[];
        const candidates = trades.filter((t) => t.trade_side === 'BUY' && t.pair_address === position.pair_address);
        if (candidates.length === 0) {
            return null;
        }

        const opened = new Date((position as any).opened_at ?? 0).getTime();
        candidates.sort((a, b) => {
            const at = new Date((a as any).created_at ?? 0).getTime();
            const bt = new Date((b as any).created_at ?? 0).getTime();
            return Math.abs(at - opened) - Math.abs(bt - opened);
        });
        return candidates[0] ?? null;
    }

    private formatPositionNotionalCellHtml(row: TradingPositionPayload | undefined): string {
        return formatPositionNotionalCellHtml(row, this.numberFormattingService);
    }

    private formatTakeProfitOrStopLossPriceStackCellHtml(
        row: TradingPositionPayload | undefined,
        priceValue: unknown,
        priceStackKind: 'take_profit_tier_one' | 'take_profit_tier_two' | 'stop_loss'
    ): string {
        const mainLineText = this.numberFormattingService.formatUsdCompactForGrid(priceValue) ?? '—';
        const mainLineCssClass = this.resolveTakeProfitStopLossPriceStackMainLineCssClass(priceStackKind);
        if (row == null) {
            return `<div class="poseidon-grid-price-stack"><span class="${mainLineCssClass}">${mainLineText}</span></div>`;
        }
        const entryPrice = this.numberFormattingService.toNumberSafe(row.entry_price);
        const levelPrice = this.numberFormattingService.toNumberSafe(priceValue);
        if (entryPrice === null || levelPrice === null || entryPrice === 0) {
            return `<div class="poseidon-grid-price-stack"><span class="${mainLineCssClass}">${mainLineText}</span></div>`;
        }
        const priceVersusEntryPercent = ((levelPrice - entryPrice) / Math.abs(entryPrice)) * 100;
        const entryRelativePercentLabel = `${priceVersusEntryPercent >= 0 ? '+' : ''}${this.numberFormattingService.formatNumber(priceVersusEntryPercent, 1, 1)}%`;
        return `<div class="poseidon-grid-price-stack"><span class="${mainLineCssClass}">${mainLineText}</span><span class="poseidon-grid-price-stack-entry-relative-percent">${entryRelativePercentLabel}</span></div>`;
    }

    private getAdjacentPosition(direction: -1 | 1): TradingPositionPayload | null {
        const selectedId = this.selectedPosition()?.id ?? null;
        if (selectedId === null) {
            return null;
        }
        const orderedPositions = this.getDisplayedPositionsInCurrentOrder();
        const selectedIndex = orderedPositions.findIndex((position) => position.id === selectedId);
        if (selectedIndex === -1) {
            return null;
        }
        return orderedPositions[selectedIndex + direction] ?? null;
    }

    private getDisplayedPositionsInCurrentOrder(): TradingPositionPayload[] {
        if (this.positionsGridApi === null) {
            return this.positionsRowData();
        }
        const rows: TradingPositionPayload[] = [];
        this.positionsGridApi.forEachNodeAfterFilterAndSort((node) => {
            if (node.data) {
                rows.push(node.data as TradingPositionPayload);
            }
        });
        return rows;
    }

    private phaseClassesForPosition(position: TradingPositionPayload | null | undefined): Record<string, boolean> {
        const phase = position?.position_phase;
        return positionPhasePillNgClasses(phase, {
            closingPreviewClass: phase === 'CLOSING' ? this.resolveClosingPreviewPillClass(position) : undefined
        });
    }

    private resetSelectedPositionIcons(row: TradingPositionPayload | null): void {
        this.selectedPositionChainIconCandidates = this.defiIconsService.getChainIconCandidates(row?.blockchain_network);
        this.selectedPositionDexIconCandidates = this.defiIconsService.getProtocolIconCandidates(row?.dex_id);
        this.selectedPositionChainIconIndex = 0;
        this.selectedPositionDexIconIndex = 0;
    }

    private resolveTakeProfitStopLossPriceStackMainLineCssClass(priceStackKind: 'take_profit_tier_one' | 'take_profit_tier_two' | 'stop_loss'): string {
        let modifierSuffix: string;
        switch (priceStackKind) {
            case 'take_profit_tier_one':
                modifierSuffix = 'take-profit-tier-one';
                break;
            case 'take_profit_tier_two':
                modifierSuffix = 'take-profit-tier-two';
                break;
            case 'stop_loss':
                modifierSuffix = 'stop-loss';
                break;
        }
        return `poseidon-grid-price-stack-main poseidon-grid-price-stack-main--${modifierSuffix}`;
    }
}
