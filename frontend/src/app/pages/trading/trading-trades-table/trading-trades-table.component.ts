import {CommonModule, DatePipe} from '@angular/common';
import {AfterViewInit, Component, computed, DestroyRef, effect, inject, signal, TemplateRef, ViewChild} from '@angular/core';
import {AgGridAngular} from 'ag-grid-angular';
import {ColDef, GetRowIdParams, GridApi, GridReadyEvent, ITooltipParams, ValueFormatterParams, ValueGetterParams} from 'ag-grid-community';

import {ButtonModule} from 'primeng/button';
import {DialogModule} from 'primeng/dialog';
import {TagModule} from 'primeng/tag';
import {DividerModule} from 'primeng/divider';
import {ScrollPanelModule} from 'primeng/scrollpanel';
import {TabsModule} from 'primeng/tabs';
import {CardModule} from 'primeng/card';
import {TooltipModule} from 'primeng/tooltip';
import {PanelModule} from 'primeng/panel';
import {SkeletonModule} from 'primeng/skeleton';

import {ApexAxisChartSeries, ApexChart, ApexDataLabels, ApexGrid, ApexLegend, ApexNonAxisChartSeries, ApexPlotOptions, ApexStates, ApexTooltip, ApexXAxis, NgApexchartsModule} from 'ng-apexcharts';

import {balhamDarkThemeCompact} from '../../../ag-grid.theme';
import {NumberFormattingService} from '../../../core/number-formatting.service';
import {DatetimeDisplayService} from '../../../core/datetime-display.service';
import {WebSocketService} from '../../../core/websocket.service';
import {TradingEvaluationPayload, TradingPositionPayload, TradingTradePayload} from '../../../core/models';
import {DefiIconsService} from '../../../core/defi-icons.service';

import {SymbolChipRendererComponent} from '../../../renderers/symbol-chip.renderer';
import {IconHeaderRendererComponent} from '../../../renderers/icon-header.renderer';
import {TemplateCellRendererComponent} from '../../../renderers/template-cell.renderer';
import {ApiService} from '../../../api.service';
import {TradingShadowIntelligenceTabComponent} from '../trading-shadow-intelligence-tab/trading-shadow-intelligence-tab.component';
import {tradingGridsLeadingColumnLayout} from "../trading.constants";
import {TradingPositionModalService} from '../trading-position-modal.service';

@Component({
    standalone: true,
    selector: 'trading-trades-table',
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
        TradingShadowIntelligenceTabComponent
    ],
    templateUrl: './trading-trades-table.component.html',
    styleUrl: './trading-trades-table.component.css'
})
export class TradingTradesTableComponent implements AfterViewInit {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly destroyRef = inject(DestroyRef);
    private readonly webSocketService = inject(WebSocketService);
    private readonly numberFormattingService = inject(NumberFormattingService);
    private readonly datetimeDisplayService = inject(DatetimeDisplayService);
    private readonly apiService = inject(ApiService);
    private readonly tradingPositionModalService = inject(TradingPositionModalService);
    private readonly defiIconsService = inject(DefiIconsService);

    private tradesGridApi: GridApi | null = null;

    public readonly tradesRowData = computed<TradingTradePayload[]>(() => {
        const rows = this.webSocketService.trades() ?? [];
        return Array.isArray(rows) ? (rows as TradingTradePayload[]) : [];
    });
    public readonly getRowId = (params: GetRowIdParams<TradingTradePayload>): string =>
        String(params.data?.id ?? '');

    public columnDefinitions: ColDef<TradingTradePayload>[] = [];
    public readonly defaultColumnDefinition: ColDef<TradingTradePayload> = {resizable: true, sortable: true, filter: true, flex: 1};

    @ViewChild('actionsTemplate', {static: false}) private actionsTemplate?: TemplateRef<unknown>;

    public readonly detailsVisible = signal<boolean>(false);
    private readonly selectedTradeId = signal<number | null>(null);
    private readonly selectedTradeSnapshot = signal<TradingTradePayload | null>(null);
    public readonly selectedTrade = computed<TradingTradePayload | null>(() => {
        const tradeId = this.selectedTradeId();
        const snapshot = this.selectedTradeSnapshot();
        if (tradeId === null) {
            return snapshot;
        }
        return this.tradesRowData().find((trade) => trade.id === tradeId) ?? snapshot;
    });
    public readonly selectedAnalytics = signal<TradingEvaluationPayload | null>(null);
    public readonly positionForSelectedTrade = computed<TradingPositionPayload | null>(() =>
        this.findPositionForTrade(this.selectedTrade())
    );
    private readonly detailsSyncEffect = effect(() => {
        if (!this.detailsVisible()) {
            return;
        }
        this.selectedTrade();
        this.selectedAnalytics();
        this.recomputeCharts();
    });

    public scoresSeries: ApexNonAxisChartSeries = [];
    public scoresChart: ApexChart = {type: 'radialBar', height: 240};
    public scoresLabels: string[] = [];
    public scoresPlot: ApexPlotOptions = {
        radialBar: {
            hollow: {size: '22%'},
            dataLabels: {name: {fontSize: '12px'}, value: {fontSize: '16px'}}
        }
    };
    public scoresLegend: ApexLegend = {show: true, position: 'bottom'};

    public deltaSeries: ApexAxisChartSeries = [];
    public deltaChart: ApexChart = {type: 'bar', height: 240, toolbar: {show: false}};
    public deltaXaxis: ApexXAxis = {categories: ['5m', '1h', '24h']};
    public deltaPlot: ApexPlotOptions = {bar: {distributed: true, columnWidth: '45%'}};
    public deltaColors: string[] = [];
    public deltaDataLabels: ApexDataLabels = {enabled: true, formatter: (v: number) => `${v.toFixed(2)}%`};

    public liqVolSeries: ApexNonAxisChartSeries = [];
    public liqVolChart: ApexChart = {type: 'donut', height: 240};
    public liqVolLabels: string[] = ['Liquidity (24h)', 'Volume (24h)'];

    public notionalSeries: ApexAxisChartSeries = [];
    public notionalChart: ApexChart = {type: 'bar', height: 200, toolbar: {show: false}};
    public notionalPlot: ApexPlotOptions = {bar: {horizontal: true, barHeight: '60%'}};
    public notionalXaxis: ApexXAxis = {categories: ['Order notional (USD)']};
    public notionalDataLabels: ApexDataLabels = {
        enabled: true,
        formatter: (v: number) => `$${this.numberFormattingService.formatNumber(v, 0, 0)}`
    };

    public grid: ApexGrid = {padding: {left: 8, right: 8}};
    public states: ApexStates = {hover: {filter: {type: 'lighten'}}};
    public tooltip: ApexTooltip = {enabled: true};
    public selectedTradeChainIconCandidates: string[] = [];
    public selectedTradeDexIconCandidates: string[] = [];
    public selectedTradeChainIconIndex: number = 0;
    public selectedTradeDexIconIndex: number = 0;

    public ngAfterViewInit(): void {
        this.columnDefinitions = [
            {
                headerName: 'symbol',
                colId: 'tokenSymbol',
                field: 'token_symbol',
                sortable: true,
                filter: true,
                cellRenderer: SymbolChipRendererComponent,
                ...tradingGridsLeadingColumnLayout.symbol,
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-coins'},
                cellClass: 'poseidon-grid-symbol-cell'
            },
            {
                headerName: 'executed',
                colId: 'createdAt',
                sortable: true,
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingTradePayload>) =>
                    this.datetimeDisplayService.parseToDate((p.data as any)?.created_at),
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) =>
                    p.value == null ? '' : this.datetimeDisplayService.formatShortForGrid(p.value as Date),
                tooltipValueGetter: (p: ITooltipParams<TradingTradePayload>) =>
                    this.datetimeDisplayService.formatIsoForTooltip((p.data as any)?.created_at),
                comparator: (valueA, valueB) => {
                    const timeA =
                        valueA instanceof Date
                            ? valueA.getTime()
                            : this.datetimeDisplayService.parseToDate(valueA)?.getTime() ?? 0;
                    const timeB =
                        valueB instanceof Date
                            ? valueB.getTime()
                            : this.datetimeDisplayService.parseToDate(valueB)?.getTime() ?? 0;
                    return timeA - timeB;
                },
                cellClass: 'whitespace-nowrap tabular-nums text-xs font-semibold text-slate-300',
                ...tradingGridsLeadingColumnLayout.dateTime,
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-clock'}
            },
            {
                headerName: 'side',
                colId: 'tradeSide',
                field: 'trade_side',
                sortable: true,
                filter: true,
                cellRenderer: (p: ValueFormatterParams<TradingTradePayload>) => {
                    const v = String(p.value ?? '');
                    const pillClass = v === 'BUY' ? 'poseidon-grid-pill--buy' : 'poseidon-grid-pill--sell';
                    return `<span class="poseidon-grid-pill ${pillClass}">${v}</span>`;
                },
                cellClass: 'poseidon-grid-phase-side-cell',
                ...tradingGridsLeadingColumnLayout.phaseOrSide,
                headerClass: 'poseidon-header-align-center',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-right-left', alignCenter: true}
            },
            {
                headerName: 'QTY',
                colId: 'executionQuantity',
                field: 'execution_quantity',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) =>
                    this.numberFormattingService.formatQuantityHumanReadable(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingTradePayload>) =>
                    this.numberFormattingService.formatNumber((p.data as any)?.execution_quantity, 2, 8),
                cellClass: 'text-right whitespace-nowrap tabular-nums font-bold text-slate-100 tracking-tight',
                ...tradingGridsLeadingColumnLayout.qty,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-layer-group', alignRight: true}
            },
            {
                headerName: 'PnL',
                colId: 'realizedProfitAndLoss',
                field: 'realized_profit_and_loss' as unknown as keyof TradingTradePayload,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 2, 2),
                headerClass: 'ag-right-aligned-header poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-scale-balanced', alignRight: true},
                cellClass: (p: ValueFormatterParams<TradingTradePayload>) => {
                    const n = this.numberFormattingService.toNumberSafe(p.value as number | null);
                    if (n === null) {
                        return 'text-right whitespace-nowrap ag-right-aligned-cell tabular-nums font-semibold text-slate-400';
                    }
                    return n > 0
                        ? 'text-right whitespace-nowrap ag-right-aligned-cell tabular-nums poseidon-grid-emphasized-metric text-emerald-400'
                        : n < 0
                            ? 'text-right whitespace-nowrap ag-right-aligned-cell tabular-nums poseidon-grid-emphasized-metric text-rose-400'
                            : 'text-right whitespace-nowrap ag-right-aligned-cell tabular-nums font-semibold text-slate-300';
                },
                ...tradingGridsLeadingColumnLayout.leadingFifthNumeric
            },
            {
                headerName: 'price',
                colId: 'executionPrice',
                field: 'execution_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) =>
                    this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingTradePayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.execution_price, 'USD', 4, 12),
                cellClass: 'text-right whitespace-nowrap tabular-nums font-semibold text-slate-200',
                flex: 1,
                minWidth: 96,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-dollar-sign', alignRight: true}
            },
            {
                headerName: 'tx fee',
                colId: 'transactionFee',
                field: 'transaction_fee' as unknown as keyof TradingTradePayload,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) => {
                    const feeUsd = this.numberFormattingService.toNumberSafe(p.value as number | null);
                    if (feeUsd === null) {
                        return '—';
                    }
                    return this.numberFormattingService.formatCurrency(feeUsd, 'USD', 2, 6);
                },
                cellClass: 'text-right whitespace-nowrap tabular-nums font-semibold text-slate-300',
                flex: 1,
                minWidth: 88,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-receipt', alignRight: true}
            },
            {
                headerName: 'tx hash',
                colId: 'transactionHash',
                sortable: true,
                filter: true,
                valueGetter: (p: ValueGetterParams<TradingTradePayload>) => {
                    const raw = p.data?.transaction_hash?.trim();
                    return raw == null || raw.length === 0 ? null : raw;
                },
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) => {
                    const raw = typeof p.value === 'string' ? p.value.trim() : '';
                    if (raw.length === 0) {
                        return '—';
                    }
                    return raw.length <= 18 ? raw : `${raw.slice(0, 8)}…${raw.slice(-6)}`;
                },
                tooltipValueGetter: (p: ITooltipParams<TradingTradePayload>) => p.data?.transaction_hash?.trim() ?? '',
                cellRenderer: (p: ValueFormatterParams<TradingTradePayload>) =>
                    this.formatTransactionHashCellHtml(p.data ?? undefined),
                cellClass: 'text-right whitespace-nowrap',
                flex: 2,
                minWidth: 120,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-link', alignRight: true}
            },
            {
                headerName: '',
                colId: 'actions',
                pinned: 'right',
                width: 100,
                suppressHeaderMenuButton: true,
                sortable: false,
                filter: false,
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-ellipsis-vertical', hideLabel: true},
                cellRenderer: TemplateCellRendererComponent,
                cellRendererParams: {template: this.actionsTemplate}
            }
        ];
    }

    public onTradesGridReady(event: GridReadyEvent): void {
        this.tradesGridApi = event.api;
        this.applyTradesColumnVisibilityForViewport();
        const handler = (): void => {
            this.applyTradesColumnVisibilityForViewport();
        };
        const mediaExtraSmall = window.matchMedia('(max-width: 768px)');
        mediaExtraSmall.addEventListener('change', handler);
        this.destroyRef.onDestroy(() => {
            mediaExtraSmall.removeEventListener('change', handler);
        });
    }

    private applyTradesColumnVisibilityForViewport(): void {
        if (this.tradesGridApi === null) {
            return;
        }
        const isExtraSmallViewport = window.matchMedia('(max-width: 768px)').matches;
        if (isExtraSmallViewport) {
            this.tradesGridApi.setColumnsVisible(['tokenSymbol', 'realizedProfitAndLoss', 'actions'], true);
            this.tradesGridApi.setColumnsVisible(
                ['createdAt', 'tradeSide', 'executionQuantity', 'executionPrice', 'transactionFee', 'transactionHash'],
                false
            );
            return;
        }
        this.tradesGridApi.setColumnsVisible(
            [
                'createdAt',
                'tradeSide',
                'executionQuantity',
                'realizedProfitAndLoss',
                'executionPrice',
                'transactionFee',
                'transactionHash'
            ],
            true
        );
    }

    public openDetails(row: TradingTradePayload | null): void {
        this.selectedTradeId.set(row?.id ?? null);
        this.selectedTradeSnapshot.set(row ?? null);
        this.selectedAnalytics.set(null);
        this.resetSelectedTradeIcons(row);
        this.detailsVisible.set(true);

        if (row && row.evaluation_id) {
            this.apiService.getEvaluationById(row.evaluation_id).subscribe({
                next: (evalData) => {
                    this.selectedAnalytics.set(evalData);
                },
                error: (error) => {
                    console.error('[UI][TRADES][DETAILS] Failed to load analytics for pair', error);
                }
            });
        }
    }

    public analyticsForSelected(): TradingEvaluationPayload | null {
        return this.selectedAnalytics();
    }

    public dexUrlForPair(row: { blockchain_network?: string; pair_address?: string } | null): string {
        const chain = (row as any)?.blockchain_network as string | undefined;
        const pair = row?.pair_address;
        return chain && pair ? `https://dexscreener.com/${chain}/${pair}` : '';
    }

    public dexUrlForToken(row: { blockchain_network?: string; token_address?: string } | null): string {
        const chain = (row as any)?.blockchain_network as string | undefined;
        const token = row?.token_address;
        return chain && token ? `https://dexscreener.com/${chain}/${token}` : '';
    }

    public transactionExplorerUrl(row: TradingTradePayload | null): string | null {
        const hash = row?.transaction_hash?.trim();
        if (!row || !hash) {
            return null;
        }
        const chain = String(row.blockchain_network ?? '').toLowerCase();
        if (chain === 'solana') {
            return `https://solscan.io/tx/${hash}`;
        }
        return null;
    }

    public openLinkedPositionDetails(): void {
        const linkedPosition = this.positionForSelectedTrade();
        if (!linkedPosition) {
            return;
        }
        this.detailsVisible.set(false);
        window.setTimeout(() => {
            this.tradingPositionModalService.open(linkedPosition);
        }, 0);
    }

    public previousTradeForSelected(): TradingTradePayload | null {
        return this.getAdjacentTrade(-1);
    }

    public nextTradeForSelected(): TradingTradePayload | null {
        return this.getAdjacentTrade(1);
    }

    public openPreviousTrade(): void {
        const trade = this.previousTradeForSelected();
        if (!trade) {
            return;
        }
        this.openDetails(trade);
    }

    public openNextTrade(): void {
        const trade = this.nextTradeForSelected();
        if (!trade) {
            return;
        }
        this.openDetails(trade);
    }

    public linkedPositionDeltaPercent(position: TradingPositionPayload | null): number | null {
        if (!position) {
            return null;
        }
        const lastPrice = this.numberFormattingService.toNumberSafe(position.last_price ?? null);
        const entryPrice = this.numberFormattingService.toNumberSafe(position.entry_price);
        if (lastPrice === null || entryPrice === null || entryPrice === 0) {
            return null;
        }
        return ((lastPrice - entryPrice) / Math.abs(entryPrice)) * 100;
    }

    public linkedPositionLastPrice(position: TradingPositionPayload | null): number | null {
        if (!position) {
            return null;
        }
        return this.numberFormattingService.toNumberSafe(position.last_price ?? null);
    }

    private formatTransactionHashCellHtml(row: TradingTradePayload | undefined): string {
        const raw = row?.transaction_hash?.trim();
        if (raw == null || raw.length === 0) {
            return '<span class="text-slate-500">—</span>';
        }
        const shortLabel = raw.length <= 14 ? raw : `${raw.slice(0, 6)}…${raw.slice(-4)}`;
        const shortHtml = this.escapeHtmlText(shortLabel);
        const explorerUrl = row == null ? null : this.transactionExplorerUrl(row);
        if (explorerUrl != null && explorerUrl.length > 0) {
            const href = this.escapeHtmlAttributeValue(explorerUrl);
            return `<a class="poseidon-grid-tx-hash-link" href="${href}" target="_blank" rel="noopener noreferrer">${shortHtml}</a>`;
        }
        return `<span class="poseidon-grid-tx-hash-muted">${shortHtml}</span>`;
    }

    private escapeHtmlText(text: string): string {
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    private escapeHtmlAttributeValue(text: string): string {
        return text
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    public orderNotionalUsd(row: TradingTradePayload | null): number | null {
        if (!row) {
            return null;
        }
        const q = this.numberFormattingService.toNumberSafe((row as any).execution_quantity);
        const p = this.numberFormattingService.toNumberSafe((row as any).execution_price);
        if (q === null || p === null) {
            return null;
        }
        return q * p;
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

    public formatNumber(value: unknown, min: number, max: number): string {
        return this.numberFormattingService.formatNumber(value as number, min, max);
    }

    public formatCurrency(value: unknown, code: string, min: number, max: number): string {
        return this.numberFormattingService.formatCurrency(value as number, code, min, max);
    }

    public formatCompactUsd(value: unknown): string {
        return this.numberFormattingService.formatUsdCompactForGrid(value) || '—';
    }

    public formatCompactQuantity(value: unknown): string {
        return this.numberFormattingService.formatQuantityHumanReadable(value) || '—';
    }

    public formatSignedCompactUsd(value: unknown): string {
        const number = this.numberFormattingService.toNumberSafe(value);
        if (number === null) {
            return '—';
        }
        const formatted = this.numberFormattingService.formatUsdCompactForGrid(number) || '—';
        return number > 0 ? `+${formatted}` : formatted;
    }

    public formatPercent(value: number | null | undefined): string {
        if (value == null) {
            return '—';
        }
        return `${this.numberFormattingService.formatNumber(value, 2, 2)}%`;
    }

    public currentTradeChainIcon(): string {
        return this.selectedTradeChainIconCandidates[this.selectedTradeChainIconIndex] ?? '';
    }

    public currentTradeDexIcon(): string | null {
        return this.selectedTradeDexIconCandidates[this.selectedTradeDexIconIndex] ?? null;
    }

    public handleTradeChainIconError(event: Event): void {
        this.advanceTradeIconCandidate(event, this.selectedTradeChainIconCandidates, 'chain');
    }

    public handleTradeDexIconError(event: Event): void {
        this.advanceTradeIconCandidate(event, this.selectedTradeDexIconCandidates, 'dex');
    }

    private getAdjacentTrade(direction: -1 | 1): TradingTradePayload | null {
        const selectedId = this.selectedTrade()?.id ?? null;
        if (selectedId === null) {
            return null;
        }
        const orderedTrades = this.getDisplayedTradesInCurrentOrder();
        const selectedIndex = orderedTrades.findIndex((trade) => trade.id === selectedId);
        if (selectedIndex === -1) {
            return null;
        }
        return orderedTrades[selectedIndex + direction] ?? null;
    }

    private getDisplayedTradesInCurrentOrder(): TradingTradePayload[] {
        if (this.tradesGridApi === null) {
            return this.tradesRowData();
        }
        const rows: TradingTradePayload[] = [];
        this.tradesGridApi.forEachNodeAfterFilterAndSort((node) => {
            if (node.data) {
                rows.push(node.data as TradingTradePayload);
            }
        });
        return rows;
    }

    private resetSelectedTradeIcons(row: TradingTradePayload | null): void {
        this.selectedTradeChainIconCandidates = this.defiIconsService.getChainIconCandidates(row?.blockchain_network);
        this.selectedTradeDexIconCandidates = this.defiIconsService.getProtocolIconCandidates(row?.dex_id);
        this.selectedTradeChainIconIndex = 0;
        this.selectedTradeDexIconIndex = 0;
    }

    private advanceTradeIconCandidate(event: Event, candidates: string[], kind: 'chain' | 'dex'): void {
        const imageElement = event.target as HTMLImageElement | null;
        if (!imageElement) {
            return;
        }
        if (kind === 'chain') {
            this.selectedTradeChainIconIndex += 1;
            const nextCandidate = candidates[this.selectedTradeChainIconIndex];
            if (nextCandidate) {
                imageElement.src = nextCandidate;
                return;
            }
        } else {
            this.selectedTradeDexIconIndex += 1;
            const nextCandidate = candidates[this.selectedTradeDexIconIndex];
            if (nextCandidate) {
                imageElement.src = nextCandidate;
                return;
            }
        }
        imageElement.style.display = 'none';
    }

    private findPositionForTrade(trade: TradingTradePayload | null): TradingPositionPayload | null {
        if (!trade) {
            return null;
        }
        const linkedPositionId = trade.linked_position.id;
        const positions = this.webSocketService.positions() ?? [];
        const livePosition = positions.find((position) => position.id === linkedPositionId);
        if (livePosition) {
            return livePosition;
        }
        return trade.linked_position;
    }

    private recomputeCharts(): void {
        const t = this.selectedTrade();
        const a = this.selectedAnalytics();

        const scoreValues: number[] = [];
        const scoreLabels: string[] = [];
        const push = (label: string, v: number | null | undefined) => {
            if (v == null) {
                return;
            }
            scoreLabels.push(label);
            scoreValues.push(v);
        };
        push('Quality', (a as any)?.scores?.quality_score);
        push('AI adjusted', (a as any)?.scores?.ai_adjusted_quality_score);
        this.scoresLabels = scoreLabels;
        this.scoresSeries = scoreValues;

        const pct5m = this.numberFormattingService.toNumberSafe((a as any)?.fundamentals?.price_change_percentage_m5) ?? 0;
        const pct1h = this.numberFormattingService.toNumberSafe((a as any)?.fundamentals?.price_change_percentage_h1) ?? 0;
        const pct24h = this.numberFormattingService.toNumberSafe((a as any)?.fundamentals?.price_change_percentage_h24) ?? 0;
        const deltas = [pct5m, pct1h, pct24h];
        this.deltaSeries = [{name: 'Δ', data: deltas}];
        this.deltaColors = deltas.map((v) => (v >= 0 ? '#22c55e' : '#ef4444'));

        const liq = this.numberFormattingService.toNumberSafe((a as any)?.fundamentals?.liquidity_usd) ?? 0;
        const vol = this.numberFormattingService.toNumberSafe((a as any)?.fundamentals?.volume_h24_usd) ?? 0;
        this.liqVolSeries = [Math.max(liq, 0), Math.max(vol, 0)];

        const notional = this.orderNotionalUsd(t) ?? 0;
        this.notionalSeries = [{name: 'Notional', data: [notional]}];
    }
}
