import { CommonModule } from '@angular/common';
import { Component, inject, Input } from '@angular/core';
import { MetricsFormattingService } from '../../../core/metrics-formatting.service';
import {
    TradingCortexInferenceSnapshotPayload,
    TradingEvaluationShadowingMetricEvaluationPayload,
    TradingEvaluationShadowingSnapshotPayload
} from '../../../core/models';
import { EXPLORATION_CATEGORIES, MetricCategory } from '../trading.constants';
import { TradingOverviewShadowingRegimeComponent } from '../trading-overview/trading-overview-shadowing-regime/trading-overview-shadowing-regime.component';

@Component({
    standalone: true,
    selector: 'trading-shadowing-snapshot-tab',
    imports: [CommonModule, TradingOverviewShadowingRegimeComponent],
    templateUrl: './trading-shadowing-snapshot-tab.component.html',
    styleUrl: './trading-shadowing-snapshot-tab.component.css'
})
export class TradingShadowingSnapshotTabComponent {
    @Input() snapshot: TradingEvaluationShadowingSnapshotPayload | null = null;

    private readonly metricsFormattingService = inject(MetricsFormattingService);

    public cortexInference(snapshotValue: TradingEvaluationShadowingSnapshotPayload | null): TradingCortexInferenceSnapshotPayload | null {
        return snapshotValue?.cortex_inference ?? null;
    }

    public formatMetricLabel(metricKey: string): string {
        return this.metricsFormattingService.formatMetricLabel(metricKey);
    }

    public formatMetricValue(metricKey: string, value: number | null | undefined): string {
        return this.metricsFormattingService.formatMetricValue(metricKey, value);
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
}
