import type {
    ChronicleArrays,
    ChronicleBucketMeta,
    ChronicleChartModel,
    ChronicleGoldenZoneThresholds,
    ChronicleSurfaceSyncOptions
} from '../data/shadow-verdict-chronicle.models';
import {
    blendChronicleArrays,
    buildChronicleArraysFromBucket,
    CHRONICLE_SNAPSHOT_BLEND_MS,
    CHRONICLE_STREAM_LAG_MS_FALLBACK,
    chronicleMinimumDisplayXMilliseconds,
    chronicleShouldShowTargetVerdictCloud,
    cloneChronicleArrays,
    computeChronicleViewportWidthMilliseconds,
    extendChronicleArraysToTapeRight,
    parseIsoTimestampToEpochMilliseconds,
    resolveChronicleStreamLagMilliseconds
} from '../data/shadow-verdict-chronicle-arrays.utils';
import type { ShadowVerdictChronicleSciChartLoaderService } from '../services/shadow-verdict-chronicle-scichart-loader.service';
import {
    applyChronicleGoldenZoneVisualState,
    isChronicleMovingAverageSeriesVisible,
    resolveChronicleGoldenZoneThresholds
} from './shadow-verdict-chronicle-golden-zone.utils';
import type { ChronicleLegendSeriesItem } from './shadow-verdict-chronicle-legend.adapter';
import { listChronicleLegendSeries, setChronicleSeriesVisibility } from './shadow-verdict-chronicle-legend.adapter';
import { harmonizeChronicleRightAxes } from './shadow-verdict-chronicle-right-axis.utils';
import {
    synchronizeChronicleSeriesFromArrays,
    synchronizeChronicleTapeBoundSeries,
    synchronizeChronicleVerdictCloudSeries
} from './shadow-verdict-chronicle-series-sync.utils';
import { ShadowVerdictChronicleSurfaceBuilder } from './shadow-verdict-chronicle-surface.builder';

export class ShadowVerdictChronicleSurfaceCoordinator {
    private static readonly RIGHT_AXIS_MAJOR_TICK_COUNT: number = 8;
    private static readonly SMA_EV_SERIES_NAME = 'SMA EV per trade';
    private static readonly SMA_PF_SERIES_NAME = 'SMA profit factor';

    private blendFromArrays: ChronicleArrays | null = null;
    private blendStartPerformanceMs: number | null = null;
    private blendToArrays: ChronicleArrays | null = null;
    private chartModel: ChronicleChartModel | undefined;
    private displayArrays: ChronicleArrays | null = null;
    private goldenZoneThresholds: ChronicleGoldenZoneThresholds = {
        sparseExpectedValueThreshold: undefined,
        chronicleProfitFactorThreshold: undefined
    };
    private pendingTapeAnchorWallClockMs: number | undefined;
    private playbackRequestAnimationFrameId: number | null = null;
    private sciChartSurface: ChronicleChartModel['sciChartSurface'] | undefined;
    private readonly surfaceBuilder: ShadowVerdictChronicleSurfaceBuilder = new ShadowVerdictChronicleSurfaceBuilder();
    private tapeAnchorPerformanceMs: number | null = null;
    private tapeAnchorWallClockMs: number = 0;

    constructor(private readonly sciChartLoader: ShadowVerdictChronicleSciChartLoaderService) {}

    hasChartModel(): boolean {
        return this.chartModel !== undefined;
    }

    listLegendSeries(): ChronicleLegendSeriesItem[] {
        const model = this.chartModel;
        if (!model) {
            return [];
        }
        return listChronicleLegendSeries(model);
    }

    setSeriesVisibility(seriesName: string, isVisible: boolean): void {
        const model = this.chartModel;
        if (!model) {
            return;
        }
        setChronicleSeriesVisibility(model, seriesName, isVisible);
        this.applyGoldenZoneVisualState();
        model.sciChartSurface.invalidateElement();
    }

    async synchronizeChartSurface(
        host: HTMLDivElement,
        meta: ChronicleBucketMeta,
        options: ChronicleSurfaceSyncOptions,
        notifyChartReady: () => void
    ): Promise<void> {
        try {
            if (!this.chartModel) {
                if (!options.allowInitialBuild) {
                    return;
                }
                await this.buildFullChartSurface(host, meta, options.smaWindowBuckets);
                return;
            }
            this.updateChartData(meta, options.snapBucketData, options.smaWindowBuckets);
        } finally {
            if (this.chartModel) {
                notifyChartReady();
            }
        }
    }

    teardownChartSurface(): void {
        this.stopPlaybackLoop();
        this.displayArrays = null;
        this.blendFromArrays = null;
        this.blendToArrays = null;
        this.blendStartPerformanceMs = null;
        this.tapeAnchorPerformanceMs = null;
        this.pendingTapeAnchorWallClockMs = undefined;
        this.goldenZoneThresholds = {
            sparseExpectedValueThreshold: undefined,
            chronicleProfitFactorThreshold: undefined
        };
        this.chartModel = undefined;
        if (this.sciChartSurface) {
            try {
                this.sciChartSurface.delete();
            } catch {}
            this.sciChartSurface = undefined;
        }
    }

    private applyGoldenZoneVisualState(): void {
        const model = this.chartModel;
        if (!model) {
            return;
        }
        const isSmaExpectedValueVisible = isChronicleMovingAverageSeriesVisible(model, ShadowVerdictChronicleSurfaceCoordinator.SMA_EV_SERIES_NAME);
        const isSmaProfitFactorVisible = isChronicleMovingAverageSeriesVisible(model, ShadowVerdictChronicleSurfaceCoordinator.SMA_PF_SERIES_NAME);
        applyChronicleGoldenZoneVisualState(model, this.goldenZoneThresholds, isSmaExpectedValueVisible, isSmaProfitFactorVisible);
    }

    private async buildFullChartSurface(host: HTMLDivElement, meta: ChronicleBucketMeta, smaWindowBuckets: number): Promise<void> {
        this.teardownChartSurface();

        this.chartModel = await this.surfaceBuilder.buildFullChartSurface(host, meta, this.sciChartLoader, smaWindowBuckets);
        this.sciChartSurface = this.chartModel.sciChartSurface;

        const streamLagMilliseconds = resolveChronicleStreamLagMilliseconds(meta.response.series_end_lag_seconds);
        const chronicleArrays = buildChronicleArraysFromBucket(meta, streamLagMilliseconds, smaWindowBuckets);
        this.displayArrays = cloneChronicleArrays(chronicleArrays);
        this.blendFromArrays = null;
        this.blendToArrays = null;
        this.blendStartPerformanceMs = null;

        this.queueTapeAnchorFromMeta(meta);
        this.startPlaybackLoop(true);
    }

    private queueTapeAnchorFromMeta(meta: ChronicleBucketMeta): void {
        const parsed = parseIsoTimestampToEpochMilliseconds(meta.response.as_of_iso);
        if (parsed != null) {
            this.pendingTapeAnchorWallClockMs = parsed;
        }
    }

    private startPlaybackLoop(resetTapeAnchors: boolean): void {
        this.stopPlaybackLoop();
        if (resetTapeAnchors || this.tapeAnchorPerformanceMs == null) {
            this.tapeAnchorWallClockMs = this.pendingTapeAnchorWallClockMs ?? Date.now() - CHRONICLE_STREAM_LAG_MS_FALLBACK;
            this.pendingTapeAnchorWallClockMs = undefined;
            this.tapeAnchorPerformanceMs = performance.now();
        }

        const tick = (): void => {
            const model = this.chartModel;
            if (!model) {
                this.stopPlaybackLoop();
                return;
            }

            if (this.blendFromArrays && this.blendToArrays && this.blendStartPerformanceMs != null) {
                const rawAlpha = (performance.now() - this.blendStartPerformanceMs) / CHRONICLE_SNAPSHOT_BLEND_MS;
                if (rawAlpha >= 1) {
                    this.displayArrays = cloneChronicleArrays(this.blendToArrays);
                    this.blendFromArrays = null;
                    this.blendToArrays = null;
                    this.blendStartPerformanceMs = null;
                } else {
                    this.displayArrays = blendChronicleArrays(this.blendFromArrays, this.blendToArrays, rawAlpha);
                }
                if (this.displayArrays && chronicleShouldShowTargetVerdictCloud(rawAlpha)) {
                    synchronizeChronicleVerdictCloudSeries(model, this.displayArrays);
                }
            }

            const { NumberRange, EAutoRange } = model.sci;
            const performanceBase = this.tapeAnchorPerformanceMs ?? performance.now();
            const rightEdgeMs = this.tapeAnchorWallClockMs + (performance.now() - performanceBase);
            if (this.displayArrays) {
                const tapeArrays = extendChronicleArraysToTapeRight(this.displayArrays, rightEdgeMs);
                synchronizeChronicleTapeBoundSeries(model, tapeArrays, this.goldenZoneThresholds);
                this.applyGoldenZoneVisualState();
                harmonizeChronicleRightAxes(model, tapeArrays, ShadowVerdictChronicleSurfaceCoordinator.RIGHT_AXIS_MAJOR_TICK_COUNT, this.goldenZoneThresholds);
                const earliestDisplayXMilliseconds = chronicleMinimumDisplayXMilliseconds(tapeArrays);
                const naturalLeftEdgeMilliseconds = rightEdgeMs - model.viewportWidthMilliseconds;
                const leftEdgeClampMilliseconds = earliestDisplayXMilliseconds - 45_000;
                const leftEdgeMs = Math.max(naturalLeftEdgeMilliseconds, leftEdgeClampMilliseconds);
                model.xAxis.autoRange = EAutoRange.Never;
                model.xAxis.visibleRange = new NumberRange(leftEdgeMs, rightEdgeMs);
            } else {
                const leftEdgeMs = rightEdgeMs - model.viewportWidthMilliseconds;
                model.xAxis.autoRange = EAutoRange.Never;
                model.xAxis.visibleRange = new NumberRange(leftEdgeMs, rightEdgeMs);
            }
            model.sciChartSurface.invalidateElement();

            this.playbackRequestAnimationFrameId = requestAnimationFrame(tick);
        };

        this.playbackRequestAnimationFrameId = requestAnimationFrame(tick);
    }

    private stopPlaybackLoop(): void {
        if (this.playbackRequestAnimationFrameId != null) {
            cancelAnimationFrame(this.playbackRequestAnimationFrameId);
            this.playbackRequestAnimationFrameId = null;
        }
    }

    private synchronizeGoldenZones(meta: ChronicleBucketMeta): void {
        this.goldenZoneThresholds = resolveChronicleGoldenZoneThresholds(meta);
        this.applyGoldenZoneVisualState();
    }

    private updateChartData(meta: ChronicleBucketMeta, snapBucketData = false, smaWindowBuckets = 0): void {
        const model = this.chartModel;
        if (!model) {
            return;
        }
        this.synchronizeGoldenZones(meta);
        const streamLagMilliseconds = resolveChronicleStreamLagMilliseconds(meta.response.series_end_lag_seconds);
        const nextArrays = buildChronicleArraysFromBucket(meta, streamLagMilliseconds, smaWindowBuckets);
        const computedViewportWidthMilliseconds = computeChronicleViewportWidthMilliseconds(nextArrays);
        if (snapBucketData) {
            model.viewportWidthMilliseconds = computedViewportWidthMilliseconds;
        } else {
            const previousViewportWidthMilliseconds = model.viewportWidthMilliseconds;
            model.viewportWidthMilliseconds =
                computedViewportWidthMilliseconds >= previousViewportWidthMilliseconds
                    ? Math.max(previousViewportWidthMilliseconds, computedViewportWidthMilliseconds)
                    : computedViewportWidthMilliseconds;
        }
        const bucketMilliseconds = Math.max(1000, meta.bucket.granularity_seconds * 1000);
        model.volumeColumnRenderableSeries.dataPointWidthMode = model.sci.EDataPointWidthMode.Range;
        model.volumeColumnRenderableSeries.dataPointWidth = bucketMilliseconds * 0.88;

        if (snapBucketData) {
            this.blendFromArrays = null;
            this.blendToArrays = null;
            this.blendStartPerformanceMs = null;
            this.displayArrays = cloneChronicleArrays(nextArrays);
            synchronizeChronicleSeriesFromArrays(model, this.displayArrays, this.goldenZoneThresholds);
            model.sciChartSurface.invalidateElement();
            this.queueTapeAnchorFromMeta(meta);
            this.startPlaybackLoop(true);
            return;
        }

        if (!this.displayArrays) {
            this.displayArrays = cloneChronicleArrays(nextArrays);
            synchronizeChronicleSeriesFromArrays(model, this.displayArrays, this.goldenZoneThresholds);
            model.sciChartSurface.invalidateElement();
            this.queueTapeAnchorFromMeta(meta);
            this.startPlaybackLoop(true);
            return;
        }

        this.queueTapeAnchorFromMeta(meta);
        this.blendFromArrays = cloneChronicleArrays(this.displayArrays);
        this.blendToArrays = cloneChronicleArrays(nextArrays);
        this.blendStartPerformanceMs = performance.now();
        this.startPlaybackLoop(false);
    }
}
