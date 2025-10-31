import { CommonModule, DatePipe, JsonPipe } from '@angular/common';
import { AfterViewInit, Component, TemplateRef, ViewChild, computed, inject, signal } from '@angular/core';
import { AgGridAngular } from 'ag-grid-angular';
import { CellClassParams, ColDef, ValueFormatterParams, ValueGetterParams } from 'ag-grid-community';

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
    ApexStroke,
    ApexFill,
    ApexResponsive,
    ApexYAxis,
    ApexGrid,
    ApexStates,
    ApexTooltip
} from 'ng-apexcharts';

import { balhamDarkThemeCompact } from '../../ag-grid.theme';
import { NumberFormattingService } from '../../core/number-formatting.service';
import { WebSocketService } from '../../core/websocket.service';
import { Analytics, Position, Trade } from '../../core/models';
import { SymbolChipRendererComponent } from '../../renderers/symbol-chip.renderer';
import { TemplateCellRendererComponent } from '../../renderers/template-cell.renderer';
import { TemplateHeaderRendererComponent } from '../../renderers/template-header.renderer';

/**
 * Positions data-table + details modal with ApexCharts visualizations.
 * Uses existing domain models (Position, Trade, Analytics).
 */
@Component({
    standalone: true,
    selector: 'positions-table',
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
    templateUrl: './positions-table.component.html'
})
export class PositionsTableComponent implements AfterViewInit {
    public readonly agGridTheme = balhamDarkThemeCompact;

    private readonly webSocketService = inject(WebSocketService);
    private readonly numberFormattingService = inject(NumberFormattingService);

    public readonly positionsRowData = computed<Position[]>(() => {
        const rows = this.webSocketService.positions() ?? [];
        return Array.isArray(rows) ? [...(rows as Position[])] : [];
    });

    public columnDefinitions: ColDef<Position>[] = [];
    public readonly defaultColumnDefinition: ColDef<Position> = {
        resizable: true,
        sortable: true,
        filter: true,
        suppressHeaderMenuButton: false,
        flex: 1
    };

    @ViewChild('actionsTemplate', { static: false }) private actionsTemplate?: TemplateRef<unknown>;
    @ViewChild('symbolHeaderTemplate', { static: false }) private symbolHeaderTemplate?: TemplateRef<unknown>;

    public readonly detailsVisible = signal<boolean>(false);
    public readonly selectedPosition = signal<Position | null>(null);
    public readonly selectedAnalytics = signal<Analytics | null>(null);

    private cachedOriginBuyTrade: Trade | null = null;

    // ---- ApexCharts: Scores (radial) ----
    public scoresSeries: ApexNonAxisChartSeries = [];
    public scoresChart: ApexChart = { type: 'radialBar', height: 260 };
    public scoresLabels: string[] = [];
    public scoresPlot: ApexPlotOptions = {
        radialBar: {
            hollow: { size: '22%' },
            dataLabels: { name: { fontSize: '12px' }, value: { fontSize: '16px' } }
        }
    };
    public scoresLegend: ApexLegend = { show: true, position: 'bottom' };

    // ---- ApexCharts: Δ (5m/1h/24h) Bar ----
    public deltaSeries: ApexAxisChartSeries = [];
    public deltaChart: ApexChart = { type: 'bar', height: 260, toolbar: { show: false } };
    public deltaXaxis: ApexXAxis = { categories: ['5m', '1h', '24h'] };
    public deltaPlot: ApexPlotOptions = { bar: { distributed: true, columnWidth: '45%' } };
    public deltaColors: string[] = [];
    public deltaDataLabels: ApexDataLabels = { enabled: true, formatter: (v: number) => `${v.toFixed(2)}%` };

    // ---- ApexCharts: Liquidity vs Volume (donut) ----
    public liqVolSeries: ApexNonAxisChartSeries = [];
    public liqVolChart: ApexChart = { type: 'donut', height: 260 };
    public liqVolLabels: string[] = ['Liquidity (24h)', 'Volume (24h)'];
    public liqVolResponsive: ApexResponsive[] = [
        { breakpoint: 768, options: { chart: { height: 220 }, legend: { position: 'bottom' } } }
    ];

    // ---- ApexCharts: AI Probability (radial) ----
    public probSeries: ApexNonAxisChartSeries = [];
    public probChart: ApexChart = { type: 'radialBar', height: 220 };
    public probPlot: ApexPlotOptions = {
        radialBar: {
            startAngle: -120,
            endAngle: 120,
            hollow: { margin: 0, size: '55%' },
            dataLabels: { name: { show: true }, value: { show: true, formatter: (v: number) => `${v.toFixed(1)}%` } }
        }
    };
    public probLabels: string[] = ['TP1 before SL'];

    // ---- ApexCharts: Notional compare (entry vs last) ----
    public notionalSeries: ApexAxisChartSeries = [];
    public notionalChart: ApexChart = { type: 'bar', height: 220, toolbar: { show: false } };
    public notionalPlot: ApexPlotOptions = { bar: { horizontal: true, barHeight: '60%' } };
    public notionalXaxis: ApexXAxis = { categories: ['Entry', 'Last'] };
    public notionalDataLabels: ApexDataLabels = {
        enabled: true,
        formatter: (v: number) => `$${this.numberFormattingService.formatNumber(v, 0, 0)}`
    };

    // ---- Cosmetics (types-safe) ----
    public grid: ApexGrid = { padding: { left: 8, right: 8 } };
    public stroke: ApexStroke = { width: 2 };
    public fill: ApexFill = { opacity: 0.85 };
    // IMPORTANT: ng-apexcharts v5 typings do not expose `value` on filter. Keep only `type`.
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
                comparator: (a, b) => String(a ?? '').localeCompare(String(b ?? ''), undefined, { sensitivity: 'base' }),
                flex: 1.6,
                headerComponent: this.symbolHeaderTemplate ? TemplateHeaderRendererComponent : undefined,
                headerComponentParams: this.symbolHeaderTemplate ? { template: this.symbolHeaderTemplate } : undefined
            },
            {
                headerName: 'Open date',
                field: 'opened_at' as unknown as keyof Position,
                sortable: true,
                filter: 'agDateColumnFilter',
                valueGetter: (p: ValueGetterParams<Position>) => (p.data as any)?.opened_at ?? null,
                cellClass: 'whitespace-nowrap',
                flex: 1.4
            },
            {
                headerName: 'Quantity',
                field: 'qty',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<Position>) => this.numberFormattingService.formatNumber(p.value, 2, 6),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.3
            },
            {
                headerName: 'Entry',
                field: 'entry',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<Position>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'TP1',
                field: 'tp1',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<Position>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'TP2',
                field: 'tp2',
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<Position>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'Stop',
                field: 'stop' as unknown as keyof Position,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueFormatter: (p: ValueFormatterParams<Position>) =>
                    this.numberFormattingService.formatCurrency(p.value, 'USD', 4, 8),
                cellClass: 'text-right whitespace-nowrap',
                flex: 1.1
            },
            {
                headerName: 'Δ %',
                colId: 'deltaPercent',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<Position>) => this.computeDeltaPercent(p.data ?? null),
                valueFormatter: (p: ValueFormatterParams<Position>) =>
                    p.value == null ? '—' : `${this.numberFormattingService.formatNumber(p.value, 2, 2)}%`,
                cellClassRules: { 'pct-up': (p) => (p.value ?? 0) > 0, 'pct-down': (p) => (p.value ?? 0) < 0 },
                cellClass: 'text-right whitespace-nowrap',
                flex: 0.9
            },
            {
                headerName: 'Phase',
                field: 'phase' as unknown as keyof Position,
                sortable: true,
                cellRenderer: (p: ValueFormatterParams<Position>) => {
                    const sev = this.phaseSeverity(String((p.value as any) ?? ''));
                    const colorClass = sev === 'info' ? 'bg-blue-600' : sev === 'warn' ? 'bg-yellow-600' : 'bg-gray-600';
                    return `<span class="${colorClass} saturate-70 inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs text-white font-semibold">${p.value}</span>`;
                }
            },
            {
                headerName: 'Last price',
                field: 'last_price' as unknown as keyof Position,
                type: 'numericColumn',
                sortable: true,
                filter: 'agNumberColumnFilter',
                valueGetter: (p: ValueGetterParams<Position>) =>
                    this.numberFormattingService.toNumberSafe((p.data as any)?.last_price as number | null),
                valueFormatter: (p: ValueFormatterParams<Position>) =>
                    p.value == null ? '—' : this.numberFormattingService.formatNumber(p.value, 4, 8),
                cellClass: (p: CellClassParams<Position>) => {
                    const direction = (p.data as any)?._lastDir as 'up' | 'down' | null | undefined;
                    if (direction === 'up') return 'text-right whitespace-nowrap price-up';
                    if (direction === 'down') return 'text-right whitespace-nowrap price-down';
                    return 'text-right whitespace-nowrap';
                },
                flex: 1.2
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

    public openDetails(row: Position | null): void {
        this.selectedPosition.set(row ?? null);
        this.cachedOriginBuyTrade = null;
        this.detailsVisible.set(true);

        console.info('[UI][POSITIONS][DETAILS] open', row);
        console.debug('[UI][POSITIONS][DETAILS][VERBOSE] resolving origin BUY trade & analytics…');

        this.cachedOriginBuyTrade = this.findOriginBuyTrade(row);
        this.selectedAnalytics.set(this.findBestAnalyticsForPosition(row));
        this.recomputeCharts();
    }

    public phaseSeverity(phase: string | null | undefined): 'success' | 'info' | 'warn' | 'danger' | 'secondary' {
        if (!phase) return 'secondary';
        if (phase === 'OPEN') return 'info';
        if (phase === 'PARTIAL') return 'warn';
        if (phase === 'CLOSED' || phase === 'STALED') return 'secondary';
        return 'secondary';
    }

    private computeDeltaPercent(row: Position | null): number | null {
        if (!row) return null;
        const enriched = this.numberFormattingService.toNumberSafe((row as any)._changePct as number | null);
        if (enriched !== null) return enriched;
        const last = this.numberFormattingService.toNumberSafe((row as any).last_price as number | null);
        const entry = this.numberFormattingService.toNumberSafe(row.entry);
        if (last === null || entry === null || entry === 0) return null;
        return ((last - entry) / Math.abs(entry)) * 100;
    }
    public deltaPercent(row: Position | null): number {
        return this.computeDeltaPercent(row) ?? 0;
    }

    public orderNotionalUsd(row: Position | null, priceBasis: 'entry' | 'last'): number | null {
        if (!row) return null;
        const quantity = this.numberFormattingService.toNumberSafe(row.qty);
        const price =
            priceBasis === 'entry'
                ? this.numberFormattingService.toNumberSafe(row.entry)
                : this.numberFormattingService.toNumberSafe((row as any).last_price as number | null);
        if (quantity === null || price === null) return null;
        return quantity * price;
    }

    private findBestAnalyticsForPosition(position: Position | null): Analytics | null {
        if (!position) return null;
        const rows = (this.webSocketService.analytics() ?? []) as Analytics[];
        const candidates = rows.filter(
            (a) =>
                (a.pairAddress && a.pairAddress === position.pairAddress) ||
                (a.tokenAddress && a.tokenAddress === position.tokenAddress)
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
    public async copyToClipboard(value: string | undefined | null): Promise<void> {
        if (!value) return;
        try {
            await navigator.clipboard.writeText(value);
            console.info('[UI][POSITIONS][COPY] value copied');
        } catch (error) {
            console.info('[UI][POSITIONS][COPY] failed');
            console.debug('[UI][POSITIONS][COPY][VERBOSE]', error);
        }
    }

    private findOriginBuyTrade(position: Position | null): Trade | null {
        if (!position) return null;
        const trades = (this.webSocketService.trades() ?? []) as Trade[];
        const candidates = trades.filter((t) => t.side === 'BUY' && t.pairAddress === position.pairAddress);
        if (candidates.length === 0) return null;

        const opened = new Date((position as any).opened_at ?? 0).getTime();
        candidates.sort((a, b) => {
            const at = new Date((a as any).created_at ?? 0).getTime();
            const bt = new Date((b as any).created_at ?? 0).getTime();
            return Math.abs(at - opened) - Math.abs(bt - opened);
        });
        console.debug('[UI][POSITIONS][DETAILS][VERBOSE] BUY trade candidates:', candidates.length);
        return candidates[0] ?? null;
    }
    public buyTradeForSelectedPosition(): Trade | null {
        return this.cachedOriginBuyTrade;
    }
    public focusTradeInTable(trade: Trade): void {
        console.info('[UI][POSITIONS][DETAILS] focus BUY trade', trade);
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
        const pos = this.selectedPosition();
        const a = this.selectedAnalytics();

        const scoreValues: number[] = [];
        const scoreLabels: string[] = [];
        const pushScore = (label: string, raw: number | null | undefined): void => {
            if (raw == null) return;
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

        const pct5m = this.toNumberSafe((a as any)?.rawMetrics?.pct5m);
        const pct1h = this.toNumberSafe((a as any)?.rawMetrics?.pct1h);
        const pct24h = this.toNumberSafe((a as any)?.rawMetrics?.pct24h);
        const deltas: number[] = [pct5m ?? 0, pct1h ?? 0, pct24h ?? 0];
        this.deltaSeries = [{ name: 'Δ', data: deltas }];
        this.deltaColors = deltas.map((v) => (v >= 0 ? '#22c55e' : '#ef4444'));

        const liq = this.toNumberSafe((a as any)?.rawMetrics?.liquidityUsd) ?? 0;
        const vol = this.toNumberSafe((a as any)?.rawMetrics?.volume24hUsd) ?? 0;
        this.liqVolSeries = [Math.max(liq, 0), Math.max(vol, 0)];

        const prob = this.toPercent0to100((a as any)?.ai?.probabilityTp1BeforeSl ?? null);
        this.probSeries = Number.isFinite(prob) ? [prob] : [];

        const entryNotional = this.orderNotionalUsd(pos, 'entry') ?? 0;
        const lastNotional = this.orderNotionalUsd(pos, 'last') ?? 0;
        this.notionalSeries = [{ name: 'Notional', data: [entryNotional, lastNotional] }];

        console.debug('[UI][POSITIONS][DETAILS][VERBOSE] charts recomputed');
    }

    private toPercent0to100(value: number | null | undefined): number {
        if (value == null) return 0;
        if (value <= 1 && value >= 0) return value * 100;
        return value;
    }
    private toNumberSafe(value: unknown): number | null {
        return this.numberFormattingService.toNumberSafe(value as number | null);
    }
}
