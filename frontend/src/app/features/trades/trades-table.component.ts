import { CommonModule, DatePipe, JsonPipe } from '@angular/common';
import { AfterViewInit, Component, TemplateRef, ViewChild, computed, inject, signal } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import { ColDef, ValueFormatterParams, ValueGetterParams } from 'ag-grid-community';

import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { TagModule } from 'primeng/tag';
import { DividerModule } from 'primeng/divider';
import { ScrollPanelModule } from 'primeng/scrollpanel';
import { TabsModule } from 'primeng/tabs';
import { CardModule } from 'primeng/card';
import { TooltipModule } from 'primeng/tooltip';
import { PanelModule } from 'primeng/panel';

import {
    NgApexchartsModule,
    ApexChart,
    ApexAxisChartSeries,
    ApexNonAxisChartSeries,
    ApexPlotOptions,
    ApexDataLabels,
    ApexXAxis,
    ApexLegend,
    ApexGrid,
    ApexStates,
    ApexTooltip
} from 'ng-apexcharts';

import { balhamDarkThemeCompact } from '../../ag-grid.theme';
import { NumberFormattingService } from '../../core/number-formatting.service';
import { WebSocketService } from '../../core/websocket.service';
import { Analytics, Trade } from '../../core/models';
import { SymbolChipRendererComponent } from '../../renderers/symbol-chip.renderer';
import { TemplateCellRendererComponent } from '../../renderers/template-cell.renderer';
import { TemplateHeaderRendererComponent } from '../../renderers/template-header.renderer';

/**
 * Trades data-table + details modal with ApexCharts visualizations.
 * Uses Trade + Analytics from the codebase — no extra fields.
 */
@Component({
    standalone: true,
    selector: 'trades-table',
    imports: [
        CommonModule,
        DatePipe,
        JsonPipe,
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

    public readonly tradesRowData = computed<Trade[]>(() => {
        const rows = this.webSocketService.trades() ?? [];
        return Array.isArray(rows) ? [...(rows as Trade[])] : [];
    });

    public columnDefinitions: ColDef<Trade>[] = [];
    public readonly defaultColumnDefinition: ColDef<Trade> = { resizable: true, sortable: true, filter: true, flex: 1 };

    @ViewChild('actionsTemplate', { static: false }) private actionsTemplate?: TemplateRef<unknown>;
    @ViewChild('symbolHeaderTemplate', { static: false }) private symbolHeaderTemplate?: TemplateRef<unknown>;

    public readonly detailsVisible = signal<boolean>(false);
    public readonly selectedTrade = signal<Trade | null>(null);
    public readonly selectedAnalytics = signal<Analytics | null>(null);

    // ---- ApexCharts for Trades ----
    public scoresSeries: ApexNonAxisChartSeries = [];
    public scoresChart: ApexChart = { type: 'radialBar', height: 240 };
    public scoresLabels: string[] = [];
    public scoresPlot: ApexPlotOptions = {
        radialBar: {
            hollow: { size: '22%' },
            dataLabels: { name: { fontSize: '12px' }, value: { fontSize: '16px' } }
        }
    };
    public scoresLegend: ApexLegend = { show: true, position: 'bottom' };

    public deltaSeries: ApexAxisChartSeries = [];
    public deltaChart: ApexChart = { type: 'bar', height: 240, toolbar: { show: false } };
    public deltaXaxis: ApexXAxis = { categories: ['5m', '1h', '24h'] };
    public deltaPlot: ApexPlotOptions = { bar: { distributed: true, columnWidth: '45%' } };
    public deltaColors: string[] = [];
    public deltaDataLabels: ApexDataLabels = { enabled: true, formatter: (v: number) => `${v.toFixed(2)}%` };

    public liqVolSeries: ApexNonAxisChartSeries = [];
    public liqVolChart: ApexChart = { type: 'donut', height: 240 };
    public liqVolLabels: string[] = ['Liquidity (24h)', 'Volume (24h)'];

    public notionalSeries: ApexAxisChartSeries = [];
    public notionalChart: ApexChart = { type: 'bar', height: 200, toolbar: { show: false } };
    public notionalPlot: ApexPlotOptions = { bar: { horizontal: true, barHeight: '60%' } };
    public notionalXaxis: ApexXAxis = { categories: ['Order notional (USD)'] };
    public notionalDataLabels: ApexDataLabels = {
        enabled: true,
        formatter: (v: number) => `$${this.numberFormattingService.formatNumber(v, 0, 0)}`
    };

    public grid: ApexGrid = { padding: { left: 8, right: 8 } };
    // IMPORTANT: typings v5 — keep only `type` in filter.
    public states: ApexStates = { hover: { filter: { type: 'lighten' } } };
    public tooltip: ApexTooltip = { enabled: true };

    public ngAfterViewInit(): void {
        this.columnDefinitions = [
            {
                headerName: 'Symbol',
                field: 'symbol',
                sortable: true,
                filter: true,
                cellRenderer: SymbolChipRendererComponent,
                flex: 1.2,
                headerComponent: this.symbolHeaderTemplate ? TemplateHeaderRendererComponent : undefined,
                headerComponentParams: this.symbolHeaderTemplate ? { template: this.symbolHeaderTemplate } : undefined
            },
            {
                headerName: 'Date',
                field: 'created_at' as unknown as keyof Trade,
                sortable: true,
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams<Trade>) => (p.data as any)?.created_at ?? null,
                flex: 1
            },
            {
                headerName: 'Side',
                field: 'side',
                sortable: true,
                filter: true,
                cellRenderer: (p: ValueFormatterParams<Trade>) => {
                    const v = String(p.value ?? '');
                    const colorClass = v === 'BUY' ? 'bg-teal-600' : 'bg-indigo-500';
                    return `<span class="${colorClass} saturate-70 inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs text-white font-semibold">${v}</span>`;
                },
                flex: 0.5
            },
            {
                headerName: 'Quantity',
                field: 'qty',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<Trade>) => this.numberFormattingService.formatNumber(p.value, 2, 6),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.3
            },
            {
                headerName: 'Price',
                field: 'price',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<Trade>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'P&L',
                field: 'pnl' as unknown as keyof Trade,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<Trade>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 2, 2),
                cellClass: (p: ValueFormatterParams<Trade>) => {
                    const n = this.numberFormattingService.toNumberSafe(p.value as number | null);
                    if (n === null) return 'text-right whitespace-nowrap';
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
                field: 'status' as unknown as keyof Trade,
                sortable: true,
                filter: true,
                flex: 0.5
            },
            {
                headerName: 'Actions',
                colId: 'actions',
                pinned: 'right',
                width: 80,
                suppressHeaderMenuButton: true,
                sortable: false,
                filter: false,
                cellRenderer: TemplateCellRendererComponent,
                cellRendererParams: { template: this.actionsTemplate }
            }
        ];
    }

    public openDetails(row: Trade | null): void {
        this.selectedTrade.set(row ?? null);
        this.detailsVisible.set(true);
        console.info('[UI][TRADES][DETAILS] open', row);
        console.debug('[UI][TRADES][DETAILS][VERBOSE] resolving analytics & charts…');
        this.selectedAnalytics.set(this.findBestAnalyticsForTrade(row));
        this.recomputeCharts();
    }

    private findBestAnalyticsForTrade(trade: Trade | null): Analytics | null {
        if (!trade) return null;
        const rows = (this.webSocketService.analytics() ?? []) as Analytics[];
        const candidates = rows.filter(
            (a) =>
                (a.pairAddress && a.pairAddress === trade.pairAddress) ||
                (a.tokenAddress && a.tokenAddress === trade.tokenAddress)
        );
        if (candidates.length === 0) return null;
        candidates.sort((a, b) => (b.evaluatedAt || '').localeCompare(a.evaluatedAt || ''));
        return candidates[0] ?? null;
    }
    public analyticsForSelected(): Analytics | null {
        return this.selectedAnalytics();
    }

    public dexUrlForPair(row: { chain?: string; pairAddress?: string } | null): string {
        const chain = (row as any)?.chain as string | undefined;
        const pair = row?.pairAddress;
        return chain && pair ? `https://dexscreener.com/${chain}/${pair}` : '';
    }
    public dexUrlForToken(row: { chain?: string; tokenAddress?: string } | null): string {
        const chain = (row as any)?.chain as string | undefined;
        const token = row?.tokenAddress;
        return chain && token ? `https://dexscreener.com/${chain}/${token}` : '';
    }

    public orderNotionalUsd(row: Trade | null): number | null {
        if (!row) return null;
        const q = this.numberFormattingService.toNumberSafe(row.qty);
        const p = this.numberFormattingService.toNumberSafe(row.price);
        if (q === null || p === null) return null;
        return q * p;
    }

    public async copyToClipboard(value: string | undefined | null): Promise<void> {
        if (!value) return;
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
        if (value == null) return '—';
        return `${this.numberFormattingService.formatNumber(value, 2, 2)}%`;
    }

    private recomputeCharts(): void {
        const t = this.selectedTrade();
        const a = this.selectedAnalytics();

        const scoreValues: number[] = [];
        const scoreLabels: string[] = [];
        const toPct = (v: number | null | undefined) => (v == null ? null : v <= 1 && v >= 0 ? v * 100 : v);
        const push = (label: string, v: number | null | undefined) => {
            const n = toPct(v);
            if (n == null) return;
            scoreLabels.push(label);
            scoreValues.push(n);
        };
        push('Final', (a as any)?.scores?.final);
        push('Quality', (a as any)?.scores?.quality);
        push('Statistics', (a as any)?.scores?.statistics);
        push('Entry', (a as any)?.scores?.entry);
        this.scoresLabels = scoreLabels;
        this.scoresSeries = scoreValues;

        const pct5m = this.numberFormattingService.toNumberSafe((a as any)?.rawMetrics?.pct5m) ?? 0;
        const pct1h = this.numberFormattingService.toNumberSafe((a as any)?.rawMetrics?.pct1h) ?? 0;
        const pct24h = this.numberFormattingService.toNumberSafe((a as any)?.rawMetrics?.pct24h) ?? 0;
        const deltas = [pct5m, pct1h, pct24h];
        this.deltaSeries = [{ name: 'Δ', data: deltas }];
        this.deltaColors = deltas.map((v) => (v >= 0 ? '#22c55e' : '#ef4444'));

        const liq = this.numberFormattingService.toNumberSafe((a as any)?.rawMetrics?.liquidityUsd) ?? 0;
        const vol = this.numberFormattingService.toNumberSafe((a as any)?.rawMetrics?.volume24hUsd) ?? 0;
        this.liqVolSeries = [Math.max(liq, 0), Math.max(vol, 0)];

        const notional = this.orderNotionalUsd(t) ?? 0;
        this.notionalSeries = [{ name: 'Notional', data: [notional] }];

        console.debug('[UI][TRADES][DETAILS][VERBOSE] charts recomputed');
    }
}
