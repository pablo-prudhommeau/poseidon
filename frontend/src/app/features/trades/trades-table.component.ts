import {CommonModule, DatePipe} from '@angular/common';
import {AfterViewInit, Component, computed, inject, signal, TemplateRef, ViewChild} from '@angular/core';
import {AgGridAngular} from 'ag-grid-angular';
import {ColDef, ValueFormatterParams, ValueGetterParams} from 'ag-grid-community';

import {ButtonModule} from 'primeng/button';
import {DialogModule} from 'primeng/dialog';
import {TagModule} from 'primeng/tag';
import {DividerModule} from 'primeng/divider';
import {ScrollPanelModule} from 'primeng/scrollpanel';
import {TabsModule} from 'primeng/tabs';
import {CardModule} from 'primeng/card';
import {TooltipModule} from 'primeng/tooltip';
import {PanelModule} from 'primeng/panel';

import {ApexAxisChartSeries, ApexChart, ApexDataLabels, ApexGrid, ApexLegend, ApexNonAxisChartSeries, ApexPlotOptions, ApexStates, ApexTooltip, ApexXAxis, NgApexchartsModule} from 'ng-apexcharts';

import {balhamDarkThemeCompact} from '../../ag-grid.theme';
import {NumberFormattingService} from '../../core/number-formatting.service';
import {WebSocketService} from '../../core/websocket.service';
import {TradingEvaluationPayload, TradingTradePayload} from '../../core/models';
import {MetricsFormattingService} from '../../core/metrics-formatting.service';

import {SymbolChipRendererComponent} from '../../renderers/symbol-chip.renderer';
import {TemplateCellRendererComponent} from '../../renderers/template-cell.renderer';
import {TemplateHeaderRendererComponent} from '../../renderers/template-header.renderer';
import {ApiService} from '../../api.service';

@Component({
    standalone: true,
    selector: 'trades-table',
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
    templateUrl: './trades-table.component.html'
})
export class TradesTableComponent implements AfterViewInit {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly webSocketService = inject(WebSocketService);
    private readonly numberFormattingService = inject(NumberFormattingService);
    private readonly metricsFormattingService = inject(MetricsFormattingService);
    private readonly apiService = inject(ApiService);

    public readonly tradesRowData = computed<TradingTradePayload[]>(() => {
        const rows = this.webSocketService.trades() ?? [];
        return Array.isArray(rows) ? [...(rows as TradingTradePayload[])] : [];
    });

    public columnDefinitions: ColDef<TradingTradePayload>[] = [];
    public readonly defaultColumnDefinition: ColDef<TradingTradePayload> = {resizable: true, sortable: true, filter: true, flex: 1};

    @ViewChild('actionsTemplate', {static: false}) private actionsTemplate?: TemplateRef<unknown>;
    @ViewChild('symbolHeaderTemplate', {static: false}) private symbolHeaderTemplate?: TemplateRef<unknown>;

    public readonly detailsVisible = signal<boolean>(false);
    public readonly selectedTrade = signal<TradingTradePayload | null>(null);
    public readonly selectedAnalytics = signal<TradingEvaluationPayload | null>(null);

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

    public ngAfterViewInit(): void {
        this.columnDefinitions = [
            {
                headerName: 'Symbol',
                field: 'token_symbol',
                sortable: true,
                filter: true,
                cellRenderer: SymbolChipRendererComponent,
                flex: 1.2,
                headerComponent: this.symbolHeaderTemplate ? TemplateHeaderRendererComponent : undefined,
                headerComponentParams: this.symbolHeaderTemplate ? {template: this.symbolHeaderTemplate} : undefined
            },
            {
                headerName: 'Date',
                field: 'created_at' as unknown as keyof TradingTradePayload,
                sortable: true,
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams<TradingTradePayload>) => (p.data as any)?.created_at ?? null,
                flex: 1
            },
            {
                headerName: 'Side',
                field: 'trade_side',
                sortable: true,
                filter: true,
                cellRenderer: (p: ValueFormatterParams<TradingTradePayload>) => {
                    const v = String(p.value ?? '');
                    const colorClass = v === 'BUY' ? 'bg-teal-600' : 'bg-indigo-500';
                    return `<span class="${colorClass} saturate-70 inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs text-white font-semibold">${v}</span>`;
                },
                flex: 0.5
            },
            {
                headerName: 'Quantity',
                field: 'execution_quantity',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) => this.numberFormattingService.formatNumber(p.value, 2, 6),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.3
            },
            {
                headerName: 'Price',
                field: 'execution_price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'P&L',
                field: 'realized_profit_and_loss' as unknown as keyof TradingTradePayload,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<TradingTradePayload>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 2, 2),
                cellClass: (p: ValueFormatterParams<TradingTradePayload>) => {
                    const n = this.numberFormattingService.toNumberSafe(p.value as number | null);
                    if (n === null) {
                        return 'text-right whitespace-nowrap';
                    }
                    return n > 0
                        ? 'text-right whitespace-nowrap text-green-400'
                        : n < 0
                            ? 'text-right whitespace-nowrap text-red-400'
                            : 'text-right whitespace-nowrap';
                },
                flex: 1
            },
            {
                headerName: 'Status',
                field: 'execution_status' as unknown as keyof TradingTradePayload,
                sortable: true,
                filter: true,
                flex: 0.5
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

    public openDetails(row: TradingTradePayload | null): void {
        this.selectedTrade.set(row ?? null);
        this.selectedAnalytics.set(null);
        this.detailsVisible.set(true);
        console.info('[UI][TRADES][DETAILS] open', row);
        console.debug('[UI][TRADES][DETAILS][VERBOSE] resolving analytics & charts…');

        if (row && row.evaluation_id) {
            this.apiService.getEvaluationById(row.evaluation_id).subscribe({
                next: (evalData) => {
                    this.selectedAnalytics.set(evalData);
                    this.recomputeCharts();
                },
                error: (error) => {
                    console.error('[UI][TRADES][DETAILS] Failed to load analytics for pair', error);
                }
            });
        }
        this.recomputeCharts();
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
            console.info('[UI][TRADES][COPY] value copied');
        } catch (error) {
            console.info('[UI][TRADES][COPY] failed');
            console.debug('[UI][TRADES][COPY][VERBOSE]', error);
        }
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
        const t = this.selectedTrade();
        const a = this.selectedAnalytics();

        const scoreValues: number[] = [];
        const scoreLabels: string[] = [];
        const toPct = (v: number | null | undefined) => (v == null ? null : v <= 1 && v >= 0 ? v * 100 : v);
        const push = (label: string, v: number | null | undefined) => {
            const n = toPct(v);
            if (n == null) {
                return;
            }
            scoreLabels.push(label);
            scoreValues.push(n);
        };
        push('Final', (a as any)?.scores?.final_score);
        push('Quality', (a as any)?.scores?.quality_score);
        push('Statistics', (a as any)?.scores?.statistics_score);
        push('Entry', (a as any)?.scores?.entry_score);
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

        console.debug('[UI][TRADES][DETAILS][VERBOSE] charts recomputed');
    }
}
