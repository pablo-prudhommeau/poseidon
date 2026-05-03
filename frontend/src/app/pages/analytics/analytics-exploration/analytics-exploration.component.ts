import {Component, Input, OnChanges, signal, SimpleChanges} from '@angular/core';
import {CommonModule} from '@angular/common';
import {ApexAxisChartSeries, ApexChart, ApexDataLabels, ApexFill, ApexGrid, ApexLegend, ApexMarkers, ApexStroke, ApexTooltip, ApexXAxis, ApexYAxis, NgApexchartsModule,} from 'ng-apexcharts';
import {baseTheme, POSEIDON_COLORS} from '../../../apex.theme';
import {AnalyticsHeatmapSeriesPayload, AnalyticsScatterSeriesPayload} from "../../../core/models";

import {EXPLORATION_CATEGORIES, MetricCategory} from "../../../core/constants";

interface ExplorerChartConfig {
    metricLabel: string;
    series: ApexAxisChartSeries;
    chart: ApexChart;
    xaxis: ApexXAxis;
    yaxis: ApexYAxis[];
    colors: string[];
    stroke: ApexStroke;
    fill: ApexFill;
    markers: ApexMarkers;
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
    @Input() scatterData: AnalyticsScatterSeriesPayload[] = [];
    @Input() isActive = false;

    categories = EXPLORATION_CATEGORIES;
    readonly activeCategory = signal<MetricCategory | null>(EXPLORATION_CATEGORIES[0]);
    readonly activeExplorationTab = signal<'non-linear' | 'outlier' | 'scatter'>('non-linear');
    readonly activeCharts = signal<ExplorerChartConfig[]>([]);

    mixedGrid: ApexGrid = {
        ...baseTheme().grid,
        padding: {top: 0, right: 25, bottom: 0, left: 10}
    };
    mixedLegend: ApexLegend = {show: false};
    mixedTooltip: ApexTooltip = {theme: 'dark', shared: true, intersect: false};
    mixedDataLabels: ApexDataLabels = {enabled: false};

    private hasRenderedOnce = false;

    ngOnChanges(changes: SimpleChanges): void {
        if ((changes['heatmapData'] || changes['scatterData']) && this.isActive) {
            this.deferredRebuild();
        }
        if (changes['isActive'] && this.isActive && (this.heatmapData.length > 0 || this.scatterData.length > 0) && !this.hasRenderedOnce) {
            this.deferredRebuild();
        }
    }

    selectCategory(category: MetricCategory): void {
        this.activeCategory.set(category);
        this.rebuildCharts();
    }

    setTab(tab: 'non-linear' | 'outlier' | 'scatter'): void {
        this.activeExplorationTab.set(tab);
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
        if (!category) {
            this.activeCharts.set([]);
            return;
        }

        const newConfigs: ExplorerChartConfig[] = [];
        const tab = this.activeExplorationTab();

        if (tab === 'non-linear' || tab === 'outlier') {
            if (!this.heatmapData || this.heatmapData.length === 0) {
                return;
            }
            const sortedSeries = category.metricKeys
                .map(key => this.heatmapData.find(s => s.metric_key === key))
                .filter((s): s is AnalyticsHeatmapSeriesPayload => !!s);

            for (const series of sortedSeries) {
                const categories = series.cells.map(cell => cell.range_label);
                const sampleSizeData = series.cells.map(cell => cell.sample_count);

                if (tab === 'non-linear') {
                    const winRateData = series.cells.map(cell => parseFloat(cell.win_rate_percentage.toFixed(1)));
                    const velocityData = series.cells.map(cell => parseFloat(Math.abs(cell.capital_velocity).toFixed(2)));
                    const pnlData = series.cells.map(cell => parseFloat(cell.average_pnl.toFixed(2)));

                    newConfigs.push({
                        metricLabel: series.metric_label,
                        series: [
                            {name: 'Sample Size', type: 'column', data: sampleSizeData as never[]},
                            {name: 'Win Rate (%)', type: 'line', data: winRateData as never[]},
                            {name: 'Velocity', type: 'line', data: velocityData as never[]},
                            {name: 'Average PnL (%)', type: 'line', data: pnlData as never[]}
                        ],
                        chart: this.buildMixedChart(),
                        colors: ['#334155', POSEIDON_COLORS.success, '#a78bfa', '#f87171'],
                        stroke: {width: [0, 3, 3, 3], curve: 'smooth'},
                        fill: {opacity: [0.15, 1, 1, 1], type: ['solid', 'solid', 'solid', 'solid']},
                        markers: {size: 4, strokeWidth: 0, colors: ['transparent', POSEIDON_COLORS.success, '#a78bfa', '#f87171']},
                        xaxis: {
                            categories: categories,
                            tooltip: {enabled: false},
                            labels: {
                                rotate: -45,
                                style: {colors: '#94a3b8', fontSize: '9px', fontFamily: 'Inter, sans-serif'}
                            }
                        },
                        yaxis: [
                            {seriesName: 'Sample Size', axisTicks: {show: false}, axisBorder: {show: false}, labels: {show: false}, title: {text: undefined}},
                            {
                                seriesName: 'Win Rate (%)',
                                opposite: true,
                                axisTicks: {show: false},
                                axisBorder: {show: true, color: POSEIDON_COLORS.success},
                                labels: {offsetX: -10, style: {colors: POSEIDON_COLORS.success, fontSize: '9px'}, formatter: (val: any) => `${Number(val).toFixed(0)}% WR`},
                                title: {text: undefined},
                                min: 0,
                                max: 100
                            },
                            {
                                seriesName: 'Velocity',
                                opposite: true,
                                axisTicks: {show: false},
                                axisBorder: {show: true, color: '#a78bfa'},
                                labels: {offsetX: -10, style: {colors: '#a78bfa', fontSize: '9px'}, formatter: (val: any) => val ? `${Number(val).toFixed(1)} vel` : '0.0 vel'},
                                title: {text: undefined}
                            },
                            {
                                seriesName: 'Average PnL (%)',
                                opposite: true,
                                axisTicks: {show: false},
                                axisBorder: {show: true, color: '#f87171'},
                                labels: {offsetX: -10, style: {colors: '#f87171', fontSize: '9px'}, formatter: (val: any) => val ? `${Number(val).toFixed(0)}% PnL` : '0% PnL'},
                                title: {text: undefined}
                            }
                        ]
                    });
                } else { // outlier
                    const outlierData = series.cells.map(cell => parseFloat((cell.outlier_hit_rate_percentage || 0).toFixed(1)));
                    newConfigs.push({
                        metricLabel: series.metric_label,
                        series: [
                            {name: 'Sample Size', type: 'column', data: sampleSizeData as never[]},
                            {name: 'Outlier Hit Rate (%)', type: 'line', data: outlierData as never[]}
                        ],
                        chart: this.buildMixedChart(),
                        colors: ['#334155', '#fbbf24'],
                        stroke: {width: [0, 3], curve: 'smooth'},
                        fill: {opacity: [0.15, 1], type: ['solid', 'solid']},
                        markers: {size: 4, strokeWidth: 0, colors: ['transparent', '#fbbf24']},
                        xaxis: {
                            categories: categories,
                            tooltip: {enabled: false},
                            labels: {
                                rotate: -45,
                                style: {colors: '#94a3b8', fontSize: '9px', fontFamily: 'Inter, sans-serif'}
                            }
                        },
                        yaxis: [
                            {seriesName: 'Sample Size', axisTicks: {show: false}, axisBorder: {show: false}, labels: {show: false}, title: {text: undefined}},
                            {
                                seriesName: 'Outlier Hit Rate (%)',
                                opposite: true,
                                axisTicks: {show: false},
                                axisBorder: {show: true, color: '#fbbf24'},
                                labels: {offsetX: -10, style: {colors: '#fbbf24', fontSize: '9px'}, formatter: (val: any) => `${Number(val).toFixed(0)}% HR`},
                                title: {text: undefined}
                            }
                        ]
                    });
                }
            }
        } else if (tab === 'scatter') {
            if (!this.scatterData || this.scatterData.length === 0) {
                return;
            }

            const sortedSeries = category.metricKeys
                .map(key => this.scatterData.find(s => s.metric_key === key))
                .filter((s): s is AnalyticsScatterSeriesPayload => !!s);

            for (const series of sortedSeries) {
                const scatterPoints = series.points.map(p => [p.metric_value, p.pnl_percentage]);

                newConfigs.push({
                    metricLabel: series.metric_label,
                    series: [
                        {name: 'Trades', type: 'scatter', data: scatterPoints as never[]}
                    ],
                    chart: {
                        type: 'scatter',
                        height: 250,
                        parentHeightOffset: 0,
                        toolbar: {show: false},
                        zoom: {enabled: true, type: 'xy'},
                        animations: {enabled: false}
                    },
                    colors: ['#0ea5e9'],
                    stroke: {width: 0},
                    fill: {opacity: 1, type: 'solid'},
                    markers: {size: 4, strokeWidth: 0, colors: ['#0ea5e9'], hover: {size: 6}},
                    xaxis: {
                        type: 'numeric',
                        labels: {style: {colors: '#94a3b8', fontSize: '10px', fontFamily: 'Inter, sans-serif'}, formatter: (val: any) => Number(val).toFixed(2)},
                        tickAmount: 10
                    },
                    yaxis: [
                        {
                            labels: {style: {colors: '#94a3b8', fontSize: '10px'}, formatter: (val: any) => `${Number(val).toFixed(0)}%`},
                            title: {text: undefined}
                        }
                    ]
                });
            }
        }

        this.activeCharts.set(newConfigs);
    }

    private buildMixedChart(): ApexChart {
        return {
            type: 'line',
            height: 250,
            parentHeightOffset: 0,
            toolbar: {show: false},
            zoom: {enabled: false},
            animations: {enabled: true, speed: 400}
        };
    }
}
