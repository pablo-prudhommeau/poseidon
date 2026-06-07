import { CommonModule } from '@angular/common';
import { Component, computed, ElementRef, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { SelectButtonModule } from 'primeng/selectbutton';
import type { TradingShadowingVerdictChroniclePayload } from '../../../../core/models';
import { WebSocketService } from '../../../../core/websocket.service';
import type { ChronicleLegendSeriesItem } from '../chart/trading-shadowing-verdict-chronicle-legend.adapter';
import { TradingShadowingVerdictChronicleSurfaceCoordinator } from '../chart/trading-shadowing-verdict-chronicle-surface.coordinator';
import type { ChronicleBucketMeta } from '../data/trading-shadowing-verdict-chronicle.models';
import { buildChronicleSnapshotFingerprint, type ChronicleBucketLabel } from '../data/trading-shadowing-verdict-chronicle-arrays.utils';
import { chronicleSeriesDisplayLabel } from '../data/trading-shadowing-verdict-chronicle-legend.utils';
import { CHRONICLE_SERIES } from '../data/trading-shadowing-verdict-chronicle-series-names';
import { TradingShadowingVerdictChronicleSciChartLoaderService } from '../services/trading-shadowing-verdict-chronicle-scichart-loader.service';

interface ChronicleBucketOption {
    label: string;
    value: ChronicleBucketLabel;
}

interface ChronicleSmaWindowOption {
    label: string;
    value: number;
}

const CHRONICLE_CORTEX_METRIC_SERIES_NAMES: string[] = [
    CHRONICLE_SERIES.cortexModelRolloutMarker,
    CHRONICLE_SERIES.cortexCalibrationBand,
    CHRONICLE_SERIES.averageCortexPredictionWinRateLine,
    CHRONICLE_SERIES.cortexSkillScoreLine,
    CHRONICLE_SERIES.cortexCalibrationGapLine,
    CHRONICLE_SERIES.cortexHighConvictionAccuracyLine,
    CHRONICLE_SERIES.cortexHighConvictionShareLine,
    CHRONICLE_SERIES.cortexGatePrecisionLine,
    CHRONICLE_SERIES.cortexGatePassRateLine
];

const CHRONICLE_SMA_CORTEX_METRIC_SERIES_NAMES: string[] = [
    CHRONICLE_SERIES.smaCortexPredictionWinRateLine,
    CHRONICLE_SERIES.smaCortexSkillScoreLine,
    CHRONICLE_SERIES.smaCortexCalibrationGapLine,
    CHRONICLE_SERIES.smaCortexHighConvictionAccuracyLine,
    CHRONICLE_SERIES.smaCortexHighConvictionShareLine,
    CHRONICLE_SERIES.smaCortexGatePrecisionLine,
    CHRONICLE_SERIES.smaCortexGatePassRateLine
];

@Component({
    standalone: true,
    selector: 'app-trading-shadowing-verdict-chronicle',
    imports: [CommonModule, DialogModule, ButtonModule, SelectButtonModule, FormsModule],
    templateUrl: './trading-shadowing-verdict-chronicle.component.html',
    styleUrl: './trading-shadowing-verdict-chronicle.component.css'
})
export class TradingShadowingVerdictChronicleComponent {
    readonly legendItems = signal<ChronicleLegendSeriesItem[]>([]);
    readonly allMetricsAvailable = computed<boolean>(() => this.legendItems().length > 0);

    readonly allMetricsChecked = computed<boolean>(() => {
        const items = this.legendItems();
        return items.length > 0 && items.every((item) => item.visible);
    });

    readonly allMetricsMixed = computed<boolean>(() => {
        const items = this.legendItems();
        return items.some((item) => item.visible) && !items.every((item) => item.visible);
    });

    readonly payload = signal<TradingShadowingVerdictChroniclePayload | null>(null);
    readonly selectedBucket = signal<ChronicleBucketLabel>('last_7d_15m');

    private readonly webSocketService: WebSocketService = inject(WebSocketService);

    readonly bucketMeta = computed<ChronicleBucketMeta | null>(() => {
        const response: TradingShadowingVerdictChroniclePayload | null = this.payload();
        const shadowingRegime = this.webSocketService.tradingShadowingRegime();
        const bucketId: ChronicleBucketLabel = this.selectedBucket();
        if (!response) {
            return null;
        }
        const bucket = response.buckets.find((entry) => entry.bucket_label === bucketId);
        return bucket
            ? {
                  bucket,
                  response,
                  sparseExpectedValueUsdThreshold: shadowingRegime?.edge_sparse_expected_value_usd_threshold,
                  chronicleProfitFactorThreshold: shadowingRegime?.edge_chronicle_profit_factor_threshold
              }
            : null;
    });

    readonly bucketOptions: ChronicleBucketOption[] = [
        { label: '30m · 1m', value: 'last_30m_1m' satisfies ChronicleBucketLabel },
        { label: '24h · 1h', value: 'last_24h_1h' satisfies ChronicleBucketLabel },
        { label: '7d · 15m', value: 'last_7d_15m' satisfies ChronicleBucketLabel },
        { label: '30d · 30m', value: 'last_30d_30m' satisfies ChronicleBucketLabel }
    ];

    readonly chartReady = signal<boolean>(false);
    readonly cortexMetricsAvailable = computed<boolean>(() => this.legendItems().some((item) => CHRONICLE_CORTEX_METRIC_SERIES_NAMES.includes(item.name)));

    readonly cortexMetricsChecked = computed<boolean>(() => {
        const cortexItems = this.legendItems().filter((item) => CHRONICLE_CORTEX_METRIC_SERIES_NAMES.includes(item.name));
        return cortexItems.length > 0 && cortexItems.every((item) => item.visible);
    });
    readonly cortexMetricsMixed = computed<boolean>(() => {
        const cortexItems = this.legendItems().filter((item) => CHRONICLE_CORTEX_METRIC_SERIES_NAMES.includes(item.name));
        return cortexItems.some((item) => item.visible) && !cortexItems.every((item) => item.visible);
    });

    readonly error = signal<string | null>(null);
    readonly selectedSmaWindow = signal<number>(50);
    readonly visible = signal<boolean>(false);
    readonly showChronicleLoader = computed<boolean>(() => this.visible() && !this.error() && (!this.payload() || !this.chartReady()));
    readonly showLegendPanel = signal<boolean>(true);
    readonly smaCortexMetricsAvailable = computed<boolean>(() =>
        this.legendItems().some((item) => CHRONICLE_SMA_CORTEX_METRIC_SERIES_NAMES.includes(item.name))
    );

    readonly smaCortexMetricsChecked = computed<boolean>(() => {
        const smaCortexItems = this.legendItems().filter((item) => CHRONICLE_SMA_CORTEX_METRIC_SERIES_NAMES.includes(item.name));
        return smaCortexItems.length > 0 && smaCortexItems.every((item) => item.visible);
    });

    readonly smaCortexMetricsMixed = computed<boolean>(() => {
        const smaCortexItems = this.legendItems().filter((item) => CHRONICLE_SMA_CORTEX_METRIC_SERIES_NAMES.includes(item.name));
        return smaCortexItems.some((item) => item.visible) && !smaCortexItems.every((item) => item.visible);
    });

    readonly smaWindowOptions: ChronicleSmaWindowOption[] = [
        { label: 'SMA (Range)', value: 0 },
        { label: 'SMA (10)', value: 10 },
        { label: 'SMA (30)', value: 30 },
        { label: 'SMA (50)', value: 50 },
        { label: 'SMA (100)', value: 100 },
        { label: 'SMA (200)', value: 200 },
        { label: 'SMA (400)', value: 400 }
    ];

    private readonly chartHost = viewChild<ElementRef<HTMLDivElement>>('chartHost');
    private readonly sciChartLoader: TradingShadowingVerdictChronicleSciChartLoaderService = inject(TradingShadowingVerdictChronicleSciChartLoaderService);

    private readonly surfaceCoordinator: TradingShadowingVerdictChronicleSurfaceCoordinator = new TradingShadowingVerdictChronicleSurfaceCoordinator(
        this.sciChartLoader
    );

    constructor() {
        effect(() => {
            const hist = this.webSocketService.tradingShadowingVerdictChronicle();
            const open = this.visible();
            if (!open || !hist) {
                return;
            }
            untracked(() => {
                void this.applySnapshot(hist);
            });
        });

        effect(() => {
            const open = this.visible();
            const payload = this.payload();
            const shadowingRegime = this.webSocketService.tradingShadowingRegime();
            const chartReady = this.chartReady();
            if (!open || !payload || !shadowingRegime || !chartReady) {
                return;
            }
            untracked(() => {
                void this.synchronizeChart(false, false);
            });
        });
    }

    handleDialogHide(): void {
        this.surfaceCoordinator.teardownChartSurface();
        this.payload.set(null);
        this.chartReady.set(false);
        this.legendItems.set([]);
        this.showLegendPanel.set(true);
    }

    handleDialogShow(): void {
        const hist = this.webSocketService.tradingShadowingVerdictChronicle();
        if (hist) {
            void this.applySnapshot(hist);
        }
    }

    legendSeriesLabel(seriesName: string): string {
        return chronicleSeriesDisplayLabel(seriesName);
    }

    onAllMetricsToggle(nextVisible: boolean): void {
        for (const item of this.legendItems()) {
            this.surfaceCoordinator.setSeriesVisibility(item.name, nextVisible);
        }
        this.syncLegendFromChart();
    }

    onBucketChange(): void {
        if (this.visible() && this.payload()) {
            void this.synchronizeChart(false, true);
        }
    }

    onCortexMetricsToggle(nextVisible: boolean): void {
        for (const item of this.legendItems()) {
            if (CHRONICLE_CORTEX_METRIC_SERIES_NAMES.includes(item.name)) {
                this.surfaceCoordinator.setSeriesVisibility(item.name, nextVisible);
            }
        }
        this.syncLegendFromChart();
    }

    onLegendItemToggle(seriesName: string, nextVisible: boolean): void {
        this.surfaceCoordinator.setSeriesVisibility(seriesName, nextVisible);
        this.syncLegendFromChart();
    }

    onSmaCortexMetricsToggle(nextVisible: boolean): void {
        for (const item of this.legendItems()) {
            if (CHRONICLE_SMA_CORTEX_METRIC_SERIES_NAMES.includes(item.name)) {
                this.surfaceCoordinator.setSeriesVisibility(item.name, nextVisible);
            }
        }
        this.syncLegendFromChart();
    }

    onSmaWindowChange(): void {
        if (this.visible() && this.payload()) {
            void this.synchronizeChart(false, true);
        }
    }

    onVisibleChange(next: boolean): void {
        this.visible.set(next);
    }

    open(): void {
        this.error.set(null);
        this.visible.set(true);
    }

    retry(): void {
        this.error.set(null);
        this.webSocketService.requestCachedStateRefresh();
    }

    toggleLegendPanel(): void {
        this.showLegendPanel.update((value) => !value);
    }

    private async applySnapshot(hist: TradingShadowingVerdictChroniclePayload): Promise<void> {
        const existing = this.payload();
        if (this.surfaceCoordinator.hasChartModel() && existing && buildChronicleSnapshotFingerprint(existing) === buildChronicleSnapshotFingerprint(hist)) {
            return;
        }
        this.payload.set(hist);
        await this.scheduleChartSynchronization();
    }

    private async scheduleChartSynchronization(): Promise<void> {
        for (let attempt = 0; attempt < 24; attempt++) {
            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
            const host = this.chartHost()?.nativeElement;
            if (host) {
                await this.synchronizeChart(true, false);
                return;
            }
            await new Promise<void>((resolve) => setTimeout(resolve, 20));
        }
    }

    private async synchronizeChart(allowInitialBuild: boolean, snapBucketData: boolean): Promise<void> {
        const host = this.chartHost()?.nativeElement;
        const meta = this.bucketMeta();
        if (!host || !meta) {
            return;
        }

        await this.surfaceCoordinator.synchronizeChartSurface(
            host,
            meta,
            {
                allowInitialBuild: allowInitialBuild,
                snapBucketData: snapBucketData,
                smaWindowBuckets: this.selectedSmaWindow()
            },
            () => this.chartReady.set(true)
        );
        this.syncLegendFromChart();
    }

    private syncLegendFromChart(): void {
        this.legendItems.set(this.surfaceCoordinator.listLegendSeries());
    }
}
