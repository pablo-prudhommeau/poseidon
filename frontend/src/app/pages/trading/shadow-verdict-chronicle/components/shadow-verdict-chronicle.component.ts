import { CommonModule } from '@angular/common';
import { Component, computed, ElementRef, effect, inject, signal, untracked, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { DialogModule } from 'primeng/dialog';
import { SelectButtonModule } from 'primeng/selectbutton';
import type { ShadowVerdictChronicleResponse } from '../../../../core/models';
import { WebSocketService } from '../../../../core/websocket.service';
import type { ChronicleLegendSeriesItem } from '../chart/shadow-verdict-chronicle-legend.adapter';
import { ShadowVerdictChronicleSurfaceCoordinator } from '../chart/shadow-verdict-chronicle-surface.coordinator';
import type { ChronicleBucketMeta } from '../data/shadow-verdict-chronicle.models';
import { buildChronicleSnapshotFingerprint, type ChronicleBucketLabel } from '../data/shadow-verdict-chronicle-arrays.utils';
import { ShadowVerdictChronicleSciChartLoaderService } from '../services/shadow-verdict-chronicle-scichart-loader.service';

interface ChronicleBucketOption {
    label: string;
    value: ChronicleBucketLabel;
}

interface ChronicleSmaWindowOption {
    label: string;
    value: number;
}

@Component({
    standalone: true,
    selector: 'app-shadow-verdict-chronicle',
    imports: [CommonModule, DialogModule, ButtonModule, SelectButtonModule, FormsModule],
    templateUrl: './shadow-verdict-chronicle.component.html',
    styleUrl: './shadow-verdict-chronicle.component.css'
})
export class ShadowVerdictChronicleComponent {
    readonly payload = signal<ShadowVerdictChronicleResponse | null>(null);

    selectedBucket = signal<ChronicleBucketLabel>('last_7d_5m');

    private readonly webSocketService: WebSocketService = inject(WebSocketService);

    readonly bucketMeta = computed<ChronicleBucketMeta | null>(() => {
        const response: ShadowVerdictChronicleResponse | null = this.payload();
        const shadowMeta = this.webSocketService.shadowMeta();
        const bucketId: ChronicleBucketLabel = this.selectedBucket();
        if (!response) {
            return null;
        }
        const bucket = response.buckets.find((entry) => entry.bucket_label === bucketId);
        return bucket
            ? {
                  bucket,
                  response,
                  sparseExpectedValueUsdThreshold: shadowMeta?.sparse_expected_value_usd_threshold,
                  chronicleProfitFactorThreshold: shadowMeta?.chronicle_profit_factor_threshold
              }
            : null;
    });

    readonly bucketOptions: ChronicleBucketOption[] = [
        { label: '30m · 1m', value: 'last_30m_1m' satisfies ChronicleBucketLabel },
        { label: '24h · 1h', value: 'last_24h_1h' satisfies ChronicleBucketLabel },
        { label: '7d · 5m', value: 'last_7d_5m' satisfies ChronicleBucketLabel },
        { label: '30d · 30m', value: 'last_30d_30m' satisfies ChronicleBucketLabel }
    ];
    readonly chartReady = signal<boolean>(false);
    readonly error = signal<string | null>(null);

    readonly legendItems = signal<ChronicleLegendSeriesItem[]>([]);
    selectedSmaWindow = signal<number>(50);
    readonly visible = signal<boolean>(false);

    readonly showChronicleLoader = computed<boolean>(() => this.visible() && !this.error() && (!this.payload() || !this.chartReady()));

    readonly showLegendPanel = signal<boolean>(true);

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
    private readonly sciChartLoader: ShadowVerdictChronicleSciChartLoaderService = inject(ShadowVerdictChronicleSciChartLoaderService);

    private readonly surfaceCoordinator: ShadowVerdictChronicleSurfaceCoordinator = new ShadowVerdictChronicleSurfaceCoordinator(this.sciChartLoader);

    constructor() {
        effect(() => {
            const hist = this.webSocketService.shadowHistory();
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
            const shadowMeta = this.webSocketService.shadowMeta();
            const chartReady = this.chartReady();
            if (!open || !payload || !shadowMeta || !chartReady) {
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
        const hist = this.webSocketService.shadowHistory();
        if (hist) {
            void this.applySnapshot(hist);
        }
    }

    onBucketChange(): void {
        if (this.visible() && this.payload()) {
            void this.synchronizeChart(false, true);
        }
    }

    onLegendItemToggle(seriesName: string, nextVisible: boolean): void {
        this.surfaceCoordinator.setSeriesVisibility(seriesName, nextVisible);
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

    private async applySnapshot(hist: ShadowVerdictChronicleResponse): Promise<void> {
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
