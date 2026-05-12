import { CommonModule } from '@angular/common';
import { Component, Input, inject } from '@angular/core';
import { MetricsFormattingService } from '../../../core/metrics-formatting.service';
import {
    TradingEvaluationShadowIntelligenceSnapshotMetricPayload,
    TradingEvaluationShadowIntelligenceSnapshotPayload,
    TradingEvaluationShadowIntelligenceSnapshotSummaryPayload
} from '../../../core/models';
import { NumberFormattingService } from '../../../core/number-formatting.service';
import { EXPLORATION_CATEGORIES, MetricCategory } from '../trading.constants';

@Component({
    standalone: true,
    selector: 'trading-shadow-intelligence-tab',
    imports: [CommonModule],
    templateUrl: './trading-shadow-intelligence-tab.component.html',
    styleUrl: './trading-shadow-intelligence-tab.component.css'
})
export class TradingShadowIntelligenceTabComponent {
    @Input() snapshot: TradingEvaluationShadowIntelligenceSnapshotPayload | null = null;
    private readonly metricsFormattingService = inject(MetricsFormattingService);

    private readonly numberFormattingService = inject(NumberFormattingService);

    public formatMetricLabel(metricKey: string): string {
        return this.metricsFormattingService.formatMetricLabel(metricKey);
    }

    public formatMetricValue(metricKey: string, value: number | null | undefined): string {
        return this.metricsFormattingService.formatMetricValue(metricKey, value);
    }

    public formatUsd(value: number | null | undefined): string {
        return this.numberFormattingService.formatUsdCompactForGrid(value) ?? '—';
    }

    public groupedShadowMetrics(
        snapshotValue: TradingEvaluationShadowIntelligenceSnapshotPayload | null
    ): { category: MetricCategory; metrics: TradingEvaluationShadowIntelligenceSnapshotMetricPayload[] }[] {
        if (!snapshotValue || !snapshotValue.evaluated_metrics) {
            return [];
        }
        const metricsMap = new Map(snapshotValue.evaluated_metrics.map((metric) => [metric.metric_key, metric]));
        return EXPLORATION_CATEGORIES.map((category) => {
            const metrics = category.metricKeys
                .map((key) => metricsMap.get(key))
                .filter((metric): metric is TradingEvaluationShadowIntelligenceSnapshotMetricPayload => !!metric)
                .sort((a, b) => (b.bucket_win_rate || 0) - (a.bucket_win_rate || 0));
            return { category, metrics };
        }).filter((group) => group.metrics.length > 0);
    }

    public outcomeCoverage(summary: TradingEvaluationShadowIntelligenceSnapshotSummaryPayload | null | undefined): number {
        if (!summary || summary.total_outcomes_analyzed <= 0) {
            return 0;
        }
        return this.clampPercentage((summary.resolved_outcome_count / summary.total_outcomes_analyzed) * 100);
    }

    public thresholdCoverage(value: number | null | undefined, threshold: number | null | undefined): number {
        if (value === null || value === undefined || threshold === null || threshold === undefined || threshold <= 0) {
            return 0;
        }
        return this.clampPercentage((value / threshold) * 100);
    }

    private clampPercentage(value: number): number {
        if (!Number.isFinite(value)) {
            return 0;
        }
        return Math.max(0, Math.min(100, value));
    }
}
