import { CommonModule } from '@angular/common';
import { Component, computed, effect, inject, signal, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AgGridAngular } from 'ag-grid-angular';
import type { ColDef, GridApi, GridReadyEvent, RowClickedEvent } from 'ag-grid-community';
import type {
    ApexAxisChartSeries, ApexChart, ApexDataLabels, ApexGrid, ApexLegend, ApexMarkers,
    ApexNonAxisChartSeries, ApexStroke, ApexTheme, ApexTooltip, ApexXAxis, ApexYAxis
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
    templateUrl: './analytics.component.html'
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

    // ---------- KPIs (dataset brut) ----------
    public readonly kpiTotal = computed(() => this.analytics().length);
    public readonly kpiAverageFinal = computed(() => {
        const arr = this.analytics();
        return arr.length ? arr.reduce((s, r) => s + (r.scores?.final ?? 0), 0) / arr.length : 0;
    });
    public readonly kpiWithAi = computed(() =>
        this.analytics().filter(r => (r.ai?.probabilityTp1BeforeSl ?? 0) > 0 || (r.ai?.qualityScoreDelta ?? 0) !== 0).length
    );

    // ---------- KPIs (basées sur outcome) ----------
    private readonly outcomeRows = computed(() => this.analytics().filter(r => r.outcome.hasOutcome));
    public readonly kpiOutCount = computed(() => this.outcomeRows().length);
    public readonly kpiOutWinRate = computed(() => {
        const o = this.outcomeRows();
        if (!o.length) return 0;
        const wins = o.filter(r => !!r.outcome?.wasProfit).length;
        return (wins / o.length) * 100;
    });
    public readonly kpiOutAvgPct = computed(() => {
        const o = this.outcomeRows();
        if (!o.length) return 0;
        return o.reduce((s, r) => s + Number(r.outcome?.pnlPct ?? 0), 0) / o.length;
    });

    // ---------- Grid ----------
    @ViewChild(AgGridAngular) grid?: AgGridAngular;
    private gridApi?: GridApi<Analytics>;

    public readonly columnDefs: ColDef[] = [
        { headerName: 'When', valueGetter: p => p.data.evaluatedAt, sort: 'desc', sortable: true, filter: 'agTextColumnFilter', width: 170 },
        { headerName: 'Symbol', field: 'symbol', sortable: true, filter: 'agTextColumnFilter', width: 110 },
        { headerName: 'Final', valueGetter: p => p.data.scores?.final, sortable: true, filter: 'agNumberColumnFilter', width: 100, valueFormatter: p => (p.value ?? 0).toFixed(2) },
        { headerName: 'Q', valueGetter: p => p.data.scores?.quality, sortable: true, filter: 'agNumberColumnFilter', width: 90, valueFormatter: p => (p.value ?? 0).toFixed(2) },
        { headerName: 'Stat', valueGetter: p => p.data.scores?.statistics, sortable: true, filter: 'agNumberColumnFilter', width: 90, valueFormatter: p => (p.value ?? 0).toFixed(2) },
        { headerName: 'Entry', valueGetter: p => p.data.scores?.entry, sortable: true, filter: 'agNumberColumnFilter', width: 90, valueFormatter: p => (p.value ?? 0).toFixed(2) },
        { headerName: 'AI Prob.', valueGetter: p => p.data.ai?.probabilityTp1BeforeSl, sortable: true, filter: 'agNumberColumnFilter', width: 110, valueFormatter: p => (p.value ?? 0).toFixed(2) },
        { headerName: 'AI ΔQ', valueGetter: p => p.data.ai?.qualityScoreDelta, sortable: true, filter: 'agNumberColumnFilter', width: 100, valueFormatter: p => (p.value ?? 0).toFixed(2) },
        { headerName: 'Age(h)', valueGetter: p => p.data.rawMetrics?.tokenAgeHours, sortable: true, filter: 'agNumberColumnFilter', width: 100 },
        { headerName: 'Vol $', valueGetter: p => p.data.rawMetrics?.volume24hUsd, sortable: true, filter: 'agNumberColumnFilter', width: 110 },
        { headerName: 'Liq $', valueGetter: p => p.data.rawMetrics?.liquidityUsd, sortable: true, filter: 'agNumberColumnFilter', width: 110 },
        { headerName: 'Decision', valueGetter: p => p.data.decision?.action, sortable: true, filter: 'agTextColumnFilter', width: 110 },
        { headerName: 'Reason', valueGetter: p => p.data.decision?.reason, sortable: true, filter: 'agTextColumnFilter', flex: 1, minWidth: 220 },
        {
            headerName: 'Outcome %',
            valueGetter: p => p.data.outcome.hasOutcome ? p.data.outcome?.pnlPct ?? null : null,
            sortable: true,
            filter: 'agNumberColumnFilter',
            width: 120,
            valueFormatter: p => p.value == null ? '' : Number(p.value).toFixed(2)
        }
    ];
    public readonly defaultColDef: ColDef = { resizable: true, floatingFilter: true };
    public rowData = computed(() => this.analytics());

    public onGridReady(e: GridReadyEvent): void {
        this.gridApi = e.api as GridApi<Analytics>;
        (this.gridApi as any).setGridOption?.('quickFilterText', this.quickFilterText);
    }
    public onQuickFilterChange(value: string) {
        this.quickFilterText = value;
        this.gridApi && (this.gridApi as any).setGridOption?.('quickFilterText', value);
    }
    public onRowClicked(e: RowClickedEvent<Analytics>): void {
        this.selected.set(e.data);
        this.rawVisible = true;
    }

    // ---------- Charts (theme & shared) ----------
    private readonly apexTheme: ApexTheme = { mode: 'dark', palette: 'palette1' as any };
    private readonly apexGrid: ApexGrid = { borderColor: 'rgba(255,255,255,0.06)', xaxis: { lines: { show: false } } };
    private readonly darkTooltip: ApexTooltip = { theme: 'dark' };

    // Histogram (Final score)
    public histSeries: ApexAxisChartSeries | ApexNonAxisChartSeries = [{ name: 'Rows', data: [] }];
    public histChart: ApexChart = { type: 'bar', height: 260, toolbar: { show: false } };
    public histXAxis: ApexXAxis = { categories: [], title: { text: 'Final score buckets' } };
    public histYAxis: ApexYAxis = { title: { text: 'Count' } };
    public histDataLabels: ApexDataLabels = { enabled: false };
    public histTooltip: ApexTooltip = this.darkTooltip;
    public histLegend: ApexLegend = { show: false };
    public histGrid: ApexGrid = this.apexGrid;
    public histTheme: ApexTheme = this.apexTheme;

    // Calibration (predicted prob. → observed buy-rate)
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

    // Age vs Final
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

    // Heatmap Final by Volume×Liquidity
    public heatSeries: { name: string; data: { x: string; y: number }[] }[] = [];
    public heatChart: ApexChart = { type: 'heatmap', height: 300, toolbar: { show: false } };
    public heatXAxis: ApexXAxis = { title: { text: 'Volume 24h buckets ($)' }, categories: [] };
    public heatYAxis: ApexYAxis = { title: { text: 'Liquidity buckets ($)' } };
    public heatDataLabels: ApexDataLabels = { enabled: false };
    public heatTooltip: ApexTooltip = this.darkTooltip;
    public heatLegend: ApexLegend = { show: false };
    public heatGrid: ApexGrid = this.apexGrid;
    public heatTheme: ApexTheme = this.apexTheme;

    // -------- Outcome charts --------

    // Outcome PnL% histogram
    public outHistSeries: ApexAxisChartSeries | ApexNonAxisChartSeries = [{ name: 'Rows', data: [] }];
    public outHistChart: ApexChart = { type: 'bar', height: 260, toolbar: { show: false } };
    public outHistXAxis: ApexXAxis = { categories: [], title: { text: 'Outcome PnL% buckets' } };
    public outHistYAxis: ApexYAxis = { title: { text: 'Count' } };
    public outHistDataLabels: ApexDataLabels = { enabled: false };
    public outHistTooltip: ApexTooltip = this.darkTooltip;
    public outHistLegend: ApexLegend = { show: false };
    public outHistGrid: ApexGrid = this.apexGrid;
    public outHistTheme: ApexTheme = this.apexTheme;

    // Win-rate by final score
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

    // Holding vs PnL% scatter
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

    // Outcome heatmap PnL% by Volume×Liquidity
    public outHeatSeries: { name: string; data: { x: string; y: number }[] }[] = [];
    public outHeatChart: ApexChart = { type: 'heatmap', height: 300, toolbar: { show: false } };
    public outHeatXAxis: ApexXAxis = { title: { text: 'Volume 24h buckets ($)' }, categories: [] };
    public outHeatYAxis: ApexYAxis = { title: { text: 'Liquidity buckets ($)' } };
    public outHeatDataLabels: ApexDataLabels = { enabled: false };
    public outHeatTooltip: ApexTooltip = this.darkTooltip;
    public outHeatLegend: ApexLegend = { show: false };
    public outHeatGrid: ApexGrid = this.apexGrid;
    public outHeatTheme: ApexTheme = this.apexTheme;

    // RAW dialog
    public rawVisible = false;
    public readonly selected = signal<Analytics | undefined>(undefined);

    // ---------- Builders ----------
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
        const vals = this.analytics().map(r => r.scores?.final ?? 0);
        if (!vals.length) {
            this.histSeries = [{ name: 'Rows', data: [] }];
            this.histXAxis = { categories: [] };
            return;
        }
        const { counts, labels } = this.makeHistogram(vals, 12);
        this.histSeries = [{ name: 'Rows', data: counts }];
        this.histXAxis = { categories: labels, title: { text: 'Final score buckets' } };
    }

    private buildCalibration(): void {
        const rows = this.analytics();
        const probs = rows.map(r => Number(r.ai?.probabilityTp1BeforeSl ?? 0));
        if (!probs.length) {
            this.calibSeries = [{ name: 'Observed buy-rate (%)', data: [] }];
            this.calibXAxis = { categories: [] };
            return;
        }
        const bins = 10;
        const { edges, indexOf, labels } = this.makeBins(probs, bins);
        const totals = Array.from({ length: bins }, () => 0);
        const buys = Array.from({ length: bins }, () => 0);
        for (const r of rows) {
            const i = indexOf(Number(r.ai?.probabilityTp1BeforeSl ?? 0));
            totals[i]++; if ((r.decision?.action ?? '') === 'BUY') buys[i]++;
        }
        const rate = totals.map((n, i) => n ? (buys[i] / n) * 100 : 0);
        this.calibSeries = [{ name: 'Observed buy-rate (%)', data: rate }];
        this.calibXAxis = { categories: labels ?? edges.slice(0, -1).map((e, i) => `${e.toFixed(2)}–${edges[i + 1].toFixed(2)}`), title: { text: 'Predicted probability bucket' } };
    }

    private buildAgeScatter(): void {
        const pts = this.analytics().map(r => ({
            x: Number(r.rawMetrics?.tokenAgeHours ?? 0),
            y: Number(r.scores?.final ?? 0),
            name: r.symbol
        }));
        this.ageSeries = [{ name: 'Candidates', data: pts }];
    }

    private buildHeatmap(): void {
        const rows = this.analytics();
        this.heatSeries = this.makeXYHeat(
            rows.map(r => Number(r.rawMetrics?.volume24hUsd ?? 0)),
            rows.map(r => Number(r.rawMetrics?.liquidityUsd ?? 0)),
            rows.map(r => Number(r.scores?.final ?? 0)),
            8, 6
        );
    }

    // ---- Outcome-based ----
    private buildOutcomeHistogram(): void {
        const vals = this.outcomeRows().map(r => Number(r.outcome?.pnlPct ?? 0));
        if (!vals.length) {
            this.outHistSeries = [{ name: 'Rows', data: [] }];
            this.outHistXAxis = { categories: [] };
            return;
        }
        const { counts, labels } = this.makeHistogram(vals, 12);
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
        const finals = rows.map(r => Number(r.scores?.final ?? 0));
        const bins = 10;
        const { edges, indexOf } = this.makeBins(finals, bins);
        const tot = Array.from({ length: bins }, () => 0);
        const win = Array.from({ length: bins }, () => 0);
        for (const r of rows) {
            const i = indexOf(Number(r.scores?.final ?? 0));
            tot[i]++; if (r.outcome?.wasProfit) win[i]++;
        }
        const rate = tot.map((n, i) => n ? (win[i] / n) * 100 : 0);
        const labels = edges.slice(0, -1).map((e, i) => `${e.toFixed(1)}–${edges[i + 1].toFixed(1)}`);
        this.winByScoreSeries = [{ name: 'Win-rate (%)', data: rate }];
        this.winByScoreXAxis = { categories: labels, title: { text: 'Final score bucket' } };
    }

    private buildHoldingScatter(): void {
        const pts = this.outcomeRows().map(r => ({
            x: Number(r.outcome?.holdingMinutes ?? 0),
            y: Number(r.outcome?.pnlPct ?? 0),
            name: r.symbol
        }));
        this.holdScatterSeries = [{ name: 'Outcomes', data: pts }];
    }

    private buildOutcomeHeatmap(): void {
        const rows = this.outcomeRows();
        this.outHeatSeries = this.makeXYHeat(
            rows.map(r => Number(r.rawMetrics?.volume24hUsd ?? 0)),
            rows.map(r => Number(r.rawMetrics?.liquidityUsd ?? 0)),
            rows.map(r => Number(r.outcome?.pnlPct ?? 0)),
            8, 6
        );
    }

    // ---------- Helpers ----------
    private makeBins(values: number[], bins: number) {
        const min = Math.min(...values), max = Math.max(...values);
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
            const mn = Math.min(...vals), mx = Math.max(...vals);
            const st = (mx - mn) / (n || 1) || 1;
            const ed = Array.from({ length: n + 1 }, (_, i) => mn + i * st);
            const lab = Array.from({ length: n }, (_, i) =>
                `${Math.round(ed[i]).toLocaleString()}–${Math.round(ed[i + 1]).toLocaleString()}`
            );
            const idx = (v: number) => Math.min(n - 1, Math.max(0, Math.floor((v - mn) / st)));
            return { ed, lab, idx, n };
        };
        const xb = mk(xs, xBins), yb = mk(ys, yBins);
        const sum: number[][] = Array.from({ length: yb.n }, () => Array.from({ length: xb.n }, () => 0));
        const cnt: number[][] = Array.from({ length: yb.n }, () => Array.from({ length: xb.n }, () => 0));
        for (let i = 0; i < xs.length; i++) {
            const ix = xb.idx(xs[i]), iy = yb.idx(ys[i]);
            sum[iy][ix] += zs[i]; cnt[iy][ix]++;
        }
        const series = yb.lab.map((name, iy) => ({
            name,
            data: cnt[iy].map((n, ix) => ({ x: xb.lab[ix], y: n ? Number((sum[iy][ix] / n).toFixed(2)) : 0 }))
        }));
        // also expose axis categories for callers that want them
        this.outHeatXAxis = { title: { text: 'Volume 24h buckets ($)' }, categories: xb.lab };
        this.heatXAxis = { title: { text: 'Volume 24h buckets ($)' }, categories: xb.lab };
        return series;
    }
}
