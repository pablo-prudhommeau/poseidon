import type {XyzDataSeries} from 'scichart';
import {
    blendChronicleArrays,
    buildChronicleArraysFromBucket,
    CHRONICLE_SNAPSHOT_BLEND_MS,
    CHRONICLE_STREAM_LAG_MS_FALLBACK,
    type ChronicleArrays,
    type ChronicleBucketMeta,
    type ChronicleChartModel,
    chronicleMinimumDisplayXMilliseconds,
    chronicleShouldShowTargetVerdictCloud,
    cloneChronicleArrays,
    computeChronicleViewportWidthMilliseconds,
    extendChronicleArraysToTapeRight,
    parseIsoTimestampToEpochMilliseconds,
    resolveChronicleStreamLagMilliseconds,
    type SciChartModule,
} from '../data/shadow-verdict-chronicle-chart-data';
import {ShadowVerdictChronicleChartSurfaceBuildController} from './shadow-verdict-chronicle-chart-surface-build.controller';
import type {ShadowVerdictChronicleSciChartLoaderService} from '../services/shadow-verdict-chronicle-scichart-loader.service';

export class ShadowVerdictChronicleSurfaceController {
    private chartModel: ChronicleChartModel | undefined;
    private sciChartSurface: ChronicleChartModel['sciChartSurface'] | undefined;

    private displayArrays: ChronicleArrays | null = null;
    private blendFromArrays: ChronicleArrays | null = null;
    private blendToArrays: ChronicleArrays | null = null;
    private blendStartPerformanceMs: number | null = null;

    private playbackRequestAnimationFrameId: number | null = null;
    private tapeAnchorWallClockMs = 0;
    private tapeAnchorPerformanceMs: number | null = null;
    private pendingTapeAnchorWallClockMs: number | undefined;

    private readonly surfaceBuildController = new ShadowVerdictChronicleChartSurfaceBuildController();

    constructor(private readonly sciChartLoader: ShadowVerdictChronicleSciChartLoaderService) {}

    hasChartModel(): boolean {
        return this.chartModel !== undefined;
    }

    async synchronizeChartSurface(
        host: HTMLDivElement,
        meta: ChronicleBucketMeta,
        options: { allowInitialBuild: boolean; snapBucketData: boolean; smaWindowBuckets: number },
        notifyChartReady: () => void,
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
        this.chartModel = undefined;
        if (this.sciChartSurface) {
            try {
                this.sciChartSurface.delete();
            } catch {
            }
            this.sciChartSurface = undefined;
        }
    }

    private pushXy(
        dataSeries: InstanceType<SciChartModule['XyDataSeries']>,
        xValues: number[],
        yValues: number[],
    ): void {
        dataSeries.clear();
        if (xValues.length > 0) {
            dataSeries.appendRange(xValues, yValues);
        }
    }

    private pushXyz(dataSeries: XyzDataSeries, points: Array<{ x: number; y: number; z: number }>): void {
        dataSeries.clear();
        for (const point of points) {
            dataSeries.append(point.x, point.y, point.z);
        }
    }

    private stopPlaybackLoop(): void {
        if (this.playbackRequestAnimationFrameId != null) {
            cancelAnimationFrame(this.playbackRequestAnimationFrameId);
            this.playbackRequestAnimationFrameId = null;
        }
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
            this.tapeAnchorWallClockMs =
                this.pendingTapeAnchorWallClockMs ?? Date.now() - CHRONICLE_STREAM_LAG_MS_FALLBACK;
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
                const rawAlpha =
                    (performance.now() - this.blendStartPerformanceMs) / CHRONICLE_SNAPSHOT_BLEND_MS;
                if (rawAlpha >= 1) {
                    this.displayArrays = cloneChronicleArrays(this.blendToArrays);
                    this.blendFromArrays = null;
                    this.blendToArrays = null;
                    this.blendStartPerformanceMs = null;
                } else {
                    this.displayArrays = blendChronicleArrays(
                        this.blendFromArrays,
                        this.blendToArrays,
                        rawAlpha,
                    );
                }
                if (this.displayArrays && chronicleShouldShowTargetVerdictCloud(rawAlpha)) {
                    this.pushVerdictCloudToChart(model, this.displayArrays);
                }
            }

            const {NumberRange, EAutoRange} = model.sci;
            const performanceBase = this.tapeAnchorPerformanceMs ?? performance.now();
            const rightEdgeMs = this.tapeAnchorWallClockMs + (performance.now() - performanceBase);
            if (this.displayArrays) {
                const tapeArrays = extendChronicleArraysToTapeRight(this.displayArrays, rightEdgeMs);
                this.pushTapeBoundSeriesToChart(model, tapeArrays);
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

    private pushVerdictCloudToChart(model: ChronicleChartModel, arrays: ChronicleArrays): void {
        this.pushXyz(model.profitableVerdictXyzDataSeries, arrays.verdictCloudProfitablePoints);
        this.pushXyz(model.lossVerdictXyzDataSeries, arrays.verdictCloudLossPoints);
    }

    private pushTapeBoundSeriesToChart(model: ChronicleChartModel, arrays: ChronicleArrays): void {
        this.pushXy(
            model.volumeMountainDataSeries,
            arrays.volumeBucketTimestampsMilliseconds,
            arrays.volumeBucketVerdictCounts,
        );
        this.pushXy(
            model.volumeColumnDataSeries,
            arrays.volumeBucketTimestampsMilliseconds,
            arrays.volumeBucketVerdictCounts,
        );

        const lineSeriesValues = [
            arrays.averagePnlPercentageSeries,
            arrays.averageWinRatePercentageSeries,
            arrays.expectedValuePerTradeUsdSeries,
            arrays.profitFactorSeries,
            arrays.capitalVelocityPerHourSeries,
        ];
        const smaSeriesValues = [
            arrays.movingAveragePnlSeries,
            arrays.movingAverageWinRateSeries,
            arrays.movingAverageExpectedValueSeries,
            arrays.movingAverageProfitFactorSeries,
            arrays.movingAverageVelocitySeries,
        ];
        for (let index = 0; index < model.metricLineRenderableSeries.length; index++) {
            const line = model.metricLineRenderableSeries[index];
            const lineDataSeries = line.dataSeries as InstanceType<SciChartModule['XyDataSeries']>;
            this.pushXy(lineDataSeries, arrays.metricTimestampsMilliseconds, lineSeriesValues[index] ?? []);
        }
        for (let index = 0; index < model.movingAverageLineRenderableSeries.length; index++) {
            const line = model.movingAverageLineRenderableSeries[index];
            const lineDataSeries = line.dataSeries as InstanceType<SciChartModule['XyDataSeries']>;
            this.pushXy(lineDataSeries, arrays.metricTimestampsMilliseconds, smaSeriesValues[index] ?? []);
        }
    }

    private pushArraysToChart(model: ChronicleChartModel, arrays: ChronicleArrays): void {
        this.pushTapeBoundSeriesToChart(model, arrays);
        this.pushVerdictCloudToChart(model, arrays);
    }

    private applyUniformColumnWidthForTimeBuckets(
        columnSeries: InstanceType<SciChartModule['FastColumnRenderableSeries']>,
        granularitySeconds: number,
        sci: SciChartModule,
    ): void {
        const bucketMilliseconds = Math.max(1000, granularitySeconds * 1000);
        columnSeries.dataPointWidthMode = sci.EDataPointWidthMode.Range;
        columnSeries.dataPointWidth = bucketMilliseconds * 0.88;
    }

    private updateChartData(meta: ChronicleBucketMeta, snapBucketData = false, smaWindowBuckets = 0): void {
        const model = this.chartModel;
        if (!model) {
            return;
        }
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
        this.applyUniformColumnWidthForTimeBuckets(
            model.volumeColumnRenderableSeries,
            meta.bucket.granularity_seconds,
            model.sci,
        );

        if (snapBucketData) {
            this.blendFromArrays = null;
            this.blendToArrays = null;
            this.blendStartPerformanceMs = null;
            this.displayArrays = cloneChronicleArrays(nextArrays);
            this.pushArraysToChart(model, this.displayArrays);
            model.sciChartSurface.invalidateElement();
            this.queueTapeAnchorFromMeta(meta);
            this.startPlaybackLoop(true);
            return;
        }

        if (!this.displayArrays) {
            this.displayArrays = cloneChronicleArrays(nextArrays);
            this.pushArraysToChart(model, this.displayArrays);
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

    private async buildFullChartSurface(host: HTMLDivElement, meta: ChronicleBucketMeta, smaWindowBuckets: number): Promise<void> {
        this.teardownChartSurface();

        this.chartModel = await this.surfaceBuildController.buildFullChartSurface(
            host,
            meta,
            this.sciChartLoader,
            smaWindowBuckets,
        );
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
}
