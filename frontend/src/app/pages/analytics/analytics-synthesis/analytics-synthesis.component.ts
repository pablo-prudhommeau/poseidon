import {Component, Input, OnChanges, SimpleChanges} from '@angular/core';
import {CommonModule, DecimalPipe} from '@angular/common';
import {ApexAxisChartSeries, ApexChart, ApexDataLabels, ApexGrid, ApexPlotOptions, ApexTooltip, ApexXAxis, ApexYAxis, NgApexchartsModule,} from 'ng-apexcharts';
import {baseTheme, POSEIDON_COLORS} from '../../../apex.theme';
import {AnalyticsHeatmapSeriesPayload, AnalyticsScatterSeriesPayload} from "../../../core/models";

export interface ActionableNiche {
    metricLabel: string;
    rangeLabel: string;
    winRate: number;
    sampleSize: number;
    medianPnl: number;
    type: 'GOLDEN' | 'TOXIC';
}

@Component({
    selector: 'app-analytics-synthesis',
    standalone: true,
    imports: [CommonModule, NgApexchartsModule, DecimalPipe],
    templateUrl: './analytics-synthesis.component.html'
})
export class AnalyticsSynthesisComponent implements OnChanges {
    @Input() pnlDriversSeries: AnalyticsHeatmapSeriesPayload[] = [];
    @Input() scatterData: AnalyticsScatterSeriesPayload[] = [];

    goldenNiches: ActionableNiche[] = [];
    toxicZones: ActionableNiche[] = [];
    sortedMetricOrder: string[] = [];

    deviationSeries: ApexAxisChartSeries = [];
    deviationChart: ApexChart = this.buildDeviationChart();
    deviationXAxis: ApexXAxis = {};
    deviationYAxis: ApexYAxis = {};
    deviationPlotOptions: ApexPlotOptions = {
        bar: {horizontal: true, borderRadius: 2, barHeight: '70%', colors: {ranges: [{from: -1000, to: -0.1, color: POSEIDON_COLORS.danger}, {from: 0.1, to: 1000, color: POSEIDON_COLORS.success}]}}
    };
    deviationDataLabels: ApexDataLabels = {enabled: false};
    deviationTooltip: ApexTooltip = {theme: 'dark', y: {formatter: (val: number) => `${val > 0 ? '+' : ''}${val.toFixed(1)}% vs global avg`}};
    deviationGrid: ApexGrid = {...baseTheme().grid, xaxis: {lines: {show: true}}, yaxis: {lines: {show: false}}};

    powerSeries: ApexAxisChartSeries = [];
    powerChart: ApexChart = this.buildBarChart();
    powerXAxis: ApexXAxis = {};
    powerYAxis: ApexYAxis = {};
    powerGrid: ApexGrid = {
        ...baseTheme().grid,
        xaxis: {lines: {show: true}},
        yaxis: {lines: {show: false}},
        padding: {top: 0, right: 20, bottom: 0, left: 10}
    };
    powerPlotOptions: ApexPlotOptions = {bar: {horizontal: true, borderRadius: 4, barHeight: '70%', colors: {ranges: [{from: 0, to: 100, color: POSEIDON_COLORS.accent}]}}};
    powerDataLabels: ApexDataLabels = {
        enabled: true,
        textAnchor: 'start',
        style: {colors: ['#fff'], fontSize: '10px', fontFamily: 'Inter, sans-serif'},
        formatter: (val: number) => `Influence: ${val.toFixed(1)}%`,
        offsetX: 0,
    };
    powerTooltip: ApexTooltip = {
        theme: 'dark',
        y: {formatter: (val: number) => `${val.toFixed(1)}% Win Rate Amplitude`}
    };

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['scatterData'] && this.scatterData.length > 0) {
            this.computeDeviationProfile();
        }
        if (changes['pnlDriversSeries'] && this.pnlDriversSeries.length > 0) {
            this.computeNiches();
            this.computePowerRanking();
        }
    }

    private computeNiches(): void {
        let allValidCells: ActionableNiche[] = [];

        for (const series of this.pnlDriversSeries) {
            for (const cell of series.cells) {
                if (cell.sample_count >= 10) {
                    allValidCells.push({
                        metricLabel: series.metric_label,
                        rangeLabel: cell.range_label,
                        winRate: cell.win_rate_percentage,
                        sampleSize: cell.sample_count,
                        medianPnl: cell.median_pnl,
                        type: 'GOLDEN'
                    });
                }
            }
        }

        const goldenSorted = [...allValidCells].sort((a, b) => {
            if (b.winRate !== a.winRate) {
                return b.winRate - a.winRate;
            }
            return b.medianPnl - a.medianPnl;
        });

        this.goldenNiches = [];
        const seenGoldenMetrics = new Set<string>();
        for (const cell of goldenSorted) {
            if (!seenGoldenMetrics.has(cell.metricLabel)) {
                this.goldenNiches.push(cell);
                seenGoldenMetrics.add(cell.metricLabel);
            }
            if (this.goldenNiches.length >= 8) {
                break;
            }
        }

        const toxicSorted = [...allValidCells].sort((a, b) => {
            if (a.winRate !== b.winRate) {
                return a.winRate - b.winRate;
            }
            return a.medianPnl - b.medianPnl;
        });

        this.toxicZones = [];
        const seenToxicMetrics = new Set<string>();
        for (const cell of toxicSorted) {
            if (!seenToxicMetrics.has(cell.metricLabel)) {
                const toxicCell = {...cell, type: 'TOXIC'};
                this.toxicZones.push(toxicCell as ActionableNiche);
                seenToxicMetrics.add(cell.metricLabel);
            }
            if (this.toxicZones.length >= 8) {
                break;
            }
        }
    }

    private computeDeviationProfile(): void {
        const results: { label: string; key: string; deviation: number }[] = [];

        for (const series of this.scatterData) {
            let winSum = 0;
            let winCount = 0;
            let lossSum = 0;
            let lossCount = 0;

            for (const point of series.points) {
                if (point.pnl_percentage > 0) {
                    winSum += point.metric_value;
                    winCount++;
                } else {
                    lossSum += point.metric_value;
                    lossCount++;
                }
            }

            const winAvg = winCount > 0 ? winSum / winCount : 0;
            const globalAvg = (winSum + lossSum) / ((winCount + lossCount) || 1);
            const deviationPercentage = globalAvg > 0 ? ((winAvg - globalAvg) / globalAvg) * 100 : 0;
            results.push({label: series.metric_label, key: series.metric_key, deviation: deviationPercentage});
        }

        results.sort((a, b) => b.deviation - a.deviation);
        this.sortedMetricOrder = results.map(r => r.key);

        this.deviationSeries = [
            {name: 'Winner Deviation', data: results.map(r => parseFloat(r.deviation.toFixed(1))) as never[]}
        ];
        this.deviationXAxis = {
            categories: results.map(r => r.label),
            labels: {style: {colors: '#94a3b8', fontSize: '11px', fontFamily: 'Inter, sans-serif'}},
            title: {text: '% Deviation from Global Average', style: {color: '#64748b', fontSize: '10px'}}
        };
    }

    private computePowerRanking(): void {
        const rankings: { label: string; key: string; amplitude: number }[] = [];

        for (const series of this.pnlDriversSeries) {
            let maxWinRate = 0;
            let minWinRate = 100;
            let hasData = false;

            for (const cell of series.cells) {
                if (cell.sample_count >= 10) {
                    hasData = true;
                    if (cell.win_rate_percentage > maxWinRate) {
                        maxWinRate = cell.win_rate_percentage;
                    }
                    if (cell.win_rate_percentage < minWinRate) {
                        minWinRate = cell.win_rate_percentage;
                    }
                }
            }

            if (hasData) {
                const amplitude = maxWinRate - minWinRate;
                rankings.push({label: series.metric_label, key: series.metric_key, amplitude});
            }
        }

        const orderedRankings = this.sortedMetricOrder.length > 0
            ? this.sortedMetricOrder
                .map(key => rankings.find(r => r.key === key))
                .filter((r): r is { label: string; key: string; amplitude: number } => !!r)
            : rankings.sort((a, b) => b.amplitude - a.amplitude);

        this.powerSeries = [{name: 'Influence Power (%)', data: orderedRankings.map(r => parseFloat(r.amplitude.toFixed(1))) as never[]}];
        this.powerXAxis = {
            categories: orderedRankings.map(r => r.label),
            labels: {style: {colors: '#94a3b8', fontSize: '11px'}},
            title: {text: 'Win Rate Amplitude between worst and best decile', style: {color: '#64748b', fontSize: '10px'}}
        };
    }

    private buildDeviationChart(): ApexChart {
        return {
            type: 'bar',
            toolbar: {show: false},
            zoom: {enabled: false},
            animations: {enabled: true, speed: 600},
            height: 500
        };
    }

    private buildBarChart(): ApexChart {
        return {
            type: 'bar',
            toolbar: {show: false},
            zoom: {enabled: false},
            animations: {enabled: true, speed: 600},
            height: 500
        };
    }
}
