import {Component, computed, effect, ElementRef, inject, signal, untracked, viewChild,} from '@angular/core';
import {CommonModule} from '@angular/common';
import {DialogModule} from 'primeng/dialog';
import {ButtonModule} from 'primeng/button';
import {SelectButtonModule} from 'primeng/selectbutton';
import {FormsModule} from '@angular/forms';
import {WebSocketService} from '../../../../core/websocket.service';
import type {ShadowVerdictChronicleResponse} from '../../../../core/models';
import {buildShadowVerdictChronicleFingerprint, type ShadowVerdictChronicleBucketLabel,} from '../data/shadow-verdict-chronicle-chart-data';
import {ShadowVerdictChronicleSciChartLoaderService} from '../services/shadow-verdict-chronicle-scichart-loader.service';
import {ShadowVerdictChronicleSurfaceController} from '../controllers/shadow-verdict-chronicle-chart-surface-session.controller';

@Component({
    standalone: true,
    selector: 'app-shadow-verdict-chronicle',
    imports: [CommonModule, DialogModule, ButtonModule, SelectButtonModule, FormsModule],
    templateUrl: './shadow-verdict-chronicle.component.html',
    styleUrl: './shadow-verdict-chronicle.component.css',
})
export class ShadowVerdictChronicleComponent {
    private readonly webSocketService = inject(WebSocketService);
    private readonly sciChartLoader = inject(ShadowVerdictChronicleSciChartLoaderService);
    private readonly chartHost = viewChild<ElementRef<HTMLDivElement>>('chartHost');

    private readonly surfaceController = new ShadowVerdictChronicleSurfaceController(this.sciChartLoader);

    readonly visible = signal(false);
    readonly error = signal<string | null>(null);
    readonly payload = signal<ShadowVerdictChronicleResponse | null>(null);

    readonly chartReady = signal(false);

    readonly showChronicleLoader = computed(
        () => this.visible() && !this.error() && (!this.payload() || !this.chartReady()),
    );

    readonly bucketOptions = [
        {label: '30m · 1m', value: 'last_30m_1m' satisfies ShadowVerdictChronicleBucketLabel},
        {label: '24h · 1h', value: 'last_24h_1h' satisfies ShadowVerdictChronicleBucketLabel},
        {label: '7d · 5m', value: 'last_7d_5m' satisfies ShadowVerdictChronicleBucketLabel},
        {label: '30d · 30m', value: 'last_30d_30m' satisfies ShadowVerdictChronicleBucketLabel},
    ];

    readonly smaWindowOptions = [
        {label: 'SMA (Range)', value: 0},
        {label: 'SMA (10)', value: 10},
        {label: 'SMA (30)', value: 30},
        {label: 'SMA (50)', value: 50},
        {label: 'SMA (100)', value: 100},
        {label: 'SMA (200)', value: 200},
        {label: 'SMA (400)', value: 400}
    ];

    selectedBucket = signal<ShadowVerdictChronicleBucketLabel>('last_30m_1m');
    selectedSmaWindow = signal<number>(0);

    readonly bucketMeta = computed(() => {
        const response = this.payload();
        const bucketId = this.selectedBucket();
        if (!response) {
            return null;
        }
        const bucket = response.buckets.find(b => b.bucket_label === bucketId);
        return bucket ? {bucket, response} : null;
    });

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
    }

    open(): void {
        this.error.set(null);
        this.visible.set(true);
    }

    onVisibleChange(next: boolean): void {
        this.visible.set(next);
    }

    handleDialogShow(): void {
        const hist = this.webSocketService.shadowHistory();
        if (hist) {
            void this.applySnapshot(hist);
        }
    }

    handleDialogHide(): void {
        this.surfaceController.teardownChartSurface();
        this.payload.set(null);
        this.chartReady.set(false);
    }

    onBucketChange(): void {
        if (this.visible() && this.payload()) {
            void this.synchronizeChart(false, true);
        }
    }

    onSmaWindowChange(): void {
        if (this.visible() && this.payload()) {
            void this.synchronizeChart(false, true);
        }
    }

    retry(): void {
        this.error.set(null);
        this.webSocketService.requestCachedStateRefresh();
    }

    private async applySnapshot(hist: ShadowVerdictChronicleResponse): Promise<void> {
        const existing = this.payload();
        if (
            this.surfaceController.hasChartModel() &&
            existing &&
            buildShadowVerdictChronicleFingerprint(existing) === buildShadowVerdictChronicleFingerprint(hist)
        ) {
            return;
        }
        this.payload.set(hist);
        await this.scheduleChartSynchronization();
    }

    private async scheduleChartSynchronization(): Promise<void> {
        for (let attempt = 0; attempt < 24; attempt++) {
            await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
            const host = this.chartHost()?.nativeElement;
            if (host) {
                await this.synchronizeChart(true, false);
                return;
            }
            await new Promise<void>(resolve => setTimeout(resolve, 20));
        }
    }

    private async synchronizeChart(allowInitialBuild: boolean, snapBucketData: boolean): Promise<void> {
        const host = this.chartHost()?.nativeElement;
        const meta = this.bucketMeta();
        if (!host || !meta) {
            return;
        }

        await this.surfaceController.synchronizeChartSurface(
            host,
            meta,
            {allowInitialBuild, snapBucketData, smaWindowBuckets: this.selectedSmaWindow()},
            () => this.chartReady.set(true),
        );
    }
}
