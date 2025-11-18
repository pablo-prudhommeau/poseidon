// frontend/src/app/pages/analytics/analytics.component.ts
import {CommonModule} from '@angular/common';
import {AfterViewInit, Component, Directive, ElementRef, EventEmitter, inject, OnDestroy, OnInit, Output, signal} from '@angular/core';
import {FormsModule} from '@angular/forms';

import {
    ApexAnnotations,
    ApexAxisChartSeries,
    ApexChart,
    ApexDataLabels,
    ApexFill,
    ApexGrid,
    ApexLegend,
    ApexMarkers,
    ApexPlotOptions,
    ApexStroke,
    ApexTooltip,
    ApexXAxis,
    ApexYAxis,
    NgApexchartsModule
} from 'ng-apexcharts';

import {CardModule} from 'primeng/card';
import {CheckboxModule} from 'primeng/checkbox';
import {forkJoin} from 'rxjs';
import {baseTheme, POSEIDON_COLORS} from '../../apex.theme';
import {ApiService} from '../../api.service';
import type {Analytics, Position} from '../../core/models';

/** Emits true/false when the element enters/leaves viewport (lazy build). */
@Directive({selector: '[inViewport]', standalone: true})
export class InViewportDirective implements AfterViewInit, OnDestroy {
    @Output() inViewportChange = new EventEmitter<boolean>();
    private observer?: IntersectionObserver;

    /** Start observing the host element visibility. */
    constructor(private readonly host: ElementRef<HTMLElement>) {}

    ngAfterViewInit(): void {
        this.observer = new IntersectionObserver(
            ([entry]) => this.inViewportChange.emit(entry.isIntersecting),
            {root: null, rootMargin: '200px', threshold: 0.01}
        );
        this.observer.observe(this.host.nativeElement);
    }

    ngOnDestroy(): void {
        this.observer?.disconnect();
    }
}

/** Scatter point. */
interface ScatterPoint {
    x: number;
    y: number;
    meta?: unknown;
}

/** Line point (nullable y creates gaps for empty buckets). */
interface LinePoint {
    x: number;
    y: number | null;
}

/** RangeArea point [low, high]. */
interface RangePoint {
    x: number;
    y: [number, number];
}

/** Heatmap cell extended with meta. */
interface HeatCell {
    x: string;
    y: number;
    meta: { rangeMin: number; rangeMax: number; sampleSize: number; isFlagged?: boolean };
    fillColor?: string;
}

type ChartKey =
    | 'final' | 'quality' | 'statistics' | 'entry'
    | 'liq'
    | 'vol5m' | 'vol1h' | 'vol6h' | 'vol24h'
    | 'p5m' | 'p1h' | 'p6h' | 'p24h'
    | 'age'
    | 'tx5m' | 'tx1h' | 'tx6h' | 'tx24h';

const CHART_KEYS: ReadonlyArray<ChartKey> = [
    'final', 'quality', 'statistics', 'entry',
    'liq',
    'vol5m', 'vol1h', 'vol6h', 'vol24h',
    'p5m', 'p1h', 'p24h',
    'age',
    'tx5m', 'tx1h', 'tx6h', 'tx24h'
];

interface MetricDefinition {
    key: ChartKey;
    label: string;
    accessor: (row: Analytics) => number | string | bigint | null | undefined;
    usesLogScaleForDisplay: boolean;
    unit: 'score' | 'usd' | 'percent' | 'count' | 'hours';
}

@Component({
    selector: 'app-analytics',
    standalone: true,
    imports: [CommonModule, FormsModule, NgApexchartsModule, CardModule, CheckboxModule, InViewportDirective],
    templateUrl: './analytics.component.html'
})
export class AnalyticsComponent implements OnInit {
    private readonly api = inject(ApiService);

    readonly rows = signal<Analytics[]>([]);
    readonly positions = signal<Position[]>([]);

    readonly pnlAxisMode = signal<'pct' | 'usd'>('pct');
    readonly showTrend = signal<boolean>(true);
    readonly showIqrBand = signal<boolean>(true);
    readonly useLogX = signal<boolean>(true);
    readonly maxScatterPoints = signal<number>(600);

    private readonly minPointsPerBucket = 3;

    visible: Record<ChartKey, boolean> = {
        final: false, quality: false, statistics: false, entry: false,
        liq: false,
        vol5m: false, vol1h: false, vol6h: false, vol24h: false,
        p5m: false, p1h: false, p6h: false, p24h: false,
        age: false,
        tx5m: false, tx1h: false, tx6h: false, tx24h: false
    };

    private readonly metricDefs: ReadonlyArray<MetricDefinition> = [
        {key: 'final', label: 'Final score', accessor: r => r.scores?.final, usesLogScaleForDisplay: false, unit: 'score'},
        {key: 'quality', label: 'Quality score', accessor: r => r.scores?.quality, usesLogScaleForDisplay: false, unit: 'score'},
        {key: 'statistics', label: 'Statistics score', accessor: r => r.scores?.statistics, usesLogScaleForDisplay: false, unit: 'score'},
        {key: 'entry', label: 'Entry score', accessor: r => r.scores?.entry, usesLogScaleForDisplay: false, unit: 'score'},
        {key: 'liq', label: 'Liquidity ($)', accessor: r => r.fundamentals?.liquidityUsd, usesLogScaleForDisplay: true, unit: 'usd'},
        {key: 'vol5m', label: 'Volume 5m ($)', accessor: r => r.fundamentals?.volume5mUsd, usesLogScaleForDisplay: true, unit: 'usd'},
        {key: 'vol1h', label: 'Volume 1h ($)', accessor: r => r.fundamentals?.volume1hUsd, usesLogScaleForDisplay: true, unit: 'usd'},
        {key: 'vol6h', label: 'Volume 6h ($)', accessor: r => r.fundamentals?.volume6hUsd, usesLogScaleForDisplay: true, unit: 'usd'},
        {key: 'vol24h', label: 'Volume 24h ($)', accessor: r => r.fundamentals?.volume24hUsd, usesLogScaleForDisplay: true, unit: 'usd'},
        {key: 'p5m', label: 'Δ5m (%)', accessor: r => r.fundamentals?.pct5m, usesLogScaleForDisplay: false, unit: 'percent'},
        {key: 'p1h', label: 'Δ1h (%)', accessor: r => r.fundamentals?.pct1h, usesLogScaleForDisplay: false, unit: 'percent'},
        {key: 'p6h', label: 'Δ6h (%)', accessor: r => r.fundamentals?.pct6h, usesLogScaleForDisplay: false, unit: 'percent'},
        {key: 'p24h', label: 'Δ24h (%)', accessor: r => r.fundamentals?.pct24h, usesLogScaleForDisplay: false, unit: 'percent'},
        {key: 'age', label: 'Token age (h)', accessor: r => r.fundamentals?.tokenAgeHours, usesLogScaleForDisplay: true, unit: 'hours'},
        {key: 'tx5m', label: 'Transactions 5m', accessor: r => r.fundamentals.tx5m, usesLogScaleForDisplay: true, unit: 'count'},
        {key: 'tx1h', label: 'Transactions 1h', accessor: r => r.fundamentals.tx1h, usesLogScaleForDisplay: true, unit: 'count'},
        {key: 'tx6h', label: 'Transactions 6h', accessor: r => r.fundamentals.tx6h, usesLogScaleForDisplay: true, unit: 'count'},
        {key: 'tx24h', label: 'Transactions 24h', accessor: r => r.fundamentals.tx24h, usesLogScaleForDisplay: true, unit: 'count'}
    ];

    constructor() {}

    /** Load analytics and positions once via HTTP (no WebSocket). */
    ngOnInit(): void { this.loadAllFromHttp(); }

    private loadAllFromHttp(): void {
        forkJoin({
            analytics: this.api.getAnalytics(),
            positions: this.api.getOpenPositions()
        }).subscribe({
            next: ({analytics, positions}) => {
                this.rows.set(analytics);
                this.positions.set(positions);
                this.rebuildDriversHeatmap();
                this.rebuildStaledHeatmap();
                console.info('[ANALYTICS][HTTP][LOAD] Loaded analytics and positions', {
                    analytics: analytics.length,
                    positions: positions.length
                });
            },
            error: (error) => {
                console.error('[ANALYTICS][HTTP][LOAD][ERROR] Failed to load analytics/positions', error);
            }
        });
    }

    onAxisModeChange(mode: 'pct' | 'usd'): void {
        this.pnlAxisMode.set(mode);
        this.rebuildVisible();
        this.rebuildDriversHeatmap();
    }

    onToggleTrend(v: boolean): void {
        this.showTrend.set(v);
        this.rebuildVisible();
    }

    onToggleIqr(v: boolean): void {
        this.showIqrBand.set(v);
        this.rebuildVisible();
    }

    onToggleLogX(v: boolean): void {
        this.useLogX.set(v);
        this.rebuildVisible();
    }

    onViewport(kind: ChartKey, visible: boolean): void {
        this.visible[kind] = visible;
        if (visible) { this.rebuildOne(kind); }
    }

    private coerceNumber(value: unknown): number | null {
        if (typeof value === 'number') {
            return Number.isFinite(value) ? value : null;
        }
        if (typeof value === 'bigint') {
            return Number(value);
        }
        if (typeof value === 'string') {
            const v = Number(value.trim());
            return Number.isFinite(v) ? v : null;
        }
        return null;
    }

    private getPnL(row: Analytics): number | null {
        const src = this.pnlAxisMode() === 'pct' ? row.outcome?.pnlPct : row.outcome?.pnlUsd;
        return this.coerceNumber(src as unknown);
    }

    private getRowKey(r: Analytics): string | number | null {
        return (r as any).positionId ?? (r as any).id ?? (r as any).tradeId ?? (r as any)?.raw?.id ?? null;
    }

    private quantile(sortedAsc: number[], q: number): number {
        const n = sortedAsc.length;
        if (n === 0) {
            return 0;
        }
        const pos = (n - 1) * q;
        const base = Math.floor(pos);
        const rest = pos - base;
        const a = sortedAsc[base];
        const b = sortedAsc[base + 1] ?? a;
        return a + (b - a) * rest;
    }

    private decileEdges(values: number[]): number[] {
        const s = [...values].sort((a, b) => a - b);
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

    private formatMetricValue(unit: MetricDefinition['unit'], value: number): string {
        if (unit === 'percent') {
            return `${value.toFixed(1)}%`;
        }
        if (unit === 'usd') {
            const abs = Math.abs(value);
            if (abs >= 1_000_000) {
                return `${(value / 1_000_000).toFixed(1)}M`;
            }
            if (abs >= 1_000) {
                return `${(value / 1_000).toFixed(1)}K`;
            }
            return value.toFixed(0);
        }
        if (unit === 'count') {
            if (value >= 1_000_000) {
                return `${(value / 1_000_000).toFixed(1)}M`;
            }
            if (value >= 1_000) {
                return `${(value / 1_000).toFixed(1)}K`;
            }
            return value.toFixed(0);
        }
        if (unit === 'hours') {
            return value.toFixed(0);
        }
        return value.toFixed(0);
    }

    private formatPnL(value: unknown): string {
        const n = this.coerceNumber(value);
        if (n === null) {
            return String(value ?? '');
        }
        if (this.pnlAxisMode() === 'pct') {
            return `${n.toFixed(1)}%`;
        }
        const abs = Math.abs(n);
        if (abs >= 1_000_000) {
            return `${(n / 1_000_000).toFixed(1)}M`;
        }
        if (abs >= 1_000) {
            return `${(n / 1_000).toFixed(1)}K`;
        }
        return n.toFixed(0);
    }

    private lttb(points: ScatterPoint[], threshold: number): ScatterPoint[] {
        const n = points.length;
        if (threshold >= n || threshold <= 0) {
            return points;
        }
        const sampled: ScatterPoint[] = [];
        const bucketSize = (n - 2) / (threshold - 2);
        let a = 0;
        sampled.push(points[a]);
        for (let i = 0; i < threshold - 2; i++) {
            const start = Math.floor((i + 1) * bucketSize) + 1;
            const end = Math.floor((i + 2) * bucketSize) + 1;
            const endClamped = Math.min(end, n);

            let avgX = 0, avgY = 0, count = 0;
            for (let j = start; j < endClamped; j++) {
                avgX += points[j].x;
                avgY += points[j].y;
                count++;
            }
            if (count > 0) {
                avgX /= count;
                avgY /= count;
            }

            let maxArea = -1;
            let chosen = points[start];
            const ax = points[a].x, ay = points[a].y;
            const rangeStart = Math.floor(i * bucketSize) + 1;
            const rangeEnd = Math.floor((i + 1) * bucketSize) + 1;

            for (let j = rangeStart; j < rangeEnd; j++) {
                const p = points[j];
                const area = Math.abs((ax - avgX) * (p.y - ay) - (ax - p.x) * (avgY - ay)) * 0.5;
                if (area > maxArea) {
                    maxArea = area;
                    chosen = p;
                }
            }
            sampled.push(chosen);
            a = points.indexOf(chosen);
        }
        sampled.push(points[n - 1]);
        return sampled;
    }

    private buildScatter(args: { metricLabel: string; accessor: MetricDefinition['accessor']; useLogX?: boolean }) {
        const theme = baseTheme();

        const scatter: ScatterPoint[] = [];
        const xAll: number[] = [];
        const xClosed: number[] = [];
        const yClosed: number[] = [];

        for (const r of this.rows()) {
            const xRaw = this.coerceNumber(args.accessor(r));
            const yRaw = this.getPnL(r);
            if (xRaw === null || yRaw === null) {
                continue;
            }

            const x = args.useLogX ? Math.log10(Math.max(1e-9, xRaw)) : xRaw;
            scatter.push({x, y: yRaw, meta: r});
            xAll.push(x);

            if (r.outcome?.hasOutcome === true) {
                xClosed.push(x);
                yClosed.push(yRaw);
            }
        }

        const edges = xClosed.length >= 2 ? this.decileEdges(xClosed)
            : xAll.length >= 2 ? this.decileEdges(xAll)
                : [0, 1];

        const centers: number[] = [];
        const bucketsClosed: number[][] = Array.from({length: Math.max(edges.length - 1, 1)}, () => []);
        for (let i = 0; i < xClosed.length; i++) {
            const b = this.binIndex(xClosed[i], edges);
            bucketsClosed[b].push(yClosed[i]);
        }
        for (let i = 0; i < edges.length - 1; i++) {
            centers.push((edges[i] + edges[i + 1]) / 2);
        }

        const medianAll: LinePoint[] = [];
        const iqr: RangePoint[] = [];

        for (let i = 0; i < centers.length; i++) {
            const cx = centers[i];
            const all = bucketsClosed[i];
            if (!all || all.length < this.minPointsPerBucket) {
                medianAll.push({x: cx, y: null});
                iqr.push({x: cx, y: [0, 0]});
            } else {
                const s = [...all].sort((a, b) => a - b);
                const q1 = this.quantile(s, 0.25);
                const med = this.quantile(s, 0.5);
                const q3 = this.quantile(s, 0.75);
                medianAll.push({x: cx, y: med});
                iqr.push({x: cx, y: [q1, q3]});
            }
        }

        const points = this.lttb(scatter, this.maxScatterPoints());

        const chart: ApexChart = {...theme.chart, animations: {enabled: true, speed: 300}};
        const xaxis: ApexXAxis = {
            title: {text: args.metricLabel},
            labels: {...(args.useLogX ? {formatter: v => this.formatLogTick(Number(v))} : {}), style: {fontSize: '11px'}}
        };
        const yaxis: ApexYAxis = {title: {text: this.pnlAxisMode() === 'pct' ? 'PnL (%)' : 'PnL (USD)'}, labels: {style: {fontSize: '11px'}}};

        const series: ApexAxisChartSeries = [
            {name: 'trades', type: 'scatter', data: points},
            ...(this.showTrend() ? [{name: 'median', type: 'line', data: medianAll}] as ApexAxisChartSeries : []),
            ...(this.showIqrBand() ? [{name: 'IQR (Q1–Q3)', type: 'rangeArea', data: iqr as unknown as ScatterPoint[]}] as ApexAxisChartSeries : [])
        ];

        const widths: number[] = series.map(s => s.type === 'rangeArea' ? 2 : (s.type === 'line' ? 3 : 0));
        const stroke: ApexStroke = {...theme.stroke!, curve: 'smooth', width: widths, colors: ['transparent']};
        const fill: ApexFill = {
            ...theme.fill!,
            type: 'gradient',
            opacity: [0, 0, 0.42],
            gradient: {shade: 'dark', type: 'vertical', gradientToColors: [POSEIDON_COLORS.accent], inverseColors: false, opacityFrom: 0.45, opacityTo: 0.2, stops: [0, 100]}
        };
        const grid: ApexGrid = theme.grid!;
        const legend: ApexLegend = theme.legend!;
        const tooltip: ApexTooltip = {...theme.tooltip!, y: {formatter: (val: number) => this.formatPnL(val)}};
        const markers: ApexMarkers = {...(theme.markers ?? {}), size: 2, strokeWidth: 0};
        const dataLabels: ApexDataLabels = {...(theme.dataLabels ?? {}), enabled: false, style: {fontSize: '11px'}};
        const annotations: ApexAnnotations = {
            yaxis: [{y: 0, borderColor: 'rgba(148,163,184,.65)', strokeDashArray: 4, label: {text: '0', style: {fontSize: '10px', color: '#cbd5e1', background: '#1f2437'}}}]
        };
        const colors = [POSEIDON_COLORS.primary, POSEIDON_COLORS.accent, POSEIDON_COLORS.accent];

        return {series, chart, xaxis, yaxis, stroke, fill, grid, legend, tooltip, markers, dataLabels, annotations, colors};
    }

    // ===== Heatmap “drivers” (closed trades)
    private buildDriversHeatmap(): {
        series: ApexAxisChartSeries; chart: ApexChart;
        xaxis: ApexXAxis; yaxis: ApexYAxis;
        grid: ApexGrid; legend: ApexLegend; tooltip: ApexTooltip;
        dataLabels: ApexDataLabels; plotOptions: ApexPlotOptions; colors: string[]; stroke: ApexStroke;
    } {
        const theme = baseTheme();
        const series: ApexAxisChartSeries = [];

        for (const def of this.metricDefs) {
            const xsRaw: number[] = [];
            const ys: number[] = [];
            for (const r of this.rows()) {
                if (r.outcome?.hasOutcome !== true) {
                    continue;
                }
                const x = this.coerceNumber(def.accessor(r));
                const y = this.getPnL(r);
                if (x === null || y === null) {
                    continue;
                }
                xsRaw.push(x);
                ys.push(y);
            }

            if (xsRaw.length === 0) {
                series.push({name: def.label, type: 'heatmap', data: []});
                continue;
            }

            const edges = this.decileEdges(xsRaw);
            const bins: number[][] = Array.from({length: edges.length - 1}, () => []);
            const counts: number[] = Array.from({length: edges.length - 1}, () => 0);

            for (let i = 0; i < xsRaw.length; i++) {
                const b = this.binIndex(xsRaw[i], edges);
                bins[b].push(ys[i]);
                counts[b]++;
            }

            const cells: HeatCell[] = [];
            const labels: string[] = [];
            const medians: number[] = [];
            for (let i = 0; i < bins.length; i++) {
                const left = edges[i];
                const right = edges[i + 1];
                const label = `${this.formatMetricValue(def.unit, left)}–${this.formatMetricValue(def.unit, right)}`;
                labels.push(label);

                let median = 0;
                if (bins[i].length >= this.minPointsPerBucket) {
                    const s = [...bins[i]].sort((a, b) => a - b);
                    median = this.quantile(s, 0.5);
                } else {
                    median = Number.NEGATIVE_INFINITY;
                }
                medians.push(median);
            }

            const maxMedian = Math.max(...medians.filter(v => v !== Number.NEGATIVE_INFINITY));
            const threshold = maxMedian - Math.abs(maxMedian) * 0.10;
            const flagMask: boolean[] = medians.map((v, i) => v !== Number.NEGATIVE_INFINITY && v >= threshold && counts[i] >= this.minPointsPerBucket);

            for (let i = 0; i < medians.length; i++) {
                const cell: HeatCell = {
                    x: labels[i],
                    y: medians[i] === Number.NEGATIVE_INFINITY ? 0 : medians[i],
                    meta: {rangeMin: edges[i], rangeMax: edges[i + 1], sampleSize: counts[i], isFlagged: flagMask[i]},
                    fillColor: flagMask[i] ? POSEIDON_COLORS.accent : undefined
                };
                cells.push(cell);
            }

            series.push({name: def.label, type: 'heatmap', data: cells as any});
        }

        const chart: ApexChart = {...theme.chart, type: 'heatmap', animations: {enabled: true, speed: 350}};
        const plotOptions: ApexPlotOptions = {
            heatmap: {
                enableShades: false,
                shadeIntensity: 0,
                radius: 8,
                useFillColorAsStroke: false,
                colorScale: {
                    inverse: false,
                    ranges: [
                        {from: -1e12, to: -0.001, color: POSEIDON_COLORS.danger, name: 'Loss'},
                        {from: -0.001, to: 0.001, color: '#94a3b8', name: 'Neutral'},
                        {from: 0.001, to: 1e12, color: POSEIDON_COLORS.success, name: 'Gain'}
                    ]
                }
            }
        };
        const xaxis: ApexXAxis = {type: 'category', labels: {style: {fontSize: '11px'}, rotate: -45, trim: true}};
        const yaxis: ApexYAxis = {labels: {style: {fontSize: '11px'}}};
        const grid: ApexGrid = {...theme.grid!, xaxis: {lines: {show: false}}, padding: {top: 6, right: 8, left: 8, bottom: 6}};
        const legend: ApexLegend = {...theme.legend!, show: true};
        const tooltip: ApexTooltip = {
            ...theme.tooltip!,
            y: {formatter: (v: number) => this.formatPnL(v)},
            custom: ({seriesIndex, dataPointIndex, w}: any) => {
                try {
                    const serie = w.config.series[seriesIndex] as { data: HeatCell[]; name: string };
                    const cell = serie.data[dataPointIndex] as HeatCell;
                    const unit = this.metricDefs[seriesIndex]?.unit ?? 'score';
                    const range = `${this.formatMetricValue(unit, cell.meta.rangeMin)}–${this.formatMetricValue(unit, cell.meta.rangeMax)}`;
                    const pnl = this.formatPnL(cell.y);
                    const n = cell.meta.sampleSize;
                    const badge = cell.meta.isFlagged ? `<span style="background:${POSEIDON_COLORS.accent};color:#0b1020;border-radius:6px;padding:2px 6px;margin-left:6px;">optimal</span>` : '';
                    return `<div style="padding:8px 10px;">
            <div style="font-weight:600;">${serie.name}${badge}</div>
            <div style="font-size:12px;opacity:.9;">${range}</div>
            <div style="margin-top:4px;">Median PnL: <b>${pnl}</b> &nbsp;•&nbsp; n=${n}</div>
          </div>`;
                } catch { return ''; }
            }
        };
        const dataLabels: ApexDataLabels = {
            enabled: true,
            formatter: (_: number, opts?: any) => {
                try {
                    const cell = (opts?.w?.config.series[opts.seriesIndex]?.data[opts.dataPointIndex]) as HeatCell;
                    if (cell?.meta?.isFlagged) {
                        return '●';
                    }
                    return this.formatPnL(opts.value);
                } catch { return ''; }
            },
            style: {fontSize: '13px', fontWeight: 700, colors: [POSEIDON_COLORS.text]}
        };
        const stroke: ApexStroke = {width: 2, colors: ['transparent']};
        const colors = theme.colors;
        return {series, chart, xaxis, yaxis, grid, legend, tooltip, dataLabels, plotOptions, colors, stroke};
    }

    private buildStaledHeatmap(): {
        series: ApexAxisChartSeries; chart: ApexChart;
        xaxis: ApexXAxis; yaxis: ApexYAxis;
        grid: ApexGrid; legend: ApexLegend; tooltip: ApexTooltip;
        dataLabels: ApexDataLabels; plotOptions: ApexPlotOptions; colors: string[]; stroke: ApexStroke;
    } {
        const theme = baseTheme();

        const staledSet = new Set<string | number>();
        for (const p of this.positions()) {
            const phase = (p as any)?.phase;
            if (typeof phase === 'string' && phase.toUpperCase() === 'STALED') {
                const key = (p as any).positionId ?? (p as any).id ?? (p as any).tradeId;
                if (key !== undefined) {
                    staledSet.add(key);
                }
            }
        }

        const series: ApexAxisChartSeries = [];

        for (const def of this.metricDefs) {
            const xsRaw: number[] = [];
            const keys: (string | number | null)[] = [];

            for (const r of this.rows()) {
                const x = this.coerceNumber(def.accessor(r));
                if (x === null) {
                    continue;
                }
                xsRaw.push(x);
                keys.push(this.getRowKey(r));
            }

            if (xsRaw.length === 0) {
                series.push({name: def.label, type: 'heatmap', data: []});
                continue;
            }

            const edges = this.decileEdges(xsRaw);
            const counts: number[] = Array.from({length: edges.length - 1}, () => 0);
            const staledCounts: number[] = Array.from({length: edges.length - 1}, () => 0);

            for (let i = 0; i < xsRaw.length; i++) {
                const b = this.binIndex(xsRaw[i], edges);
                counts[b]++;
                const key = keys[i];
                if (key != null && staledSet.has(key)) {
                    staledCounts[b]++;
                }
            }

            const labels: string[] = [];
            const cells: HeatCell[] = [];
            const rates: number[] = [];
            for (let i = 0; i < counts.length; i++) {
                const left = edges[i];
                const right = edges[i + 1];
                const n = counts[i];
                const rate = n > 0 ? (staledCounts[i] / n) * 100 : 0;
                labels.push(`${this.formatMetricValue(def.unit, left)}–${this.formatMetricValue(def.unit, right)}`);
                rates.push(rate);
            }

            const maxRate = Math.max(0, ...rates);
            const thr = maxRate * 0.9;

            for (let i = 0; i < counts.length; i++) {
                const left = edges[i];
                const right = edges[i + 1];
                const n = counts[i];
                const rate = rates[i];
                cells.push({
                    x: labels[i],
                    y: rate,
                    meta: {rangeMin: left, rangeMax: right, sampleSize: n, isFlagged: rate >= thr && n >= this.minPointsPerBucket}
                });
            }

            series.push({name: def.label, type: 'heatmap', data: cells as any});
        }

        const chart: ApexChart = {...theme.chart, type: 'heatmap', animations: {enabled: true, speed: 350}};
        const plotOptions: ApexPlotOptions = {
            heatmap: {
                enableShades: false,
                shadeIntensity: 0,
                radius: 8,
                useFillColorAsStroke: false,
                colorScale: {
                    inverse: false,
                    ranges: [
                        {from: 0, to: 5, color: POSEIDON_COLORS.success, name: 'Low'},
                        {from: 5, to: 15, color: '#f59e0b', name: 'Medium'},
                        {from: 15, to: 100, color: POSEIDON_COLORS.danger, name: 'High'}
                    ]
                }
            }
        };
        const xaxis: ApexXAxis = {type: 'category', labels: {style: {fontSize: '11px'}, rotate: -45, trim: true}};
        const yaxis: ApexYAxis = {labels: {style: {fontSize: '11px'}}};
        const grid: ApexGrid = {...theme.grid!, xaxis: {lines: {show: false}}, padding: {top: 6, right: 8, left: 8, bottom: 6}};
        const legend: ApexLegend = {...theme.legend!, show: true};
        const tooltip: ApexTooltip = {
            ...theme.tooltip!,
            y: {formatter: (v: number) => `${v.toFixed(1)}%`},
            custom: ({seriesIndex, dataPointIndex, w}: any) => {
                try {
                    const serie = w.config.series[seriesIndex] as { data: HeatCell[]; name: string };
                    const cell = serie.data[dataPointIndex] as HeatCell;
                    const unit = this.metricDefs[seriesIndex]?.unit ?? 'score';
                    const range = `${this.formatMetricValue(unit, cell.meta.rangeMin)}–${this.formatMetricValue(unit, cell.meta.rangeMax)}`;
                    const n = cell.meta.sampleSize;
                    const pct = `${cell.y.toFixed(1)}%`;
                    const badge = cell.meta.isFlagged ? `<span style="background:${POSEIDON_COLORS.danger};color:#0b1020;border-radius:6px;padding:2px 6px;margin-left:6px;">worst</span>` : '';
                    return `<div style="padding:8px 10px;">
            <div style="font-weight:600;">${serie.name}${badge}</div>
            <div style="font-size:12px;opacity:.9;">${range}</div>
            <div style="margin-top:4px;">Staled rate: <b>${pct}</b> &nbsp;•&nbsp; n=${n}</div>
          </div>`;
                } catch { return ''; }
            }
        };
        const dataLabels: ApexDataLabels = {
            enabled: true,
            formatter: (_: number, opts?: any) => {
                try {
                    const cell = (opts?.w?.config.series[opts.seriesIndex]?.data[opts.dataPointIndex]) as HeatCell;
                    return cell?.meta?.isFlagged ? '●' : `${opts.value.toFixed(1)}%`;
                } catch { return ''; }
            },
            style: {fontSize: '13px', fontWeight: 700, colors: [POSEIDON_COLORS.text]}
        };
        const stroke: ApexStroke = {width: 2, colors: ['transparent']};
        const colors = theme.colors;
        return {series, chart, xaxis, yaxis, grid, legend, tooltip, dataLabels, plotOptions, colors, stroke};
    }

    driversSeries: ApexAxisChartSeries = [];
    driversChart: ApexChart = baseTheme().chart;
    driversXAxis: ApexXAxis = {};
    driversYAxis: ApexYAxis = {};
    driversGrid: ApexGrid = baseTheme().grid;
    driversLegend: ApexLegend = baseTheme().legend;
    driversTooltip: ApexTooltip = baseTheme().tooltip;
    driversDataLabels: ApexDataLabels = baseTheme().dataLabels;
    driversPlotOptions: ApexPlotOptions = {};
    driversStroke: ApexStroke = baseTheme().stroke;
    driversColors: string[] = [];

    staledSeries: ApexAxisChartSeries = [];
    staledChart: ApexChart = baseTheme().chart;
    staledXAxis: ApexXAxis = {};
    staledYAxis: ApexYAxis = {};
    staledGrid: ApexGrid = baseTheme().grid;
    staledLegend: ApexLegend = baseTheme().legend;
    staledTooltip: ApexTooltip = baseTheme().tooltip;
    staledDataLabels: ApexDataLabels = baseTheme().dataLabels;
    staledPlotOptions: ApexPlotOptions = {};
    staledStroke: ApexStroke = baseTheme().stroke;
    staledColors: string[] = [];

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
    finalColors: string[] = baseTheme().colors;

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
    qualityColors: string[] = baseTheme().colors;

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
    statisticsColors: string[] = baseTheme().colors;

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
    entryColors: string[] = baseTheme().colors;

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
    liqColors: string[] = baseTheme().colors;

    vol5mSeries: ApexAxisChartSeries = [];
    vol5mChart: ApexChart = baseTheme().chart;
    vol5mXAxis: ApexXAxis = {};
    vol5mYAxis: ApexYAxis = {};
    vol5mStroke: ApexStroke = baseTheme().stroke;
    vol5mFill: ApexFill = baseTheme().fill;
    vol5mGrid: ApexGrid = baseTheme().grid;
    vol5mLegend: ApexLegend = baseTheme().legend;
    vol5mTooltip: ApexTooltip = baseTheme().tooltip;
    vol5mMarkers: ApexMarkers = baseTheme().markers;
    vol5mDataLabels: ApexDataLabels = baseTheme().dataLabels;
    vol5mAnn: ApexAnnotations = {};
    vol5mColors: string[] = baseTheme().colors;
    vol1hSeries: ApexAxisChartSeries = [];
    vol1hChart: ApexChart = baseTheme().chart;
    vol1hXAxis: ApexXAxis = {};
    vol1hYAxis: ApexYAxis = {};
    vol1hStroke: ApexStroke = baseTheme().stroke;
    vol1hFill: ApexFill = baseTheme().fill;
    vol1hGrid: ApexGrid = baseTheme().grid;
    vol1hLegend: ApexLegend = baseTheme().legend;
    vol1hTooltip: ApexTooltip = baseTheme().tooltip;
    vol1hMarkers: ApexMarkers = baseTheme().markers;
    vol1hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    vol1hAnn: ApexAnnotations = {};
    vol1hColors: string[] = baseTheme().colors;
    vol6hSeries: ApexAxisChartSeries = [];
    vol6hChart: ApexChart = baseTheme().chart;
    vol6hXAxis: ApexXAxis = {};
    vol6hYAxis: ApexYAxis = {};
    vol6hStroke: ApexStroke = baseTheme().stroke;
    vol6hFill: ApexFill = baseTheme().fill;
    vol6hGrid: ApexGrid = baseTheme().grid;
    vol6hLegend: ApexLegend = baseTheme().legend;
    vol6hTooltip: ApexTooltip = baseTheme().tooltip;
    vol6hMarkers: ApexMarkers = baseTheme().markers;
    vol6hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    vol6hAnn: ApexAnnotations = {};
    vol6hColors: string[] = baseTheme().colors;
    vol24hSeries: ApexAxisChartSeries = [];
    vol24hChart: ApexChart = baseTheme().chart;
    vol24hXAxis: ApexXAxis = {};
    vol24hYAxis: ApexYAxis = {};
    vol24hStroke: ApexStroke = baseTheme().stroke;
    vol24hFill: ApexFill = baseTheme().fill;
    vol24hGrid: ApexGrid = baseTheme().grid;
    vol24hLegend: ApexLegend = baseTheme().legend;
    vol24hTooltip: ApexTooltip = baseTheme().tooltip;
    vol24hMarkers: ApexMarkers = baseTheme().markers;
    vol24hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    vol24hAnn: ApexAnnotations = {};
    vol24hColors: string[] = baseTheme().colors;

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
    p5mColors: string[] = baseTheme().colors;
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
    p1hColors: string[] = baseTheme().colors;
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
    p6hColors: string[] = baseTheme().colors;
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
    p24hColors: string[] = baseTheme().colors;

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
    ageColors: string[] = baseTheme().colors;

    tx5mSeries: ApexAxisChartSeries = [];
    tx5mChart: ApexChart = baseTheme().chart;
    tx5mXAxis: ApexXAxis = {};
    tx5mYAxis: ApexYAxis = {};
    tx5mStroke: ApexStroke = baseTheme().stroke;
    tx5mFill: ApexFill = baseTheme().fill;
    tx5mGrid: ApexGrid = baseTheme().grid;
    tx5mLegend: ApexLegend = baseTheme().legend;
    tx5mTooltip: ApexTooltip = baseTheme().tooltip;
    tx5mMarkers: ApexMarkers = baseTheme().markers;
    tx5mDataLabels: ApexDataLabels = baseTheme().dataLabels;
    tx5mAnn: ApexAnnotations = {};
    tx5mColors: string[] = baseTheme().colors;
    tx1hSeries: ApexAxisChartSeries = [];
    tx1hChart: ApexChart = baseTheme().chart;
    tx1hXAxis: ApexXAxis = {};
    tx1hYAxis: ApexYAxis = {};
    tx1hStroke: ApexStroke = baseTheme().stroke;
    tx1hFill: ApexFill = baseTheme().fill;
    tx1hGrid: ApexGrid = baseTheme().grid;
    tx1hLegend: ApexLegend = baseTheme().legend;
    tx1hTooltip: ApexTooltip = baseTheme().tooltip;
    tx1hMarkers: ApexMarkers = baseTheme().markers;
    tx1hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    tx1hAnn: ApexAnnotations = {};
    tx1hColors: string[] = baseTheme().colors;
    tx6hSeries: ApexAxisChartSeries = [];
    tx6hChart: ApexChart = baseTheme().chart;
    tx6hXAxis: ApexXAxis = {};
    tx6hYAxis: ApexYAxis = {};
    tx6hStroke: ApexStroke = baseTheme().stroke;
    tx6hFill: ApexFill = baseTheme().fill;
    tx6hGrid: ApexGrid = baseTheme().grid;
    tx6hLegend: ApexLegend = baseTheme().legend;
    tx6hTooltip: ApexTooltip = baseTheme().tooltip;
    tx6hMarkers: ApexMarkers = baseTheme().markers;
    tx6hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    tx6hAnn: ApexAnnotations = {};
    tx6hColors: string[] = baseTheme().colors;
    tx24hSeries: ApexAxisChartSeries = [];
    tx24hChart: ApexChart = baseTheme().chart;
    tx24hXAxis: ApexXAxis = {};
    tx24hYAxis: ApexYAxis = {};
    tx24hStroke: ApexStroke = baseTheme().stroke;
    tx24hFill: ApexFill = baseTheme().fill;
    tx24hGrid: ApexGrid = baseTheme().grid;
    tx24hLegend: ApexLegend = baseTheme().legend;
    tx24hTooltip: ApexTooltip = baseTheme().tooltip;
    tx24hMarkers: ApexMarkers = baseTheme().markers;
    tx24hDataLabels: ApexDataLabels = baseTheme().dataLabels;
    tx24hAnn: ApexAnnotations = {};
    tx24hColors: string[] = baseTheme().colors;

    private rebuildVisible(): void { CHART_KEYS.forEach(k => { if (this.visible[k]) { this.rebuildOne(k); } }); }

    public rebuildOne(kind: ChartKey): void {
        const def = this.metricDefs.find(m => m.key === kind)!;
        const r = this.buildScatter({metricLabel: def.label, accessor: def.accessor, useLogX: def.usesLogScaleForDisplay && this.useLogX()});

        const apply = (p: string) => {
            (this as any)[`${p}Series`] = r.series;
            (this as any)[`${p}Chart`] = r.chart;
            (this as any)[`${p}XAxis`] = r.xaxis;
            (this as any)[`${p}YAxis`] = r.yaxis;
            (this as any)[`${p}Stroke`] = r.stroke;
            (this as any)[`${p}Fill`] = r.fill;
            (this as any)[`${p}Grid`] = r.grid;
            (this as any)[`${p}Legend`] = r.legend;
            (this as any)[`${p}Tooltip`] = r.tooltip;
            (this as any)[`${p}Markers`] = r.markers;
            (this as any)[`${p}DataLabels`] = r.dataLabels;
            (this as any)[`${p}Ann`] = r.annotations;
            (this as any)[`${p}Colors`] = r.colors;
        };

        switch (kind) {
            case 'final':
                apply('final');
                break;
            case 'quality':
                apply('quality');
                break;
            case 'statistics':
                apply('statistics');
                break;
            case 'entry':
                apply('entry');
                break;
            case 'liq':
                apply('liq');
                break;
            case 'vol5m':
                apply('vol5m');
                break;
            case 'vol1h':
                apply('vol1h');
                break;
            case 'vol6h':
                apply('vol6h');
                break;
            case 'vol24h':
                apply('vol24h');
                break;
            case 'p5m':
                apply('p5m');
                break;
            case 'p1h':
                apply('p1h');
                break;
            case 'p6h':
                apply('p6h');
                break;
            case 'p24h':
                apply('p24h');
                break;
            case 'age':
                apply('age');
                break;
            case 'tx5m':
                apply('tx5m');
                break;
            case 'tx1h':
                apply('tx1h');
                break;
            case 'tx6h':
                apply('tx6h');
                break;
            case 'tx24h':
                apply('tx24h');
                break;
        }
    }

    private rebuildDriversHeatmap(): void {
        const r = this.buildDriversHeatmap();
        this.driversSeries = r.series;
        this.driversChart = r.chart;
        this.driversXAxis = r.xaxis;
        this.driversYAxis = r.yaxis;
        this.driversGrid = r.grid;
        this.driversLegend = r.legend;
        this.driversTooltip = r.tooltip;
        this.driversDataLabels = r.dataLabels;
        this.driversPlotOptions = r.plotOptions;
        this.driversStroke = r.stroke;
        this.driversColors = r.colors;
        console.info('[ANALYTICS][HEATMAP] drivers rebuilt');
    }

    private rebuildStaledHeatmap(): void {
        const r = this.buildStaledHeatmap();
        this.staledSeries = r.series;
        this.staledChart = r.chart;
        this.staledXAxis = r.xaxis;
        this.staledYAxis = r.yaxis;
        this.staledGrid = r.grid;
        this.staledLegend = r.legend;
        this.staledTooltip = r.tooltip;
        this.staledDataLabels = r.dataLabels;
        this.staledPlotOptions = r.plotOptions;
        this.staledStroke = r.stroke;
        this.staledColors = r.colors;
        console.info('[ANALYTICS][HEATMAP] staled rebuilt');
    }
}