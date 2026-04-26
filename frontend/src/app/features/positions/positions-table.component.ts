import {CommonModule, DatePipe} from '@angular/common';
import {AfterViewInit, Component, computed, inject, signal, TemplateRef, ViewChild} from '@angular/core';
import {AgGridAngular} from 'ag-grid-angular';
import {CellClassParams, ColDef, ValueFormatterParams, ValueGetterParams} from 'ag-grid-community';

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

import {balhamDarkThemeCompact} from '../../ag-grid.theme';
import {NumberFormattingService} from '../../core/number-formatting.service';
import {WebSocketService} from '../../core/websocket.service';
import {TradingEvaluationPayload, TradingPositionPayload, TradingTradePayload} from '../../core/models';
import {MetricsFormattingService} from '../../core/metrics-formatting.service';

import {SymbolChipRendererComponent} from '../../renderers/symbol-chip.renderer';
import {TemplateCellRendererComponent} from '../../renderers/template-cell.renderer';
import {TemplateHeaderRendererComponent} from '../../renderers/template-header.renderer';
import {ApiService} from '../../api.service';

@Component({
    standalone: true,
    selector: 'positions-table',
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
        NgApexchartsModule
    ],
    templateUrl: './positions-table.component.html',
    styleUrl: './positions-table.component.css'
})
export class PositionsTableComponent implements AfterViewInit {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly webSocketService = inject(WebSocketService);
    private readonly numberFormattingService = inject(NumberFormattingService);
    private readonly metricsFormattingService = inject(MetricsFormattingService);
    private readonly apiService = inject(ApiService);

    public readonly positionsRowData = computed<TradingPositionPayload[]>(() => {
        const rows = this.webSocketService.positions() ?? [];
        return Array.isArray(rows) ? [...(rows as TradingPositionPayload[])] : [];
    });

    public columnDefinitions: ColDef<TradingPositionPayload>[] = [];
    public readonly defaultColumnDefinition: ColDef<TradingPositionPayload> = {
        resizable: true,
        sortable: true,
        filter: true,
        suppressHeaderMenuButton: false,
        flex: 1
    };

    @ViewChild('actionsTemplate', {static: false}) private actionsTemplate?: TemplateRef<unknown>;
    @ViewChild('symbolHeaderTemplate', {static: false}) private symbolHeaderTemplate?: TemplateRef<unknown>;

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
    public probLabels: string[] = ['TP1 before SL'];

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
                headerName: 'Symbol',
                field: 'token_symbol',
                sortable: true,
                filter: true,
                cellRenderer: SymbolChipRendererComponent,
                comparator: (a, b) => String(a ?? '').localeCompare(String(b ?? ''), undefined, {sensitivity: 'base'}),
                flex: 1.6,
                headerComponent: this.symbolHeaderTemplate ? TemplateHeaderRendererComponent : undefined,
                headerComponentParams: this.symbolHeaderTemplate ? {template: this.symbolHeaderTemplate} : undefined
            },
            {
                headerName: 'Open date',
                field: 'opened_at' as unknown as keyof TradingPositionPayload,
                sortable: true,
                sort: 'desc',
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) => (p.data as any)?.opened_at ?? null,
                cellClass: 'whitespace-nowrap',
                flex: 1.4
            },
            {
                headerName: 'Quantity',
                field: 'open_quantity',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) => this.numberFormattingService.formatNumber(p.value, 2, 6),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.3
            },
            {
                headerName: 'Entry',
                field: 'entry_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'TP1',
                field: 'take_profit_tier_1_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'TP2',
                field: 'take_profit_tier_2_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'Stop',
                field: 'stop_loss_price' as unknown as keyof TradingPositionPayload,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'Δ %',
                colId: 'deltaPercent',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) => this.computeDeltaPercent(p.data ?? null),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '—' : `${this.numberFormattingService.formatNumber(p.value, 2, 2)}%`,
                cellClassRules: {'pct-up': (p) => (p.value ?? 0) > 0, 'pct-down': (p) => (p.value ?? 0) < 0},
                cellClass: 'text-right whitespace-nowrap',
                flex: 0.9
            },
            {
                headerName: 'Phase',
                field: 'position_phase' as unknown as keyof TradingPositionPayload,
                sortable: true,
                cellRenderer: (p: ValueFormatterParams<TradingPositionPayload>) => {
                    const sev = this.phaseSeverity(String((p.value as any) ?? ''));
                    const colorClass = sev === 'info' ? 'bg-blue-600' : sev === 'warn' ? 'bg-yellow-600' : 'bg-gray-600';
                    return `<span class="${colorClass} saturate-70 inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs text-white font-semibold">${p.value}</span>`;
                }
            },
            {
                headerName: 'Last price',
                field: 'last_price' as unknown as keyof TradingPositionPayload,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingPositionPayload>) =>
                    this.numberFormattingService.toNumberSafe((p.data as any)?.last_price as number | null),
                valueFormatter: (p: ValueFormatterParams<TradingPositionPayload>) =>
                    p.value == null ? '—' : this.numberFormattingService.formatNumber(p.value, 4, 8),
                cellClass: (p: CellClassParams<TradingPositionPayload>) => {
                    const direction = (p.data as any)?._lastDir as 'up' | 'down' | null | undefined;
                    if (direction === 'up') {
                        return 'text-right whitespace-nowrap price-up';
                    }
                    if (direction === 'down') {
                        return 'text-right whitespace-nowrap price-down';
                    }
                    return 'text-right whitespace-nowrap';
                },
                flex: 1.2
            },
            {
                headerName: 'Actions',
                colId: 'actions',
                pinned: 'right',
                width: 100,
                suppressHeaderMenuButton: true,
                sortable: false,
                filter: false,
                cellRenderer: TemplateCellRendererComponent,
                cellRendererParams: {template: this.actionsTemplate}
            }
        ];
    }

    public openDetails(row: TradingPositionPayload | null): void {
        this.selectedPosition.set(row ?? null);
        this.cachedOriginBuyTrade = null;
        this.selectedAnalytics.set(null);
        this.detailsVisible.set(true);

        console.info('[UI][POSITIONS][DETAILS] open', row);
        console.debug('[UI][POSITIONS][DETAILS][VERBOSE] resolving origin BUY trade & analytics…');

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
        const enriched = this.numberFormattingService.toNumberSafe((row as any)._changePct as number | null);
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
            console.info('[UI][POSITIONS][COPY] value copied');
        } catch (error) {
            console.info('[UI][POSITIONS][COPY] failed');
            console.debug('[UI][POSITIONS][COPY][VERBOSE]', error);
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
        console.debug('[UI][POSITIONS][DETAILS][VERBOSE] BUY trade candidates:', candidates.length);
        return candidates[0] ?? null;
    }

    public buyTradeForSelectedPosition(): TradingTradePayload | null {
        return this.cachedOriginBuyTrade;
    }

    public focusTradeInTable(trade: TradingTradePayload): void {
        console.info('[UI][POSITIONS][DETAILS] focus BUY trade', trade);
    }

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

    public formatMetricLabel(key: string): string {
        return this.metricsFormattingService.formatMetricLabel(key);
    }

    public formatMetricValue(key: string, value: number | null | undefined): string {
        return this.metricsFormattingService.formatMetricValue(key, value);
    }

    public sortedShadowMetrics(snapshot: any): any[] {
        if (!snapshot || !snapshot.evaluated_metrics) {
            return [];
        }
        return [...snapshot.evaluated_metrics].sort((a, b) => (b.decile_win_rate || 0) - (a.decile_win_rate || 0));
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
            const v = this.toPercent0to100(raw);
            scoreLabels.push(label);
            scoreValues.push(v);
        };
        pushScore('Final', (a as any)?.scores?.final);
        pushScore('Quality', (a as any)?.scores?.quality);
        pushScore('Statistics', (a as any)?.scores?.statistics);
        pushScore('Entry', (a as any)?.scores?.entry);
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

        console.debug('[UI][POSITIONS][DETAILS][VERBOSE] charts recomputed');
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
