import {Component, Input, OnChanges, signal, SimpleChanges} from '@angular/core';
import {CommonModule} from '@angular/common';
import {ApexAxisChartSeries, ApexChart, ApexDataLabels, ApexFill, ApexGrid, ApexLegend, ApexMarkers, ApexStroke, ApexTooltip, ApexXAxis, ApexYAxis, NgApexchartsModule,} from 'ng-apexcharts';
import {baseTheme, POSEIDON_COLORS} from '../../../apex.theme';
import {AnalyticsHeatmapCellPayload, AnalyticsHeatmapSeriesPayload} from "../../../core/models";

interface MetricCategory {
    id: string;
    label: string;
    icon: string;
    metricKeys: string[];
}

const EXPLORATION_CATEGORIES: MetricCategory[] = [
    {
        id: 'liquidity_volume',
        label: 'Volume & Liquidity',
        icon: 'fa-water',
        metricKeys: ['liquidity_usd', 'volume_m5_usd', 'volume_h1_usd', 'volume_h6_usd']
    },
    {
        id: 'momentum',
        label: 'Price Momentum',
        icon: 'fa-bolt',
        metricKeys: ['price_change_m5', 'price_change_h1', 'price_change_h6', 'buy_to_sell_ratio']
    },
    {
        id: 'activity',
        label: 'Network Activity',
        icon: 'fa-network-wired',
        metricKeys: ['transaction_count_m5', 'transaction_count_h1', 'transaction_count_h6', 'token_age_hours']
    }
];

interface ExplorerChartConfig {
    metricLabel: string;
    series: ApexAxisChartSeries;
    chart: ApexChart;
    xaxis: ApexXAxis;
    yaxis: ApexYAxis[];
}

@Component({
    selector: 'app-analytics-exploration',
    standalone: true,
    imports: [CommonModule, NgApexchartsModule],
    templateUrl: 'analytics-exploration.component.html',
    styleUrl: 'analytics-exploration.component.css',
})
export class AnalyticsExplorationComponent implements OnChanges {
    @Input() heatmapData: AnalyticsHeatmapSeriesPayload[] = [];
    @Input() isActive = false;

    categories = EXPLORATION_CATEGORIES;
    readonly activeCategory = signal<MetricCategory | null>(EXPLORATION_CATEGORIES[0]);
    readonly activeCharts = signal<ExplorerChartConfig[]>([]);
    mixedGrid: ApexGrid = baseTheme().grid;
    mixedLegend: ApexLegend = {show: false};
    mixedTooltip: ApexTooltip = {theme: 'dark', shared: true, intersect: false};
    mixedStroke: ApexStroke = {width: [0, 3], curve: 'smooth'};
    mixedFill: ApexFill = {opacity: [0.15, 1], type: ['solid', 'solid']};
    mixedColors: string[] = ['#334155', POSEIDON_COLORS.success];
    mixedDataLabels: ApexDataLabels = {enabled: false};
    mixedMarkers: ApexMarkers = {size: 4, strokeWidth: 0, colors: [POSEIDON_COLORS.success]};
    private hasRenderedOnce = false;

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['heatmapData'] && this.heatmapData.length > 0 && this.isActive) {
            this.deferredRebuild();
        }
        if (changes['isActive'] && this.isActive && this.heatmapData.length > 0 && !this.hasRenderedOnce) {
            this.deferredRebuild();
        }
    }

    selectCategory(category: MetricCategory): void {
        this.activeCategory.set(category);
        this.rebuildCharts();
    }

    private deferredRebuild(): void {
        setTimeout(() => {
            this.rebuildCharts();
            this.hasRenderedOnce = true;
        }, 80);
    }

    private rebuildCharts(): void {
        const category = this.activeCategory();
        if (!category || !this.heatmapData) {
            this.activeCharts.set([]);
            return;
        }

        const newConfigs: ExplorerChartConfig[] = [];

        const sortedSeries = category.metricKeys
            .map(key => this.heatmapData.find(s => s.metric_key === key))
            .filter((s): s is AnalyticsHeatmapSeriesPayload => !!s);

        for (const series of sortedSeries) {
            const categories = series.cells.map((cell: AnalyticsHeatmapCellPayload) => cell.range_label);
            const sampleSizeData = series.cells.map((cell: AnalyticsHeatmapCellPayload) => cell.sample_count);
            const winRateData = series.cells.map((cell: AnalyticsHeatmapCellPayload) => parseFloat(cell.win_rate_percentage.toFixed(1)));

            const config: ExplorerChartConfig = {
                metricLabel: series.metric_label,
                series: [
                    {name: 'Sample Size', type: 'column', data: sampleSizeData as never[]},
                    {name: 'Win Rate (%)', type: 'line', data: winRateData as never[]}
                ],
                chart: this.buildMixedChart(),
                xaxis: {
                    categories: categories,
                    labels: {style: {colors: '#94a3b8', fontSize: '10px', fontFamily: 'Inter, sans-serif'}}
                },
                yaxis: [
                    {
                        seriesName: 'Sample Size',
                        axisTicks: {show: false},
                        axisBorder: {show: false},
                        labels: {show: false},
                        title: {text: undefined}
                    },
                    {
                        seriesName: 'Win Rate (%)',
                        opposite: true,
                        axisTicks: {show: false},
                        axisBorder: {show: false},
                        labels: {style: {colors: POSEIDON_COLORS.success, fontSize: '10px'}, formatter: (val) => `${val}%`},
                        title: {text: undefined},
                        min: 0,
                        max: 100
                    }
                ]
            };

            newConfigs.push(config);
        }

        this.activeCharts.set(newConfigs);
    }

    private buildMixedChart(): ApexChart {
        return {
            type: 'line',
            height: 250,
            toolbar: {show: false},
            zoom: {enabled: false},
            animations: {enabled: true, speed: 400}
        };
    }
}
