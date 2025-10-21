import { CommonModule } from '@angular/common';
import { Component, computed, effect, inject, signal, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AgGridAngular } from 'ag-grid-angular';
import type { ColDef, GridApi, GridReadyEvent, RowClickedEvent } from 'ag-grid-community';
import type {
    ApexAxisChartSeries,
    ApexChart,
    ApexDataLabels,
    ApexGrid,
    ApexLegend,
    ApexMarkers,
    ApexNonAxisChartSeries,
    ApexStroke,
    ApexTheme,
    ApexTooltip,
    ApexXAxis,
    ApexYAxis,
} from 'ng-apexcharts';
import { NgApexchartsModule } from 'ng-apexcharts';
import { ButtonModule } from 'primeng/button';
import { CardModule } from 'primeng/card';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { balhamDarkThemeCompact } from '../../ag-grid.theme';
import { Analytics } from '../../core/models';
import { WebSocketService } from '../../core/websocket.service';

@Component({
    standalone: true,
    selector: 'app-analytics',
    imports: [CommonModule, FormsModule, AgGridAngular, NgApexchartsModule, DialogModule, ButtonModule, CardModule, InputTextModule],
    templateUrl: './analytics.component.html',
})
export class AnalyticsComponent {
    private readonly ws = inject(WebSocketService);
    public readonly agGridTheme = balhamDarkThemeCompact;

    public readonly analytics = signal<Analytics[]>([]);
    public quickFilterText = '';

    public constructor() {
        effect(() => {
            const data = this.ws.analytics();
            this.analytics.set(data);
            this.rebuildAllCharts();
        });
    }

    public readonly kpiTotal = computed(() => this.analytics().length);
    public readonly kpiAverageFinal = computed(() => {
        const rows = this.analytics();
        return rows.length ? rows.reduce((sum, row) => sum + (row.scores?.final ?? 0), 0) / rows.length : 0;
    });
    public readonly kpiWithAi = computed(
        () => this.analytics().filter((r) => (r.ai?.probabilityTp1BeforeSl ?? 0) > 0 || (r.ai?.qualityScoreDelta ?? 0) !== 0).length
    );

    private readonly outcomeRows = computed(() => this.analytics().filter((r) => r?.outcome?.hasOutcome === true));
    public readonly kpiOutCount = computed(() => this.outcomeRows().length);
    public readonly kpiOutWinRate = computed(() => {
        const rows = this.outcomeRows();
        if (!rows.length) return 0;
        const wins = rows.filter((r) => !!r.outcome?.wasProfit).length;
        return (wins / rows.length) * 100;
    });
    public readonly kpiOutAvgPct = computed(() => {
        const rows = this.outcomeRows();
        if (!rows.length) return 0;
        return rows.reduce((sum, row) => sum + Number(row.outcome?.pnlPct ?? 0), 0) / rows.length;
    });

    @ViewChild(AgGridAngular) grid?: AgGridAngular;
    private gridApi?: GridApi<Analytics>;

    public readonly columnDefs: ColDef[] = [
        { headerName: 'When', valueGetter: (p) => p.data.evaluatedAt, sort: 'desc', sortable: true, filter: 'agTextColumnFilter', width: 170 },
        { headerName: 'Symbol', field: 'symbol', sortable: true, filter: 'agTextColumnFilter', width: 110 },
        {
            headerName: 'Final',
            valueGetter: (p) => p.data.scores?.final,
            sortable: true,
            filter: 'agNumberColumnFilter',
            width: 100,
            valueFormatter: (p) => (p.value ?? 0).toFixed(2),
        },
        {
            headerName: 'Q',
            valueGetter: (p) => p.data.scores?.quality,
            sortable: true,
            filter: 'agNumberColumnFilter',
            width: 90,
            valueFormatter: (p) => (p.value ?? 0).toFixed(2),
        },
        {
            headerName: 'Stat',
            valueGetter: (p) => p.data.scores?.statistics,
            sortable: true,
            filter: 'agNumberColumnFilter',
            width: 90,
            valueFormatter: (p) => (p.value ?? 0).toFixed(2),
        },
        {
            headerName: 'Entry',
            valueGetter: (p) => p.data.scores?.entry,
            sortable: true,
            filter: 'agNumberColumnFilter',
            width: 90,
            valueFormatter: (p) => (p.value ?? 0).toFixed(2),
        },
        {
            headerName: 'AI Prob.',
            valueGetter: (p) => p.data.ai?.probabilityTp1BeforeSl,
            sortable: true,
            filter: 'agNumberColumnFilter',
            width: 110,
            valueFormatter: (p) => (p.value ?? 0).toFixed(2),
        },
        {
            headerName: 'AI ΔQ',
            valueGetter: (p) => p.data.ai?.qualityScoreDelta,
            sortable: true,
            filter: 'agNumberColumnFilter',
            width: 100,
            valueFormatter: (p) => (p.value ?? 0).toFixed(2),
        },
        { headerName: 'Age(h)', valueGetter: (p) => p.data.rawMetrics?.tokenAgeHours, sortable: true, filter: 'agNumberColumnFilter', width: 100 },
        { headerName: 'Vol $', valueGetter: (p) => p.data.rawMetrics?.volume24hUsd, sortable: true, filter: 'agNumberColumnFilter', width: 110 },
        { headerName: 'Liq $', valueGetter: (p) => p.data.rawMetrics?.liquidityUsd, sortable: true, filter: 'agNumberColumnFilter', width: 110 },
        { headerName: 'Decision', valueGetter: (p) => p.data.decision?.action, sortable: true, filter: 'agTextColumnFilter', width: 110 },
        { headerName: 'Reason', valueGetter: (p) => p.data.decision?.reason, sortable: true, filter: 'agTextColumnFilter', flex: 1, minWidth: 220 },
        {
            headerName: 'Outcome %',
            valueGetter: (p) => (p.data.outcome?.hasOutcome ? p.data.outcome?.pnlPct ?? null : null),
            sortable: true,
            filter: 'agNumberColumnFilter',
            width: 120,
            valueFormatter: (p) => (p.value == null ? '' : Number(p.value).toFixed(2)),
        },
    ];
    public readonly defaultColDef: ColDef = { resizable: true, floatingFilter: true };
    public rowData = computed(() => this.analytics());

    public onGridReady(event: GridReadyEvent): void {
        this.gridApi = event.api as GridApi<Analytics>;
        (this.gridApi as any).setGridOption?.('quickFilterText', this.quickFilterText);
    }

    public onQuickFilterChange(value: string): void {
        this.quickFilterText = value;
        this.gridApi && (this.gridApi as any).setGridOption?.('quickFilterText', value);
    }

    public onRowClicked(event: RowClickedEvent<Analytics>): void {
        this.selected.set(event.data);
        this.rawVisible = true;
    }

    private readonly apexTheme: ApexTheme = { mode: 'dark', palette: 'palette1' as any };
    private readonly apexGrid: ApexGrid = { borderColor: 'rgba(255,255,255,0.06)', xaxis: { lines: { show: false } } };
    private readonly darkTooltip: ApexTooltip = { theme: 'dark' };

    public histSeries: ApexAxisChartSeries | ApexNonAxisChartSeries = [{ name: 'Rows', data: [] }];
    public histChart: ApexChart = { type: 'bar', height: 260, toolbar: { show: false } };
    public histXAxis: ApexXAxis = { categories: [], title: { text: 'Final score buckets' } };
    public histYAxis: ApexYAxis = { title: { text: 'Count' } };
    public histDataLabels: ApexDataLabels = { enabled: false };
    public histTooltip: ApexTooltip = this.darkTooltip;
    public histLegend: ApexLegend = { show: false };
    public histGrid: ApexGrid = this.apexGrid;
    public histTheme: ApexTheme = this.apexTheme;

    public calibSeries: ApexAxisChartSeries | ApexNonAxisChartSeries = [{ name: 'Observed buy-rate (%)', data: [] }];
    public calibChart: ApexChart = { type: 'line', height: 260, toolbar: { show: false } };
    public calibXAxis: ApexXAxis = { categories: [], title: { text: 'Predicted probability bucket' } };
    public calibYAxis: ApexYAxis = { title: { text: 'Buy-rate (%)' }, max: 100, min: 0 };
    public calibMarkers: ApexMarkers = { size: 4 };
    public calibStroke: ApexStroke = { width: 2 };
    public calibTooltip: ApexTooltip = this.darkTooltip;
    public calibLegend: ApexLegend = { show: true };
    public calibGrid: ApexGrid = this.apexGrid;
    public calibTheme: ApexTheme = this.apexTheme;

    public ageSeries: ApexAxisChartSeries | ApexNonAxisChartSeries = [{ name: 'Candidates', data: [] }];
    public ageChart: ApexChart = { type: 'scatter', height: 260, zoom: { enabled: true, type: 'xy' } };
    public ageXAxis: ApexXAxis = { title: { text: 'Token age (hours)' } };
    public ageYAxis: ApexYAxis = { title: { text: 'Final score' } };
    public ageMarkers: ApexMarkers = { size: 4 };
    public ageStroke: ApexStroke = { width: 1 };
    public ageTooltip: ApexTooltip = this.darkTooltip;
    public ageLegend: ApexLegend = { show: false };
    public ageGrid: ApexGrid = this.apexGrid;
    public ageTheme: ApexTheme = this.apexTheme;

    public heatSeries: { name: string; data: { x: string; y: number }[] }[] = [];
    public heatChart: ApexChart = { type: 'heatmap', height: 300, toolbar: { show: false } };
    public heatXAxis: ApexXAxis = { title: { text: 'Volume 24h buckets ($)' }, categories: [] };
    public heatYAxis: ApexYAxis = { title: { text: 'Liquidity buckets ($)' } };
    public heatDataLabels: ApexDataLabels = { enabled: false };
    public heatTooltip: ApexTooltip = this.darkTooltip;
    public heatLegend: ApexLegend = { show: false };
    public heatGrid: ApexGrid = this.apexGrid;
    public heatTheme: ApexTheme = this.apexTheme;

    public outHistSeries: ApexAxisChartSeries | ApexNonAxisChartSeries = [{ name: 'Rows', data: [] }];
    public outHistChart: ApexChart = { type: 'bar', height: 260, toolbar: { show: false } };
    public outHistXAxis: ApexXAxis = { categories: [], title: { text: 'Outcome PnL% buckets' } };
    public outHistYAxis: ApexYAxis = { title: { text: 'Count' } };
    public outHistDataLabels: ApexDataLabels = { enabled: false };
    public outHistTooltip: ApexTooltip = this.darkTooltip;
    public outHistLegend: ApexLegend = { show: false };
    public outHistGrid: ApexGrid = this.apexGrid;
    public outHistTheme: ApexTheme = this.apexTheme;

    public winByScoreSeries: ApexAxisChartSeries | ApexNonAxisChartSeries = [{ name: 'Win-rate (%)', data: [] }];
    public winByScoreChart: ApexChart = { type: 'line', height: 260, toolbar: { show: false } };
    public winByScoreXAxis: ApexXAxis = { categories: [], title: { text: 'Final score bucket' } };
    public winByScoreYAxis: ApexYAxis = { title: { text: 'Win-rate (%)' }, min: 0, max: 100 };
    public winByScoreMarkers: ApexMarkers = { size: 4 };
    public winByScoreStroke: ApexStroke = { width: 2 };
    public winByScoreTooltip: ApexTooltip = this.darkTooltip;
    public winByScoreLegend: ApexLegend = { show: true };
    public winByScoreGrid: ApexGrid = this.apexGrid;
    public winByScoreTheme: ApexTheme = this.apexTheme;

    public holdScatterSeries: ApexAxisChartSeries | ApexNonAxisChartSeries = [{ name: 'Outcomes', data: [] }];
    public holdScatterChart: ApexChart = { type: 'scatter', height: 260, zoom: { enabled: true, type: 'xy' } };
    public holdScatterXAxis: ApexXAxis = { title: { text: 'Holding (minutes)' } };
    public holdScatterYAxis: ApexYAxis = { title: { text: 'PnL (%)' } };
    public holdScatterMarkers: ApexMarkers = { size: 4 };
    public holdScatterStroke: ApexStroke = { width: 1 };
    public holdScatterTooltip: ApexTooltip = this.darkTooltip;
    public holdScatterLegend: ApexLegend = { show: false };
    public holdScatterGrid: ApexGrid = this.apexGrid;
    public holdScatterTheme: ApexTheme = this.apexTheme;

    public outHeatSeries: { name: string; data: { x: string; y: number }[] }[] = [];
    public outHeatChart: ApexChart = { type: 'heatmap', height: 300, toolbar: { show: false } };
    public outHeatXAxis: ApexXAxis = { title: { text: 'Volume 24h buckets ($)' }, categories: [] };
    public outHeatYAxis: ApexYAxis = { title: { text: 'Liquidity buckets ($)' } };
    public outHeatDataLabels: ApexDataLabels = { enabled: false };
    public outHeatTooltip: ApexTooltip = this.darkTooltip;
    public outHeatLegend: ApexLegend = { show: false };
    public outHeatGrid: ApexGrid = this.apexGrid;
    public outHeatTheme: ApexTheme = this.apexTheme;

    public rawVisible = false;
    public readonly selected = signal<Analytics | undefined>(undefined);

    private rebuildAllCharts(): void {
        this.buildHistogram();
        this.buildCalibration();
        this.buildAgeScatter();
        this.buildHeatmap();

        this.buildOutcomeHistogram();
        this.buildWinRateByScore();
        this.buildHoldingScatter();
        this.buildOutcomeHeatmap();
    }

    private buildHistogram(): void {
        const values = this.analytics().map((r) => r.scores?.final ?? 0);
        if (!values.length) {
            this.histSeries = [{ name: 'Rows', data: [] }];
            this.histXAxis = { categories: [] };
            return;
        }
        const { counts, labels } = this.makeHistogram(values, 12);
        this.histSeries = [{ name: 'Rows', data: counts }];
        this.histXAxis = { categories: labels, title: { text: 'Final score buckets' } };
    }

    private buildCalibration(): void {
        const rows = this.analytics();
        const probabilities = rows.map((r) => Number(r.ai?.probabilityTp1BeforeSl ?? 0));
        if (!probabilities.length) {
            this.calibSeries = [{ name: 'Observed buy-rate (%)', data: [] }];
            this.calibXAxis = { categories: [] };
            return;
        }
        const binCount = 10;
        const { edges, indexOf, labels } = this.makeBins(probabilities, binCount);
        const totals = Array.from({ length: binCount }, () => 0);
        const buys = Array.from({ length: binCount }, () => 0);
        for (const row of rows) {
            const i = indexOf(Number(row.ai?.probabilityTp1BeforeSl ?? 0));
            totals[i] += 1;
            if ((row.decision?.action ?? '') === 'BUY') {
                buys[i] += 1;
            }
        }
        const rate = totals.map((n, i) => (n ? (buys[i] / n) * 100 : 0));
        this.calibSeries = [{ name: 'Observed buy-rate (%)', data: rate }];
        this.calibXAxis = {
            categories: labels ?? edges.slice(0, -1).map((e, i) => `${e.toFixed(2)}–${edges[i + 1].toFixed(2)}`),
            title: { text: 'Predicted probability bucket' },
        };
    }

    private buildAgeScatter(): void {
        const points = this.analytics().map((r) => ({
            x: Number(r.rawMetrics?.tokenAgeHours ?? 0),
            y: Number(r.scores?.final ?? 0),
            name: r.symbol,
        }));
        this.ageSeries = [{ name: 'Candidates', data: points }];
    }

    private buildHeatmap(): void {
        const rows = this.analytics();
        this.heatSeries = this.makeXYHeat(
            rows.map((r) => Number(r.rawMetrics?.volume24hUsd ?? 0)),
            rows.map((r) => Number(r.rawMetrics?.liquidityUsd ?? 0)),
            rows.map((r) => Number(r.scores?.final ?? 0)),
            8,
            6
        );
    }

    private buildOutcomeHistogram(): void {
        const values = this.outcomeRows().map((r) => Number(r.outcome?.pnlPct ?? 0));
        if (!values.length) {
            this.outHistSeries = [{ name: 'Rows', data: [] }];
            this.outHistXAxis = { categories: [] };
            return;
        }
        const { counts, labels } = this.makeHistogram(values, 12);
        this.outHistSeries = [{ name: 'Rows', data: counts }];
        this.outHistXAxis = { categories: labels, title: { text: 'Outcome PnL% buckets' } };
    }

    private buildWinRateByScore(): void {
        const rows = this.outcomeRows();
        if (!rows.length) {
            this.winByScoreSeries = [{ name: 'Win-rate (%)', data: [] }];
            this.winByScoreXAxis = { categories: [] };
            return;
        }
        const finals = rows.map((r) => Number(r.scores?.final ?? 0));
        const binCount = 10;
        const { edges, indexOf } = this.makeBins(finals, binCount);
        const totals = Array.from({ length: binCount }, () => 0);
        const wins = Array.from({ length: binCount }, () => 0);
        for (const row of rows) {
            const i = indexOf(Number(row.scores?.final ?? 0));
            totals[i] += 1;
            if (row.outcome?.wasProfit) {
                wins[i] += 1;
            }
        }
        const rate = totals.map((n, i) => (n ? (wins[i] / n) * 100 : 0));
        const labels = edges.slice(0, -1).map((e, i) => `${e.toFixed(1)}–${edges[i + 1].toFixed(1)}`);
        this.winByScoreSeries = [{ name: 'Win-rate (%)', data: rate }];
        this.winByScoreXAxis = { categories: labels, title: { text: 'Final score bucket' } };
    }

    private buildHoldingScatter(): void {
        const points = this.outcomeRows().map((r) => ({
            x: Number(r.outcome?.holdingMinutes ?? 0),
            y: Number(r.outcome?.pnlPct ?? 0),
            name: r.symbol,
        }));
        this.holdScatterSeries = [{ name: 'Outcomes', data: points }];
    }

    private buildOutcomeHeatmap(): void {
        const rows = this.outcomeRows();
        this.outHeatSeries = this.makeXYHeat(
            rows.map((r) => Number(r.rawMetrics?.volume24hUsd ?? 0)),
            rows.map((r) => Number(r.rawMetrics?.liquidityUsd ?? 0)),
            rows.map((r) => Number(r.outcome?.pnlPct ?? 0)),
            8,
            6
        );
    }

    private makeBins(values: number[], bins: number) {
        const min = Math.min(...values);
        const max = Math.max(...values);
        const step = (max - min) / (bins || 1) || 1;
        const edges = Array.from({ length: bins + 1 }, (_, i) => min + i * step);
        const indexOf = (v: number) => Math.min(bins - 1, Math.max(0, Math.floor((v - min) / step)));
        const labels = edges.slice(0, -1).map((e, i) => `${e.toFixed(2)}–${edges[i + 1].toFixed(2)}`);
        return { edges, indexOf, labels };
    }

    private makeHistogram(values: number[], bins: number) {
        const { edges, indexOf, labels } = this.makeBins(values, bins);
        const counts = Array.from({ length: bins }, () => 0);
        for (const v of values) counts[indexOf(v)]++;
        return { counts, labels, edges };
    }

    private makeXYHeat(xs: number[], ys: number[], zs: number[], xBins: number, yBins: number) {
        if (!xs.length) return [];
        const mk = (vals: number[], n: number) => {
            const mn = Math.min(...vals);
            const mx = Math.max(...vals);
            const st = (mx - mn) / (n || 1) || 1;
            const ed = Array.from({ length: n + 1 }, (_, i) => mn + i * st);
            const lab = Array.from({ length: n }, (_, i) => `${Math.round(ed[i]).toLocaleString()}–${Math.round(ed[i + 1]).toLocaleString()}`);
            const idx = (v: number) => Math.min(n - 1, Math.max(0, Math.floor((v - mn) / st)));
            return { ed, lab, idx, n };
        };
        const xb = mk(xs, xBins);
        const yb = mk(ys, yBins);
        const sum: number[][] = Array.from({ length: yb.n }, () => Array.from({ length: xb.n }, () => 0));
        const cnt: number[][] = Array.from({ length: yb.n }, () => Array.from({ length: xb.n }, () => 0));
        for (let i = 0; i < xs.length; i++) {
            const ix = xb.idx(xs[i]);
            const iy = yb.idx(ys[i]);
            sum[iy][ix] += zs[i];
            cnt[iy][ix]++;
        }
        const series = yb.lab.map((name, iy) => ({
            name,
            data: cnt[iy].map((n, ix) => ({ x: xb.lab[ix], y: n ? Number((sum[iy][ix] / n).toFixed(2)) : 0 })),
        }));
        this.outHeatXAxis = { title: { text: 'Volume 24h buckets ($)' }, categories: xb.lab };
        this.heatXAxis = { title: { text: 'Volume 24h buckets ($)' }, categories: xb.lab };
        return series;
    }
}
