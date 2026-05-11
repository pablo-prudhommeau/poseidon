import {CommonModule} from '@angular/common';
import {Component, Input, inject} from '@angular/core';

import {EXPLORATION_CATEGORIES, MetricCategory} from '../../../core/constants';
import {MetricsFormattingService} from '../../../core/metrics-formatting.service';
import {NumberFormattingService} from '../../../core/number-formatting.service';
import {
    TradingEvaluationShadowIntelligenceSnapshotMetricPayload,
    TradingEvaluationShadowIntelligenceSnapshotPayload,
} from '../../../core/models';

@Component({
    standalone: true,
    selector: 'trading-shadow-intelligence-tab',
    imports: [CommonModule],
    templateUrl: './trading-shadow-intelligence-tab.component.html',
})
export class TradingShadowIntelligenceTabComponent {
    private readonly metricsFormattingService = inject(MetricsFormattingService);
    private readonly numberFormattingService = inject(NumberFormattingService);

    @Input() snapshot: TradingEvaluationShadowIntelligenceSnapshotPayload | null = null;

    public groupedShadowMetrics(
        snapshotValue: TradingEvaluationShadowIntelligenceSnapshotPayload | null,
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
            return {category, metrics};
        }).filter((group) => group.metrics.length > 0);
    }

    public formatMetricLabel(metricKey: string): string {
        return this.metricsFormattingService.formatMetricLabel(metricKey);
    }

    public formatMetricValue(metricKey: string, value: number | null | undefined): string {
        return this.metricsFormattingService.formatMetricValue(metricKey, value);
    }

    public formatUsd(value: number | null | undefined): string {
        return this.numberFormattingService.formatUsdCompactForGrid(value) ?? '—';
    }
}
