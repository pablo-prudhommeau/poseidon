import { CommonModule } from '@angular/common';
import { Component, inject, Input } from '@angular/core';
import { MetricsFormattingService } from '../../../core/metrics-formatting.service';
import {
    TradingEvaluationShadowingMetricEvaluationPayload,
    TradingEvaluationShadowingSnapshotPayload,
    TradingShadowingRegimePayload
} from '../../../core/models';
import { NumberFormattingService } from '../../../core/number-formatting.service';
import { EXPLORATION_CATEGORIES, MetricCategory } from '../trading.constants';

@Component({
    standalone: true,
    selector: 'trading-shadowing-snapshot-tab',
    imports: [CommonModule],
    templateUrl: './trading-shadowing-snapshot-tab.component.html',
    styleUrl: './trading-shadowing-snapshot-tab.component.css'
})
export class TradingShadowingSnapshotTabComponent {
    @Input() snapshot: TradingEvaluationShadowingSnapshotPayload | null = null;
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

    public groupedShadowingMetrics(
        snapshotValue: TradingEvaluationShadowingSnapshotPayload | null
    ): { category: MetricCategory; metrics: TradingEvaluationShadowingMetricEvaluationPayload[] }[] {
        if (!snapshotValue || !snapshotValue.metrics) {
            return [];
        }
        const metricsMap = new Map(snapshotValue.metrics.map((metric) => [metric.metric_key, metric]));
        return EXPLORATION_CATEGORIES.map((category) => {
            const metrics = category.metricKeys
                .map((key) => metricsMap.get(key))
                .filter((metric): metric is TradingEvaluationShadowingMetricEvaluationPayload => !!metric)
                .sort((a, b) => (b.bucket_win_rate || 0) - (a.bucket_win_rate || 0));
            return { category, metrics };
        }).filter((group) => group.metrics.length > 0);
    }

    public outcomeCoverage(regime: TradingShadowingRegimePayload | null | undefined): number {
        if (!regime || !regime.required_outcome_count || regime.required_outcome_count <= 0) {
            return 0;
        }
        return this.clampPercentage(((regime.resolved_outcome_count ?? 0) / regime.required_outcome_count) * 100);
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
