import {CommonModule, DatePipe} from '@angular/common';
import {AfterViewInit, Component, computed, DestroyRef, inject, signal, TemplateRef, ViewChild} from '@angular/core';
import {AgGridAngular} from 'ag-grid-angular';
import {
    ColDef,
    GetRowIdParams,
    GridApi,
    GridReadyEvent,
    ITooltipParams,
    ValueFormatterParams,
    ValueGetterParams
} from 'ag-grid-community';

import {ButtonModule} from 'primeng/button';
import {DialogModule} from 'primeng/dialog';
import {TagModule} from 'primeng/tag';
import {DividerModule} from 'primeng/divider';
import {ScrollPanelModule} from 'primeng/scrollpanel';
import {TabsModule} from 'primeng/tabs';
import {CardModule} from 'primeng/card';
import {TooltipModule} from 'primeng/tooltip';
import {PanelModule} from 'primeng/panel';

import {
    ApexAxisChartSeries,
    ApexChart,
    ApexDataLabels,
    ApexFill,
    ApexGrid,
    ApexLegend,
    ApexNonAxisChartSeries,
    ApexPlotOptions,
    ApexResponsive,
    ApexStates,
    ApexStroke,
    ApexTooltip,
    ApexXAxis,
    NgApexchartsModule
} from 'ng-apexcharts';

import {balhamDarkThemeCompact} from '../../../ag-grid.theme';
import {NumberFormattingService} from '../../../core/number-formatting.service';
import {DatetimeDisplayService} from '../../../core/datetime-display.service';
import {WebSocketService} from '../../../core/websocket.service';
import {TradingEvaluationPayload, TradingPositionPayload, TradingTradePayload} from '../../../core/models';

import {SymbolChipRendererComponent} from '../../../renderers/symbol-chip.renderer';
import {IconHeaderRendererComponent} from '../../../renderers/icon-header.renderer';
import {TemplateCellRendererComponent} from '../../../renderers/template-cell.renderer';
import {ApiService} from '../../../api.service';
import {tradingGridsLeadingColumnLayout} from '../trading-grids-leading-column-layout';
import {TradingShadowIntelligenceTabComponent} from '../trading-shadow-intelligence-tab/trading-shadow-intelligence-tab.component';

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
        NgApexchartsModule,
        TradingShadowIntelligenceTabComponent
    ],
    templateUrl: './trading-positions-table.component.html',
    styleUrl: './trading-positions-table.component.css'
})
export class TradingPositionsTableComponent implements AfterViewInit {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly destroyRef = inject(DestroyRef);
    private readonly webSocketService = inject(WebSocketService);
    private readonly numberFormattingService = inject(NumberFormattingService);
    private readonly datetimeDisplayService = inject(DatetimeDisplayService);
    private readonly apiService = inject(ApiService);

    private positionsGridApi: GridApi | null = null;

    public readonly positionsRowData = computed<TradingPositionPayload[]>(() => {
        const rows = this.webSocketService.positions() ?? [];
        return Array.isArray(rows) ? (rows as TradingPositionPayload[]) : [];
    });
    public readonly getRowId = (params: GetRowIdParams<TradingPositionPayload>): string =>
        String(params.data?.id ?? '');

    public columnDefinitions: ColDef<TradingPositionPayload>[] = [];
    public readonly defaultColumnDefinition: ColDef<TradingPositionPayload> = {
        resizable: true,
        sortable: true,
        filter: true,
        suppressHeaderMenuButton: false,
        flex: 1
    };

    @ViewChild('actionsTemplate', {static: false}) private actionsTemplate?: TemplateRef<unknown>;

    public readonly detailsVisible = signal<boolean>(false);
    public readonly selectedPosition = signal<TradingPositionPayload | null>(null);
    public readonly selectedAnalytics = signal<TradingEvaluationPayload | null>(null);

    private cachedOriginBuyTrade: TradingTradePayload | null = null;

    public scoresSeries: ApexNonAxisChartSeries = [];
    public scoresChart: ApexChart = {type: 'radialBar', height: 260};
    public scoresLabels: string[] = [];
    public scoresPlot: ApexPlotOptions = {
        radialBar: {
            hollow: {size: '22%'},
            dataLabels: {name: {fontSize: '12px'}, value: {fontSize: '16px'}}
        }
    };
    public scoresLegend: ApexLegend = {show: true, position: 'bottom'};

    public deltaSeries: ApexAxisChartSeries = [];
    public deltaChart: ApexChart = {type: 'bar', height: 260, toolbar: {show: false}};
    public deltaXaxis: ApexXAxis = {categories: ['5m', '1h', '24h']};
    public deltaPlot: ApexPlotOptions = {bar: {distributed: true, columnWidth: '45%'}};
    public deltaColors: string[] = [];
    public deltaDataLabels: ApexDataLabels = {enabled: true, formatter: (v: number) => `${v.toFixed(2)}%`};

    public liqVolSeries: ApexNonAxisChartSeries = [];
    public liqVolChart: ApexChart = {type: 'donut', height: 260};
    public liqVolLabels: string[] = ['Liquidity (24h)', 'Volume (24h)'];
    public liqVolResponsive: ApexResponsive[] = [
        {breakpoint: 768, options: {chart: {height: 220}, legend: {position: 'bottom'}}}
    ];

    public probSeries: ApexNonAxisChartSeries = [];
    public probChart: ApexChart = {type: 'radialBar', height: 220};
    public probPlot: ApexPlotOptions = {
        radialBar: {
            startAngle: -120,
            endAngle: 120,
            hollow: {margin: 0, size: '55%'},
            dataLabels: {name: {show: true}, value: {show: true, formatter: (v: number) => `${v.toFixed(1)}%`}}
        }
    };
    public probLabels: string[] = ['take profit tier 1 before stop loss'];

    public notionalSeries: ApexAxisChartSeries = [];
    public notionalChart: ApexChart = {type: 'bar', height: 220, toolbar: {show: false}};
    public notionalPlot: ApexPlotOptions = {bar: {horizontal: true, barHeight: '60%'}};
    public notionalXaxis: ApexXAxis = {categories: ['Entry', 'Last']};
    public notionalDataLabels: ApexDataLabels = {
        enabled: true,
        formatter: (v: number) => `$${this.numberFormattingService.formatNumber(v, 0, 0)}`
    };

    public grid: ApexGrid = {padding: {left: 8, right: 8}};
    public stroke: ApexStroke = {width: 2};
    public fill: ApexFill = {opacity: 0.85};
    public states: ApexStates = {hover: {filter: {type: 'lighten'}}};
    public tooltip: ApexTooltip = {enabled: true};

    public ngAfterViewInit(): void {
        this.columnDefinitions = [
            {
                headerName: 'symbol',
                colId: 'tokenSymbol',
                field: 'token_symbol',
                sortable: true,
                filter: true,
                cellRenderer: SymbolChipRendererComponent,
                comparator: (a, b) => String(a ?? '').localeCompare(String(b ?? ''), undefined, {sensitivity: 'base'}),
                ...tradingGridsLeadingColumnLayout.symbol,
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-coins'},
                cellClass: 'poseidon-grid-symbol-cell'
            },
            {
                headerName: 'opened',
                colId: 'openedAt',
                sortable: true,
                sort: 'desc',
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) =>
                    this.datetimeDisplayService.parseToDate((p.data as any)?.opened_at),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '' : this.datetimeDisplayService.formatShortForGrid(p.value as Date),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.datetimeDisplayService.formatIsoForTooltip((p.data as any)?.opened_at),
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
                headerName: 'phase',
                colId: 'positionPhase',
                field: 'position_phase' as unknown as keyof TradingPositionPayload,
                sortable: true,
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) => {
                    const sev = this.phaseSeverity(String((p.value as any) ?? ''));
                    const pillClass =
                        sev === 'info'
                            ? 'poseidon-grid-pill--info'
                            : sev === 'warn'
                                ? 'poseidon-grid-pill--warn'
                                : 'poseidon-grid-pill--neutral';
                    return `<span class="poseidon-grid-pill ${pillClass}">${p.value}</span>`;
                },
                cellClass: 'poseidon-grid-phase-side-cell',
                ...tradingGridsLeadingColumnLayout.phaseOrSide,
                headerClass: 'poseidon-header-align-center',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-diagram-project', alignCenter: true}
            },
            {
                headerName: 'QTY',
                colId: 'openQuantity',
                field: 'open_quantity',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatQuantityHumanReadable(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatNumber((p.data as any)?.open_quantity, 2, 8),
                cellClass: 'text-right whitespace-nowrap tabular-nums font-bold text-slate-100 tracking-tight',
                ...tradingGridsLeadingColumnLayout.qty,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-layer-group', alignRight: true}
            },
            {
                headerName: 'delta %',
                colId: 'deltaPercent',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) => this.computeDeltaPercent(p.data ?? null),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '—' : `${this.numberFormattingService.formatNumber(p.value, 2, 2)}%`,
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) => {
                    const deltaValue = this.numberFormattingService.toNumberSafe(p.value as number | null);
                    const displayedValue =
                        deltaValue == null
                            ? '—'
                            : `${this.numberFormattingService.formatNumber(deltaValue, 2, 2)}%`;
                    if (deltaValue == null || deltaValue === 0) {
                        return `<span class="delta-static font-semibold text-slate-400 poseidon-grid-emphasized-metric">${displayedValue}</span>`;
                    }
                    if (deltaValue > 0) {
                        return `<span class="delta-tick delta-tick-up font-bold"><span class="delta-arrow" aria-hidden="true">↗</span><span class="poseidon-grid-emphasized-metric">${displayedValue}</span></span>`;
                    }
                    return `<span class="delta-tick delta-tick-down font-bold"><span class="delta-arrow" aria-hidden="true">↘</span><span class="poseidon-grid-emphasized-metric">${displayedValue}</span></span>`;
                },
                cellClass: 'text-right whitespace-nowrap tabular-nums',
                ...tradingGridsLeadingColumnLayout.leadingFifthNumeric,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-chart-line', alignRight: true}
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
                    p.data == null
                        ? ''
                        : this.numberFormattingService.formatCurrency((p.data as any)?.last_price, 'USD', 4, 12),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) => {
                    const displayedValue =
                        p.value == null
                            ? '—'
                            : this.numberFormattingService.formatUsdCompactForGrid(p.value);
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
                headerComponentParams: {iconClass: 'fa-dollar-sign', alignRight: true}
            },
            {
                headerName: 'entry',
                colId: 'entryPrice',
                field: 'entry_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.entry_price, 'USD', 4, 12),
                cellClass: 'text-right whitespace-nowrap tabular-nums font-semibold text-slate-200',
                flex: 1.05,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-right-to-bracket', alignRight: true}
            },
            {
                headerName: 'TP1',
                colId: 'takeProfitTier1',
                field: 'take_profit_tier_1_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.take_profit_tier_1_price, 'USD', 4, 12),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.formatTakeProfitOrStopLossPriceStackCellHtml(
                        p.data ?? undefined,
                        p.value,
                        'take_profit_tier_one'
                    ),
                cellClass: 'text-right whitespace-nowrap poseidon-grid-price-stack-cell',
                flex: 1.05,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-flag', alignRight: true}
            },
            {
                headerName: 'TP2',
                colId: 'takeProfitTier2',
                field: 'take_profit_tier_2_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.take_profit_tier_2_price, 'USD', 4, 12),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.formatTakeProfitOrStopLossPriceStackCellHtml(
                        p.data ?? undefined,
                        p.value,
                        'take_profit_tier_two'
                    ),
                cellClass: 'text-right whitespace-nowrap poseidon-grid-price-stack-cell',
                flex: 1.05,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-flag-checkered', alignRight: true}
            },
            {
                headerName: 'stop',
                colId: 'stopLoss',
                field: 'stop_loss_price' as unknown as keyof TradingPositionPayload,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatUsdCompactForGrid(p.value),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency((p.data as any)?.stop_loss_price, 'USD', 4, 12),
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.formatTakeProfitOrStopLossPriceStackCellHtml(p.data ?? undefined, p.value, 'stop_loss'),
                cellClass: 'text-right whitespace-nowrap poseidon-grid-price-stack-cell',
                flex: 1.05,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-shield-halved', alignRight: true}
            },
            {
                headerName: 'notional',
                colId: 'positionEntryNotional',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) =>
                    this.orderNotionalUsd(p.data ?? null, 'last'),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '—' : this.numberFormattingService.formatCurrency(p.value as number, 'USD', 0, 2),
                tooltipValueGetter: (p: ITooltipParams<TradingPositionPayload>) => {
                    const row = p.data;
                    if (row == null) {
                        return '';
                    }
                    const entryNotional = this.orderNotionalUsd(row, 'entry');
                    const lastNotional = this.orderNotionalUsd(row, 'last');
                    const delta = this.computeDeltaPercent(row);
                    const parts: string[] = [];
                    if (entryNotional != null) {
                        parts.push(
                            `entry ${this.numberFormattingService.formatCurrency(entryNotional, 'USD', 2, 8)}`
                        );
                    }
                    if (lastNotional != null) {
                        parts.push(`last ${this.numberFormattingService.formatCurrency(lastNotional, 'USD', 2, 8)}`);
                    }
                    if (delta != null) {
                        parts.push(`delta ${this.numberFormattingService.formatNumber(delta, 2, 2)}%`);
                    }
                    return parts.join(' · ');
                },
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.formatPositionNotionalCellHtml(p.data ?? undefined),
                cellClass: 'text-right whitespace-nowrap',
                flex: 0.95,
                headerClass: 'poseidon-header-align-end',
                headerComponent: IconHeaderRendererComponent,
                headerComponentParams: {iconClass: 'fa-coins', alignRight: true}
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

    public onPositionsGridReady(event: GridReadyEvent): void {
        this.positionsGridApi = event.api;
        this.applyPositionsColumnVisibilityForViewport();
        const handler = (): void => {
            this.applyPositionsColumnVisibilityForViewport();
        };
        const mediaNarrow = window.matchMedia('(max-width: 1024px)');
        const mediaExtraSmall = window.matchMedia('(max-width: 768px)');
        mediaNarrow.addEventListener('change', handler);
        mediaExtraSmall.addEventListener('change', handler);
        this.destroyRef.onDestroy(() => {
            mediaNarrow.removeEventListener('change', handler);
            mediaExtraSmall.removeEventListener('change', handler);
        });
    }

    private applyPositionsColumnVisibilityForViewport(): void {
        if (this.positionsGridApi === null) {
            return;
        }
        const isNarrowViewport = window.matchMedia('(max-width: 1024px)').matches;
        const isExtraSmallViewport = window.matchMedia('(max-width: 768px)').matches;
        if (isExtraSmallViewport) {
            this.positionsGridApi.setColumnsVisible(
                ['tokenSymbol', 'deltaPercent', 'positionEntryNotional', 'actions'],
                true
            );
            this.positionsGridApi.setColumnsVisible(
                [
                    'openedAt',
                    'positionPhase',
                    'openQuantity',
                    'lastPrice',
                    'entryPrice',
                    'takeProfitTier1',
                    'takeProfitTier2',
                    'stopLoss'
                ],
                false
            );
            return;
        }
        this.positionsGridApi.setColumnsVisible(
            [
                'openedAt',
                'positionPhase',
                'openQuantity',
                'lastPrice',
                'entryPrice',
                'deltaPercent',
                'positionEntryNotional'
            ],
            true
        );
        this.positionsGridApi.setColumnsVisible(['takeProfitTier1', 'takeProfitTier2', 'stopLoss'], !isNarrowViewport);
    }

    public openDetails(row: TradingPositionPayload | null): void {
        this.selectedPosition.set(row ?? null);
        this.cachedOriginBuyTrade = null;
        this.selectedAnalytics.set(null);
        this.detailsVisible.set(true);

        if (row && row.evaluation_id) {
            this.apiService.getEvaluationById(row.evaluation_id).subscribe({
                next: (evalData) => {
                    this.selectedAnalytics.set(evalData);
                    this.recomputeCharts();
                },
                error: (error) => {
                    console.error('[UI][POSITIONS][DETAILS] Failed to load analytics for pair', error);
                }
            });
        }

        this.cachedOriginBuyTrade = this.findOriginBuyTrade(row);
        this.recomputeCharts();
    }

    public phaseSeverity(phase: string | null | undefined): 'success' | 'info' | 'warn' | 'danger' | 'secondary' {
        if (!phase) {
            return 'secondary';
        }
        if (phase === 'OPEN') {
            return 'info';
        }
        if (phase === 'PARTIAL') {
            return 'warn';
        }
        if (phase === 'CLOSED' || phase === 'STALED') {
            return 'secondary';
        }
        return 'secondary';
    }

    private computeDeltaPercent(row: TradingPositionPayload | null): number | null {
        if (!row) {
            return null;
        }
        const enriched = this.numberFormattingService.toNumberSafe((row as any).priceChangePercent as number | null);
        if (enriched !== null) {
            return enriched;
        }
        const last = this.numberFormattingService.toNumberSafe((row as any).last_price as number | null);
        const entry = this.numberFormattingService.toNumberSafe(row.entry_price);
        if (last === null || entry === null || entry === 0) {
            return null;
        }
        return ((last - entry) / Math.abs(entry)) * 100;
    }

    public deltaPercent(row: TradingPositionPayload | null): number {
        return this.computeDeltaPercent(row) ?? 0;
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

    private resolveTakeProfitStopLossPriceStackMainLineCssClass(
        priceStackKind: 'take_profit_tier_one' | 'take_profit_tier_two' | 'stop_loss'
    ): string {
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

    private formatPositionNotionalCellHtml(row: TradingPositionPayload | undefined): string {
        if (row == null) {
            return '—';
        }
        const entryNotionalUsd = this.orderNotionalUsd(row, 'entry');
        const lastNotionalUsd = this.orderNotionalUsd(row, 'last');
        const entryNotionalLabel =
            entryNotionalUsd == null
                ? '—'
                : this.numberFormattingService.formatCurrency(entryNotionalUsd, 'USD', 0, 2);
        const lastNotionalLabel =
            lastNotionalUsd == null
                ? '—'
                : this.numberFormattingService.formatCurrency(lastNotionalUsd, 'USD', 0, 2);
        const deltaPercent = this.computeDeltaPercent(row);
        let liveToneClass = 'poseidon-grid-notional-live poseidon-grid-notional-live--neutral';
        if (deltaPercent != null && deltaPercent > 0) {
            liveToneClass = 'poseidon-grid-notional-live poseidon-grid-notional-live--positive';
        } else if (deltaPercent != null && deltaPercent < 0) {
            liveToneClass = 'poseidon-grid-notional-live poseidon-grid-notional-live--negative';
        }
        if (entryNotionalUsd == null && lastNotionalUsd == null) {
            return '—';
        }
        if (entryNotionalUsd == null) {
            return `<span class="${liveToneClass} poseidon-grid-emphasized-metric">${lastNotionalLabel}</span>`;
        }
        return `<div class="poseidon-grid-notional-stack"><span class="poseidon-grid-notional-entry-struck">${entryNotionalLabel}</span><span class="${liveToneClass} poseidon-grid-emphasized-metric">${lastNotionalLabel}</span></div>`;
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

    public entryPositionPercentage(row: TradingPositionPayload | null): number {
        return this.pricePositionPercentage(row, this.numberFormattingService.toNumberSafe((row as any)?.entry_price));
    }

    public tp1PositionPercentage(row: TradingPositionPayload | null): number {
        return this.pricePositionPercentage(row, this.numberFormattingService.toNumberSafe((row as any)?.take_profit_tier_1_price));
    }

    public orderNotionalUsd(row: TradingPositionPayload | null, priceBasis: 'entry' | 'last'): number | null {
        if (!row) {
            return null;
        }
        const quantity = this.numberFormattingService.toNumberSafe(row.open_quantity);
        const price =
            priceBasis === 'entry'
                ? this.numberFormattingService.toNumberSafe(row.entry_price)
                : this.numberFormattingService.toNumberSafe((row as any).last_price as number | null);
        if (quantity === null || price === null) {
            return null;
        }
        return quantity * price;
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

    private findOriginBuyTrade(position: TradingPositionPayload | null): TradingTradePayload | null {
        if (!position) {
            return null;
        }
        const trades = (this.webSocketService.trades() ?? []) as TradingTradePayload[];
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

    public buyTradeForSelectedPosition(): TradingTradePayload | null {
        return this.cachedOriginBuyTrade;
    }

    public focusTradeInTable(_trade: TradingTradePayload): void {}

    public formatNumber(value: unknown, min: number, max: number): string {
        return this.numberFormattingService.formatNumber(value as number, min, max);
    }

    public formatCurrency(value: unknown, code: string, min: number, max: number): string {
        return this.numberFormattingService.formatCurrency(value as number, code, min, max);
    }

    public formatPercent(value: number | null | undefined): string {
        if (value == null) {
            return '—';
        }
        return `${this.numberFormattingService.formatNumber(value, 2, 2)}%`;
    }

    private recomputeCharts(): void {
        const pos = this.selectedPosition();
        const a = this.selectedAnalytics();

        const scoreValues: number[] = [];
        const scoreLabels: string[] = [];
        const pushScore = (label: string, raw: number | null | undefined): void => {
            if (raw == null) {
                return;
            }
            scoreLabels.push(label);
            scoreValues.push(raw);
        };
        pushScore('Quality', (a as any)?.scores?.quality_score);
        pushScore('AI adjusted', (a as any)?.scores?.ai_adjusted_quality_score);
        this.scoresLabels = scoreLabels;
        this.scoresSeries = scoreValues;

        const pct5m = this.toNumberSafe((a as any)?.fundamentals?.price_change_percentage_m5);
        const pct1h = this.toNumberSafe((a as any)?.fundamentals?.price_change_percentage_h1);
        const pct24h = this.toNumberSafe((a as any)?.fundamentals?.price_change_percentage_h24);
        const deltas: number[] = [pct5m ?? 0, pct1h ?? 0, pct24h ?? 0];
        this.deltaSeries = [{name: 'Δ', data: deltas}];
        this.deltaColors = deltas.map((v) => (v >= 0 ? '#22c55e' : '#ef4444'));

        const liq = this.toNumberSafe((a as any)?.fundamentals?.liquidity_usd) ?? 0;
        const vol = this.toNumberSafe((a as any)?.fundamentals?.volume_h24_usd) ?? 0;
        this.liqVolSeries = [Math.max(liq, 0), Math.max(vol, 0)];

        const prob = this.toPercent0to100((a as any)?.ai?.ai_probability_take_profit_before_stop_loss ?? null);
        this.probSeries = Number.isFinite(prob) ? [prob] : [];

        const entryNotional = this.orderNotionalUsd(pos, 'entry') ?? 0;
        const lastNotional = this.orderNotionalUsd(pos, 'last') ?? 0;
        this.notionalSeries = [{name: 'Notional', data: [entryNotional, lastNotional]}];
    }

    private toPercent0to100(value: number | null | undefined): number {
        if (value == null) {
            return 0;
        }
        if (value <= 1 && value >= 0) {
            return value * 100;
        }
        return value;
    }

    private toNumberSafe(value: unknown): number | null {
        return this.numberFormattingService.toNumberSafe(value as number | null);
    }
}
