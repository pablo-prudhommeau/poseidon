import { CommonModule, DecimalPipe } from '@angular/common';
import { Component, Input, OnChanges, SimpleChanges } from '@angular/core';
import {
    ApexAxisChartSeries,
    ApexChart,
    ApexDataLabels,
    ApexGrid,
    ApexPlotOptions,
    ApexTooltip,
    ApexXAxis,
    ApexYAxis,
    NgApexchartsModule
} from 'ng-apexcharts';
import { baseTheme, POSEIDON_COLORS } from '../../../apex.theme';
import { TradingAnalyticsHeatmapSeriesPayload, TradingAnalyticsScatterSeriesPayload } from '../../../core/models';

export interface TradingAnalyticsActionableNiche {
    metricLabel: string;
    rangeLabel: string;
    winRate: number;
    sampleSize: number;
    averagePnl: number;
    expectedPnlVelocity: number;
    averageHoldingTime: number;
    outlierHitRatePercentage: number;
    type: 'GOLDEN' | 'TOXIC';
}

@Component({
    selector: 'app-trading-analytics-synthesis',
    standalone: true,
    imports: [CommonModule, NgApexchartsModule, DecimalPipe],
    templateUrl: './trading-analytics-synthesis.component.html'
})
export class TradingAnalyticsSynthesisComponent implements OnChanges {
    @Input() pnlDriversSeries: TradingAnalyticsHeatmapSeriesPayload[] = [];
    @Input() scatterData: TradingAnalyticsScatterSeriesPayload[] = [];

    deviationChart: ApexChart = this.buildDeviationChart();
    deviationDataLabels: ApexDataLabels = { enabled: false };
    deviationGrid: ApexGrid = {
        ...baseTheme().grid,
        xaxis: { lines: { show: true } },
        yaxis: { lines: { show: false } }
    };

    deviationPlotOptions: ApexPlotOptions = {
        bar: {
            horizontal: true,
            borderRadius: 2,
            barHeight: '70%',
            colors: {
                ranges: [
                    { from: -1000, to: -0.1, color: POSEIDON_COLORS.danger },
                    { from: 0.1, to: 1000, color: POSEIDON_COLORS.success }
                ]
            }
        }
    };
    deviationSeries: ApexAxisChartSeries = [];
    deviationTooltip: ApexTooltip = {
        theme: 'dark',
        y: { formatter: (val: number) => `${val > 0 ? '+' : ''}${val.toFixed(1)}% vs global avg` }
    };
    deviationXAxis: ApexXAxis = {};
    deviationYAxis: ApexYAxis = {};
    goldenNiches: TradingAnalyticsActionableNiche[] = [];
    powerChart: ApexChart = this.buildBarChart();
    powerDataLabels: ApexDataLabels = {
        enabled: true,
        textAnchor: 'start',
        style: { colors: ['#fff'], fontSize: '10px', fontFamily: 'Inter, sans-serif' },
        formatter: (val: number) => `Influence: ${val.toFixed(1)}%`,
        offsetX: 0
    };

    powerGrid: ApexGrid = {
        ...baseTheme().grid,
        xaxis: { lines: { show: true } },
        yaxis: { lines: { show: false } },
        padding: { top: 0, right: 20, bottom: 0, left: 10 }
    };
    powerPlotOptions: ApexPlotOptions = {
        bar: {
            horizontal: true,
            borderRadius: 4,
            barHeight: '70%',
            colors: { ranges: [{ from: 0, to: 100, color: POSEIDON_COLORS.accent }] }
        }
    };
    powerSeries: ApexAxisChartSeries = [];
    powerTooltip: ApexTooltip = {
        theme: 'dark',
        y: { formatter: (val: number) => `${val.toFixed(1)}% Win Rate Amplitude` }
    };
    powerXAxis: ApexXAxis = {};
    powerYAxis: ApexYAxis = {};
    sortedMetricOrder: string[] = [];
    toxicZones: TradingAnalyticsActionableNiche[] = [];

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['scatterData'] && this.scatterData.length > 0) {
            this.computeDeviationProfile();
        }
        if (changes['pnlDriversSeries'] && this.pnlDriversSeries.length > 0) {
            this.computeNiches();
            this.computePowerRanking();
        }
    }

    private buildBarChart(): ApexChart {
        return {
            type: 'bar',
            toolbar: { show: false },
            zoom: { enabled: false },
            animations: { enabled: true, speed: 600 },
            height: 500
        };
    }

    private buildDeviationChart(): ApexChart {
        return {
            type: 'bar',
            toolbar: { show: false },
            zoom: { enabled: false },
            animations: { enabled: true, speed: 600 },
            height: 500
        };
    }

    private computeDeviationProfile(): void {
        const results: { label: string; key: string; deviation: number }[] = [];

        for (const series of this.scatterData) {
            const winValues: number[] = [];
            const globalValues: number[] = [];

            for (const point of series.points) {
                globalValues.push(point.metric_value);
                if (point.pnl_percentage > 0) {
                    winValues.push(point.metric_value);
                }
            }

            const getMedian = (values: number[]) => {
                if (values.length === 0) {
                    return 0;
                }
                values.sort((left, right) => left - right);
                const mid = Math.floor(values.length / 2);
                return values.length % 2 !== 0 ? values[mid] : (values[mid - 1] + values[mid]) / 2;
            };

            const winMedian = getMedian(winValues);
            const globalMedian = getMedian(globalValues);
            const deviationPercentage = globalMedian > 0 ? ((winMedian - globalMedian) / globalMedian) * 100 : 0;
            results.push({ label: series.metric_label, key: series.metric_key, deviation: deviationPercentage });
        }

        results.sort((left, right) => right.deviation - left.deviation);
        this.sortedMetricOrder = results.map((result) => result.key);

        this.deviationSeries = [{ name: 'Winner Deviation', data: results.map((result) => parseFloat(result.deviation.toFixed(1))) as never[] }];
        this.deviationXAxis = {
            categories: results.map((result) => result.label),
            labels: { style: { colors: '#94a3b8', fontSize: '11px', fontFamily: 'Inter, sans-serif' } },
            title: { text: '% Deviation from Global Average', style: { color: '#64748b', fontSize: '10px' } }
        };
    }

    private computeNiches(): void {
        const allGoldenCells: TradingAnalyticsActionableNiche[] = [];
        const allToxicCells: TradingAnalyticsActionableNiche[] = [];

        for (const series of this.pnlDriversSeries) {
            for (const cell of series.cells) {
                if (cell.sample_count >= 2) {
                    if (cell.is_golden) {
                        allGoldenCells.push({
                            metricLabel: series.metric_label,
                            rangeLabel: cell.range_label,
                            winRate: cell.win_rate_percentage,
                            sampleSize: cell.sample_count,
                            averagePnl: cell.average_pnl,
                            expectedPnlVelocity: cell.expected_pnl_velocity,
                            averageHoldingTime: cell.average_holding_time_minutes,
                            outlierHitRatePercentage: cell.outlier_hit_rate_percentage,
                            type: 'GOLDEN'
                        });
                    }
                    if (cell.is_toxic) {
                        allToxicCells.push({
                            metricLabel: series.metric_label,
                            rangeLabel: cell.range_label,
                            winRate: cell.win_rate_percentage,
                            sampleSize: cell.sample_count,
                            averagePnl: cell.average_pnl,
                            expectedPnlVelocity: cell.expected_pnl_velocity,
                            averageHoldingTime: cell.average_holding_time_minutes,
                            outlierHitRatePercentage: cell.outlier_hit_rate_percentage,
                            type: 'TOXIC'
                        });
                    }
                }
            }
        }

        const goldenSorted = [...allGoldenCells].sort((left, right) => {
            if (right.outlierHitRatePercentage !== left.outlierHitRatePercentage) {
                return right.outlierHitRatePercentage - left.outlierHitRatePercentage;
            }
            return right.expectedPnlVelocity - left.expectedPnlVelocity;
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

        const toxicSorted = [...allToxicCells].sort((left, right) => {
            if (left.expectedPnlVelocity !== right.expectedPnlVelocity) {
                return left.expectedPnlVelocity - right.expectedPnlVelocity;
            }
            return left.averagePnl - right.averagePnl;
        });

        this.toxicZones = [];
        const seenToxicMetrics = new Set<string>();
        for (const cell of toxicSorted) {
            if (!seenToxicMetrics.has(cell.metricLabel)) {
                this.toxicZones.push(cell);
                seenToxicMetrics.add(cell.metricLabel);
            }
            if (this.toxicZones.length >= 8) {
                break;
            }
        }
    }

    private computePowerRanking(): void {
        const rankings: { label: string; key: string; amplitude: number }[] = [];

        for (const series of this.pnlDriversSeries) {
            let maxWinRate = 0;
            let minWinRate = 100;
            let hasData = false;

            for (const cell of series.cells) {
                if (cell.sample_count >= 2) {
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
                rankings.push({ label: series.metric_label, key: series.metric_key, amplitude });
            }
        }

        const orderedRankings =
            this.sortedMetricOrder.length > 0
                ? this.sortedMetricOrder
                      .map((key) => rankings.find((ranking) => ranking.key === key))
                      .filter((ranking): ranking is { label: string; key: string; amplitude: number } => !!ranking)
                : rankings.sort((left, right) => right.amplitude - left.amplitude);

        this.powerSeries = [
            {
                name: 'Influence Power (%)',
                data: orderedRankings.map((ranking) => parseFloat(ranking.amplitude.toFixed(1))) as never[]
            }
        ];
        this.powerXAxis = {
            categories: orderedRankings.map((ranking) => ranking.label),
            labels: { style: { colors: '#94a3b8', fontSize: '11px' } },
            title: {
                text: 'Win Rate Amplitude between worst and best bucket',
                style: { color: '#64748b', fontSize: '10px' }
            }
        };
    }
}
