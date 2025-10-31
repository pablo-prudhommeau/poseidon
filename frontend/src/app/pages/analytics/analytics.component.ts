// frontend/src/app/pages/analytics/analytics.component.ts
import {CommonModule} from '@angular/common';
import {AfterViewInit, Component, Directive, effect, ElementRef, EventEmitter, inject, OnDestroy, Output, signal} from '@angular/core';
import {FormsModule} from '@angular/forms';

import {ApexAnnotations, ApexAxisChartSeries, ApexChart, ApexDataLabels, ApexFill, ApexGrid, ApexLegend, ApexMarkers, ApexStroke, ApexTooltip, ApexXAxis, ApexYAxis, NgApexchartsModule} from 'ng-apexcharts';

import {CardModule} from 'primeng/card';
import {CheckboxModule} from 'primeng/checkbox';
import {baseTheme} from '../../apex.theme';
import type {Analytics} from '../../core/models';

import {WebSocketService} from '../../core/websocket.service';

/** Emits true/false when the element enters/leaves viewport (lazy build). */
@Directive({selector: '[inViewport]', standalone: true})
export class InViewportDirective implements AfterViewInit, OnDestroy {
    @Output() inViewportChange = new EventEmitter<boolean>();
    private io?: IntersectionObserver;

    constructor(private el: ElementRef<HTMLElement>) {}

    ngAfterViewInit(): void {
        this.io = new IntersectionObserver(([entry]) => this.inViewportChange.emit(entry.isIntersecting), {
            root: null, rootMargin: '200px', threshold: 0.01
        });
        this.io.observe(this.el.nativeElement);
    }

    ngOnDestroy(): void { this.io?.disconnect(); }
}

type XY = { x: number; y: number; meta?: any };
type ChartKey =
    | 'final' | 'quality' | 'statistics' | 'entry'
    | 'liq' | 'vol'
    | 'p5m' | 'p1h' | 'p6h' | 'p24h'
    | 'age' | 'tx';

const CHART_KEYS: ReadonlyArray<ChartKey> = [
    'final', 'quality', 'statistics', 'entry',
    'liq', 'vol',
    'p5m', 'p1h', 'p6h', 'p24h',
    'age', 'tx'
];

@Component({
    selector: 'app-analytics',
    standalone: true,
    imports: [CommonModule, FormsModule, NgApexchartsModule, CardModule, CheckboxModule, InViewportDirective],
    templateUrl: './analytics.component.html'
})
export class AnalyticsComponent {
    private readonly ws = inject(WebSocketService);

    // ===== Dataset
    readonly rows = signal<Analytics[]>([]);

    // ===== Controls (no heavy logic in template)
    readonly yMode = signal<'pct' | 'usd'>('pct');
    readonly showTrend = signal<boolean>(true);
    readonly showQLines = signal<boolean>(true);
    readonly logX = signal<boolean>(true);

    /** Scatter decimation threshold (LTTB). */
    readonly maxScatterPoints = signal<number>(600);

    /** Visibility toggles per card (rebuilt only when visible). */
    visible: Record<ChartKey, boolean> = {
        final: false, quality: false, statistics: false, entry: false,
        liq: false, vol: false,
        p5m: false, p1h: false, p6h: false, p24h: false,
        age: false, tx: false
    };

    constructor() {
        effect(() => {
            const data = (this.ws as any).analytics?.() ?? [];
            if (Array.isArray(data)) {
                this.rows.set(data as Analytics[]);
            }
        });
    }

    // ===== Public API for template (simple & typed)
    onAxisModeChange(mode: 'pct' | 'usd'): void {
        this.yMode.set(mode);
        this.rebuildVisible();
    }

    onToggleTrend(value: boolean): void {
        this.showTrend.set(value);
        this.rebuildVisible();
    }

    onToggleQLines(value: boolean): void {
        this.showQLines.set(value);
        this.rebuildVisible();
    }

    onToggleLogX(value: boolean): void {
        this.logX.set(value);
        // Les courbes X-log sont surtout liq/vol/age/tx, mais rebuildVisible() suffit
        this.rebuildVisible();
    }

    onViewport(kind: ChartKey, isVisible: boolean): void {
        this.visible[kind] = isVisible;
        if (isVisible) {
            this.rebuildOne(kind);
        }
    }

    // ===== Stats utils
    private quantile(sorted: number[], q: number): number {
        if (!sorted.length) {
            return 0;
        }
        const pos = (sorted.length - 1) * q;
        const base = Math.floor(pos);
        const rest = pos - base;
        const next = sorted[base + 1] ?? sorted[base];
        return sorted[base] + (next - sorted[base]) * rest;
    }

    private decileEdges(xs: number[]): number[] {
        const s = [...xs].sort((a, b) => a - b);
        const edges: number[] = [];
        for (let i = 0; i <= 10; i++) {
            edges.push(this.quantile(s, i / 10));
        }
        return edges;
    }

    private binIndex(v: number, edges: number[]): number {
        const last = edges.length - 2;
        if (!isFinite(v)) {
            return 0;
        }
        for (let i = 0; i < edges.length - 1; i++) {
            if (v >= edges[i] && v <= edges[i + 1]) {
                return Math.min(i, last);
            }
        }
        return last;
    }

    private toY(r: Analytics): number {
        return this.yMode() === 'pct' ? (r.outcome?.pnlPct ?? 0) : (r.outcome?.pnlUsd ?? 0);
    }

    private formatLogTick = (raw: number): string => {
        const x = Math.pow(10, raw);
        if (x >= 1_000_000) {
            return `${(x / 1_000_000).toFixed(1)}M`;
        }
        if (x >= 1_000) {
            return `${(x / 1_000).toFixed(1)}K`;
        }
        return x.toFixed(0);
    };

    // ===== LTTB decimation
    private lttb(points: XY[], threshold: number): XY[] {
        const data = points;
        const n = data.length;
        if (threshold >= n || threshold <= 0) {
            return data;
        }

        const sampled: XY[] = [];
        const bucketSize = (n - 2) / (threshold - 2);
        let a = 0;
        sampled.push(data[a]);

        for (let i = 0; i < threshold - 2; i++) {
            const start = Math.floor((i + 1) * bucketSize) + 1;
            const end = Math.floor((i + 2) * bucketSize) + 1;
            const endClamped = Math.min(end, n);

            let avgX = 0, avgY = 0, count = 0;
            for (let j = start; j < endClamped; j++) {
                avgX += data[j].x;
                avgY += data[j].y;
                count++;
            }
            avgX /= Math.max(count, 1);
            avgY /= Math.max(count, 1);

            let maxArea = -1;
            let maxAreaPoint = data[start];
            const ax = data[a].x, ay = data[a].y;
            const rangeStart = Math.floor(i * bucketSize) + 1;
            const rangeEnd = Math.floor((i + 1) * bucketSize) + 1;

            for (let j = rangeStart; j < rangeEnd; j++) {
                const p = data[j];
                const area = Math.abs((ax - avgX) * (p.y - ay) - (ax - p.x) * (avgY - ay)) * 0.5;
                if (area > maxArea) {
                    maxArea = area;
                    maxAreaPoint = p;
                }
            }

            sampled.push(maxAreaPoint);
            a = data.indexOf(maxAreaPoint);
        }

        sampled.push(data[n - 1]);
        return sampled;
    }

    // ===== Builder Scatter + Trend/Q1/Q3
    private buildScatterTrend(
        args: { xName: string; x: (r: Analytics) => number; useLogX?: boolean }
    ) {
        const p = baseTheme();

        // Raw points
        const raw: XY[] = [];
        const xs: number[] = [];
        const ys: number[] = [];
        for (const r of this.rows()) {
            const xRaw = args.x(r);
            const y = this.toY(r);
            if (!Number.isFinite(xRaw) || !Number.isFinite(y)) {
                continue;
            }
            const xPlot = args.useLogX ? Math.log10(Math.max(1e-9, xRaw)) : xRaw;
            raw.push({x: xPlot, y, meta: r});
            xs.push(xPlot);
            ys.push(y);
        }

        // Deciles for trend
        const edges = this.decileEdges(xs);
        const centers: number[] = [];
        const buckets: number[][] = Array.from({length: 10}, () => []);
        for (let i = 0; i < xs.length; i++) {
            buckets[this.binIndex(xs[i], edges)].push(ys[i]);
        }
        for (let i = 0; i < edges.length - 1; i++) {
            centers.push((edges[i] + edges[i + 1]) / 2);
        }

        const med: XY[] = [];
        const q1: XY[] = [];
        const q3: XY[] = [];
        for (let i = 0; i < buckets.length; i++) {
            const arr = buckets[i];
            if (!arr.length) {
                med.push({x: centers[i], y: 0});
                q1.push({x: centers[i], y: 0});
                q3.push({x: centers[i], y: 0});
                continue;
            }
            const s = [...arr].sort((a, b) => a - b);
            med.push({x: centers[i], y: this.quantile(s, 0.5)});
            q1.push({x: centers[i], y: this.quantile(s, 0.25)});
            q3.push({x: centers[i], y: this.quantile(s, 0.75)});
        }

        // Decimation for the scatter only
        const points = this.lttb(raw, this.maxScatterPoints());

        // Options
        const chart: ApexChart = {...p.chart};
        const xaxis: ApexXAxis = {
            title: {text: args.xName},
            labels: {...(args.useLogX ? {formatter: (v) => this.formatLogTick(Number(v))} : {}), style: {fontSize: '11px'}}
        };
        const yaxis: ApexYAxis = {title: {text: this.yMode() === 'pct' ? 'PnL (%)' : 'PnL (USD)'}, labels: {style: {fontSize: '11px'}}};
        const stroke: ApexStroke = p.stroke!;
        const fill: ApexFill = p.fill!;
        const grid: ApexGrid = p.grid!;
        const legend: ApexLegend = p.legend!;
        const tooltip: ApexTooltip = p.tooltip!;
        const markers: ApexMarkers = {...(p.markers ?? {}), size: 2};
        const dataLabels: ApexDataLabels = {...(p.dataLabels ?? {}), enabled: false, style: {fontSize: '11px'}};
        const annotations: ApexAnnotations = {
            yaxis: [{y: 0, borderColor: 'rgba(148,163,184,.6)', strokeDashArray: 4, label: {text: '0', style: {fontSize: '10px', color: '#cbd5e1', background: '#1f2437'}}}]
        };

        const series: ApexAxisChartSeries = [
            {name: 'trades', type: 'scatter', data: points},
            ...(this.showTrend() ? [{name: 'median', type: 'line', data: med}] as ApexAxisChartSeries : []),
            ...(this.showQLines() ? [{name: 'Q1', type: 'line', data: q1}, {name: 'Q3', type: 'line', data: q3}] as ApexAxisChartSeries : [])
        ];

        return {series, chart, xaxis, yaxis, stroke, fill, grid, legend, tooltip, markers, dataLabels, annotations};
    }

    // ===== Chart state (lazy-filled)
    finalSeries: ApexAxisChartSeries = [];
    finalChart: ApexChart = baseTheme().chart;
    finalXAxis: ApexXAxis = {};
    finalYAxis: ApexYAxis = {};
    finalStroke: ApexStroke = baseTheme().stroke;
    finalFill: ApexFill = baseTheme().fill;
    finalGrid: ApexGrid = baseTheme().grid;
    finalLegend: ApexLegend = baseTheme().legend;
    finalTooltip: ApexTooltip = baseTheme().tooltip;
    finalMarkers: ApexMarkers = baseTheme().markers;
    finalDataLabels: ApexDataLabels = baseTheme().dataLabels;
    finalAnn: ApexAnnotations = {};

    qualitySeries: ApexAxisChartSeries = [];
    qualityChart: ApexChart = baseTheme().chart;
    qualityXAxis: ApexXAxis = {};
    qualityYAxis: ApexYAxis = {};
    qualityStroke: ApexStroke = baseTheme().stroke;
    qualityFill: ApexFill = baseTheme().fill;
    qualityGrid: ApexGrid = baseTheme().grid;
    qualityLegend: ApexLegend = baseTheme().legend;
    qualityTooltip: ApexTooltip = baseTheme().tooltip;
    qualityMarkers: ApexMarkers = baseTheme().markers;
    qualityDataLabels: ApexDataLabels = baseTheme().dataLabels;
    qualityAnn: ApexAnnotations = {};

    statisticsSeries: ApexAxisChartSeries = [];
    statisticsChart: ApexChart = baseTheme().chart;
    statisticsXAxis: ApexXAxis = {};
    statisticsYAxis: ApexYAxis = {};
    statisticsStroke: ApexStroke = baseTheme().stroke;
    statisticsFill: ApexFill = baseTheme().fill;
    statisticsGrid: ApexGrid = baseTheme().grid;
    statisticsLegend: ApexLegend = baseTheme().legend;
    statisticsTooltip: ApexTooltip = baseTheme().tooltip;
    statisticsMarkers: ApexMarkers = baseTheme().markers;
    statisticsDataLabels: ApexDataLabels = baseTheme().dataLabels;
    statisticsAnn: ApexAnnotations = {};

    entrySeries: ApexAxisChartSeries = [];
    entryChart: ApexChart = baseTheme().chart;
    entryXAxis: ApexXAxis = {};
    entryYAxis: ApexYAxis = {};
    entryStroke: ApexStroke = baseTheme().stroke;
    entryFill: ApexFill = baseTheme().fill;
    entryGrid: ApexGrid = baseTheme().grid;
    entryLegend: ApexLegend = baseTheme().legend;
    entryTooltip: ApexTooltip = baseTheme().tooltip;
    entryMarkers: ApexMarkers = baseTheme().markers;
    entryDataLabels: ApexDataLabels = baseTheme().dataLabels;
    entryAnn: ApexAnnotations = {};

    liqSeries: ApexAxisChartSeries = [];
    liqChart: ApexChart = baseTheme().chart;
    liqXAxis: ApexXAxis = {};
    liqYAxis: ApexYAxis = {};
    liqStroke: ApexStroke = baseTheme().stroke;
    liqFill: ApexFill = baseTheme().fill;
    liqGrid: ApexGrid = baseTheme().grid;
    liqLegend: ApexLegend = baseTheme().legend;
    liqTooltip: ApexTooltip = baseTheme().tooltip;
    liqMarkers: ApexMarkers = baseTheme().markers;
    liqDataLabels: ApexDataLabels = baseTheme().dataLabels;
    liqAnn: ApexAnnotations = {};

    volSeries: ApexAxisChartSeries = [];
    volChart: ApexChart = baseTheme().chart;
    volXAxis: ApexXAxis = {};
    volYAxis: ApexYAxis = {};
    volStroke: ApexStroke = baseTheme().stroke;
    volFill: ApexFill = baseTheme().fill;
    volGrid: ApexGrid = baseTheme().grid;
    volLegend: ApexLegend = baseTheme().legend;
    volTooltip: ApexTooltip = baseTheme().tooltip;
    volMarkers: ApexMarkers = baseTheme().markers;
    volDataLabels: ApexDataLabels = baseTheme().dataLabels;
    volAnn: ApexAnnotations = {};

    p5mSeries: ApexAxisChartSeries = [];
    p5mChart: ApexChart = baseTheme().chart;
    p5mXAxis: ApexXAxis = {};
    p5mYAxis: ApexYAxis = {};
    p5mStroke: ApexStroke = baseTheme().stroke;
    p5mFill: ApexFill = baseTheme().fill;
    p5mGrid: ApexGrid = baseTheme().grid;
    p5mLegend: ApexLegend = baseTheme().legend;
    p5mTooltip: ApexTooltip = baseTheme().tooltip;
    p5mMarkers: ApexMarkers = baseTheme().markers;
    p5mDataLabels: ApexDataLabels = baseTheme().dataLabels;
    p5mAnn: ApexAnnotations = {};

    p1hSeries: ApexAxisChartSeries = [];
    p1hChart: ApexChart = baseTheme().chart;
    p1hXAxis: ApexXAxis = {};
    p1hYAxis: ApexYAxis = {};
    p1hStroke: ApexStroke = baseTheme().stroke;
    p1hFill: ApexFill = baseTheme().fill;
    p1hGrid: ApexGrid = baseTheme().grid;
    p1hLegend: ApexLegend = baseTheme().legend;
    p1hTooltip: ApexTooltip = baseTheme().tooltip;
    p1hMarkers: ApexMarkers = baseTheme().markers;
    p1hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    p1hAnn: ApexAnnotations = {};

    p6hSeries: ApexAxisChartSeries = [];
    p6hChart: ApexChart = baseTheme().chart;
    p6hXAxis: ApexXAxis = {};
    p6hYAxis: ApexYAxis = {};
    p6hStroke: ApexStroke = baseTheme().stroke;
    p6hFill: ApexFill = baseTheme().fill;
    p6hGrid: ApexGrid = baseTheme().grid;
    p6hLegend: ApexLegend = baseTheme().legend;
    p6hTooltip: ApexTooltip = baseTheme().tooltip;
    p6hMarkers: ApexMarkers = baseTheme().markers;
    p6hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    p6hAnn: ApexAnnotations = {};

    p24hSeries: ApexAxisChartSeries = [];
    p24hChart: ApexChart = baseTheme().chart;
    p24hXAxis: ApexXAxis = {};
    p24hYAxis: ApexYAxis = {};
    p24hStroke: ApexStroke = baseTheme().stroke;
    p24hFill: ApexFill = baseTheme().fill;
    p24hGrid: ApexGrid = baseTheme().grid;
    p24hLegend: ApexLegend = baseTheme().legend;
    p24hTooltip: ApexTooltip = baseTheme().tooltip;
    p24hMarkers: ApexMarkers = baseTheme().markers;
    p24hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    p24hAnn: ApexAnnotations = {};

    ageSeries: ApexAxisChartSeries = [];
    ageChart: ApexChart = baseTheme().chart;
    ageXAxis: ApexXAxis = {};
    ageYAxis: ApexYAxis = {};
    ageStroke: ApexStroke = baseTheme().stroke;
    ageFill: ApexFill = baseTheme().fill;
    ageGrid: ApexGrid = baseTheme().grid;
    ageLegend: ApexLegend = baseTheme().legend;
    ageTooltip: ApexTooltip = baseTheme().tooltip;
    ageMarkers: ApexMarkers = baseTheme().markers;
    ageDataLabels: ApexDataLabels = baseTheme().dataLabels;
    ageAnn: ApexAnnotations = {};

    txSeries: ApexAxisChartSeries = [];
    txChart: ApexChart = baseTheme().chart;
    txXAxis: ApexXAxis = {};
    txYAxis: ApexYAxis = {};
    txStroke: ApexStroke = baseTheme().stroke;
    txFill: ApexFill = baseTheme().fill;
    txGrid: ApexGrid = baseTheme().grid;
    txLegend: ApexLegend = baseTheme().legend;
    txTooltip: ApexTooltip = baseTheme().tooltip;
    txMarkers: ApexMarkers = baseTheme().markers;
    txDataLabels: ApexDataLabels = baseTheme().dataLabels;
    txAnn: ApexAnnotations = {};

    // ===== Helper: rebuild visible charts
    private rebuildVisible(): void {
        CHART_KEYS.forEach(k => {
            if (this.visible[k]) {
                this.rebuildOne(k);
            }
        });
    }

    /** Rebuild one chart (called on visibility or control change) */
    public rebuildOne(kind: ChartKey): void {
        const logX = this.logX();

        const apply = (dst: any, r: any) => {
            dst.series = r.series;
            dst.chart = r.chart;
            dst.xaxis = r.xaxis;
            dst.yaxis = r.yaxis;
            dst.stroke = r.stroke;
            dst.fill = r.fill;
            dst.grid = r.grid;
            dst.legend = r.legend;
            dst.tooltip = r.tooltip;
            dst.markers = r.markers;
            dst.dataLabels = r.dataLabels;
            dst.annotations = r.annotations;
        };

        const map: Record<ChartKey, () => any> = {
            final: () => this.buildScatterTrend({xName: 'Final score', x: a => a.scores?.final ?? 0}),
            quality: () => this.buildScatterTrend({xName: 'Quality score', x: a => a.scores?.quality ?? 0}),
            statistics: () => this.buildScatterTrend({xName: 'Statistics score', x: a => a.scores?.statistics ?? 0}),
            entry: () => this.buildScatterTrend({xName: 'Entry score', x: a => a.scores?.entry ?? 0}),

            liq: () => this.buildScatterTrend({xName: 'Liquidity ($)', x: a => a.rawMetrics?.liquidityUsd ?? 0, useLogX: logX}),
            vol: () => this.buildScatterTrend({xName: 'Volume 24h ($)', x: a => a.rawMetrics?.volume24hUsd ?? 0, useLogX: logX}),

            p5m: () => this.buildScatterTrend({xName: 'Δ5m (%)', x: a => (a as any).rawMetrics?.pct5m ?? 0}),
            p1h: () => this.buildScatterTrend({xName: 'Δ1h (%)', x: a => (a as any).rawMetrics?.pct1h ?? 0}),
            p6h: () => this.buildScatterTrend({xName: 'Δ6h (%)', x: a => (a as any).rawMetrics?.pct6h ?? 0}),
            p24h: () => this.buildScatterTrend({xName: 'Δ24h (%)', x: a => (a as any).rawMetrics?.pct24h ?? 0}),

            age: () => this.buildScatterTrend({xName: 'Token age (h)', x: a => a.rawMetrics?.tokenAgeHours ?? 0, useLogX: logX}),
            tx: () => this.buildScatterTrend({xName: 'Transactions 24h', x: a => (a as any).raw?.dexscreener?.txns24h ?? (a as any).rawDex?.txns24h ?? 0, useLogX: logX})
        };

        const r = map[kind]();
        switch (kind) {
            case 'final':
                apply(this, r);
                this.finalSeries = r.series;
                this.finalChart = r.chart;
                this.finalXAxis = r.xaxis;
                this.finalYAxis = r.yaxis;
                this.finalStroke = r.stroke;
                this.finalFill = r.fill;
                this.finalGrid = r.grid;
                this.finalLegend = r.legend;
                this.finalTooltip = r.tooltip;
                this.finalMarkers = r.markers;
                this.finalDataLabels = r.dataLabels;
                this.finalAnn = r.annotations;
                break;
            case 'quality':
                apply(this, r);
                this.qualitySeries = r.series;
                this.qualityChart = r.chart;
                this.qualityXAxis = r.xaxis;
                this.qualityYAxis = r.yaxis;
                this.qualityStroke = r.stroke;
                this.qualityFill = r.fill;
                this.qualityGrid = r.grid;
                this.qualityLegend = r.legend;
                this.qualityTooltip = r.tooltip;
                this.qualityMarkers = r.markers;
                this.qualityDataLabels = r.dataLabels;
                this.qualityAnn = r.annotations;
                break;
            case 'statistics':
                apply(this, r);
                this.statisticsSeries = r.series;
                this.statisticsChart = r.chart;
                this.statisticsXAxis = r.xaxis;
                this.statisticsYAxis = r.yaxis;
                this.statisticsStroke = r.stroke;
                this.statisticsFill = r.fill;
                this.statisticsGrid = r.grid;
                this.statisticsLegend = r.legend;
                this.statisticsTooltip = r.tooltip;
                this.statisticsMarkers = r.markers;
                this.statisticsDataLabels = r.dataLabels;
                this.statisticsAnn = r.annotations;
                break;
            case 'entry':
                apply(this, r);
                this.entrySeries = r.series;
                this.entryChart = r.chart;
                this.entryXAxis = r.xaxis;
                this.entryYAxis = r.yaxis;
                this.entryStroke = r.stroke;
                this.entryFill = r.fill;
                this.entryGrid = r.grid;
                this.entryLegend = r.legend;
                this.entryTooltip = r.tooltip;
                this.entryMarkers = r.markers;
                this.entryDataLabels = r.dataLabels;
                this.entryAnn = r.annotations;
                break;

            case 'liq':
                apply(this, r);
                this.liqSeries = r.series;
                this.liqChart = r.chart;
                this.liqXAxis = r.xaxis;
                this.liqYAxis = r.yaxis;
                this.liqStroke = r.stroke;
                this.liqFill = r.fill;
                this.liqGrid = r.grid;
                this.liqLegend = r.legend;
                this.liqTooltip = r.tooltip;
                this.liqMarkers = r.markers;
                this.liqDataLabels = r.dataLabels;
                this.liqAnn = r.annotations;
                break;
            case 'vol':
                apply(this, r);
                this.volSeries = r.series;
                this.volChart = r.chart;
                this.volXAxis = r.xaxis;
                this.volYAxis = r.yaxis;
                this.volStroke = r.stroke;
                this.volFill = r.fill;
                this.volGrid = r.grid;
                this.volLegend = r.legend;
                this.volTooltip = r.tooltip;
                this.volMarkers = r.markers;
                this.volDataLabels = r.dataLabels;
                this.volAnn = r.annotations;
                break;

            case 'p5m':
                apply(this, r);
                this.p5mSeries = r.series;
                this.p5mChart = r.chart;
                this.p5mXAxis = r.xaxis;
                this.p5mYAxis = r.yaxis;
                this.p5mStroke = r.stroke;
                this.p5mFill = r.fill;
                this.p5mGrid = r.grid;
                this.p5mLegend = r.legend;
                this.p5mTooltip = r.tooltip;
                this.p5mMarkers = r.markers;
                this.p5mDataLabels = r.dataLabels;
                this.p5mAnn = r.annotations;
                break;
            case 'p1h':
                apply(this, r);
                this.p1hSeries = r.series;
                this.p1hChart = r.chart;
                this.p1hXAxis = r.xaxis;
                this.p1hYAxis = r.yaxis;
                this.p1hStroke = r.stroke;
                this.p1hFill = r.fill;
                this.p1hGrid = r.grid;
                this.p1hLegend = r.legend;
                this.p1hTooltip = r.tooltip;
                this.p1hMarkers = r.markers;
                this.p1hDataLabels = r.dataLabels;
                this.p1hAnn = r.annotations;
                break;
            case 'p6h':
                apply(this, r);
                this.p6hSeries = r.series;
                this.p6hChart = r.chart;
                this.p6hXAxis = r.xaxis;
                this.p6hYAxis = r.yaxis;
                this.p6hStroke = r.stroke;
                this.p6hFill = r.fill;
                this.p6hGrid = r.grid;
                this.p6hLegend = r.legend;
                this.p6hTooltip = r.tooltip;
                this.p6hMarkers = r.markers;
                this.p6hDataLabels = r.dataLabels;
                this.p6hAnn = r.annotations;
                break;
            case 'p24h':
                apply(this, r);
                this.p24hSeries = r.series;
                this.p24hChart = r.chart;
                this.p24hXAxis = r.xaxis;
                this.p24hYAxis = r.yaxis;
                this.p24hStroke = r.stroke;
                this.p24hFill = r.fill;
                this.p24hGrid = r.grid;
                this.p24hLegend = r.legend;
                this.p24hTooltip = r.tooltip;
                this.p24hMarkers = r.markers;
                this.p24hDataLabels = r.dataLabels;
                this.p24hAnn = r.annotations;
                break;

            case 'age':
                apply(this, r);
                this.ageSeries = r.series;
                this.ageChart = r.chart;
                this.ageXAxis = r.xaxis;
                this.ageYAxis = r.yaxis;
                this.ageStroke = r.stroke;
                this.ageFill = r.fill;
                this.ageGrid = r.grid;
                this.ageLegend = r.legend;
                this.ageTooltip = r.tooltip;
                this.ageMarkers = r.markers;
                this.ageDataLabels = r.dataLabels;
                this.ageAnn = r.annotations;
                break;
            case 'tx':
                apply(this, r);
                this.txSeries = r.series;
                this.txChart = r.chart;
                this.txXAxis = r.xaxis;
                this.txYAxis = r.yaxis;
                this.txStroke = r.stroke;
                this.txFill = r.fill;
                this.txGrid = r.grid;
                this.txLegend = r.legend;
                this.txTooltip = r.tooltip;
                this.txMarkers = r.markers;
                this.txDataLabels = r.dataLabels;
                this.txAnn = r.annotations;
                break;
        }
    }
}
