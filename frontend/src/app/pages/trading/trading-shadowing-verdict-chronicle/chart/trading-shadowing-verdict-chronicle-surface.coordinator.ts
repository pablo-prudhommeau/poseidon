import type {
    ChronicleArrays,
    ChronicleBucketMeta,
    ChronicleChartModel,
    ChronicleGoldenZoneThresholds,
    ChronicleSurfaceSyncOptions
} from '../data/trading-shadowing-verdict-chronicle.models';
import {
    buildChronicleArraysFromBucket,
    chronicleMinimumDisplayXMilliseconds,
    computeChronicleViewportWidthMilliseconds,
    parseIsoTimestampToEpochMilliseconds,
    type ChronicleBucketLabel
} from '../data/trading-shadowing-verdict-chronicle-arrays.utils';
import type { TradingShadowingVerdictChronicleSciChartLoaderService } from '../services/trading-shadowing-verdict-chronicle-scichart-loader.service';
import type { DefiIconsService } from '../../../../core/defi-icons.service';
import { synchronizeCortexModelRolloutAnnotations } from './trading-shadowing-verdict-chronicle-cortex-rollout.utils';
import { applyChronicleGoldenZoneVisualState, resolveChronicleGoldenZoneThresholds } from './trading-shadowing-verdict-chronicle-golden-zone.utils';
import type { ChronicleLegendSeriesItem } from './trading-shadowing-verdict-chronicle-legend.adapter';
import { listChronicleLegendSeries, setChronicleSeriesVisibility } from './trading-shadowing-verdict-chronicle-legend.adapter';
import { deleteChronicleOverview } from './trading-shadowing-verdict-chronicle-overview.utils';
import { harmonizeChronicleRightAxes } from './trading-shadowing-verdict-chronicle-right-axis.utils';
import { synchronizeChronicleSellPathTokenIconAnnotations } from './trading-shadowing-verdict-chronicle-sell-path-token-icon.utils';
import { synchronizeChronicleSeriesFromArrays } from './trading-shadowing-verdict-chronicle-series-sync.utils';
import { TradingShadowingVerdictChronicleSurfaceBuilder } from './trading-shadowing-verdict-chronicle-surface.builder';

export class TradingShadowingVerdictChronicleSurfaceCoordinator {
    private static readonly RIGHT_AXIS_MAJOR_TICK_COUNT: number = 8;
    private static readonly TIME_VISIBLE_RANGE_LEADING_PAD_MILLISECONDS: number = 45_000;

    private chartModel: ChronicleChartModel | undefined;
    private displayArrays: ChronicleArrays | null = null;
    private goldenZoneThresholds: ChronicleGoldenZoneThresholds = {
        sparseExpectedValueThreshold: undefined,
        chronicleProfitFactorThreshold: undefined
    };
    private sciChartSurface: ChronicleChartModel['sciChartSurface'] | undefined;
    private readonly surfaceBuilder: TradingShadowingVerdictChronicleSurfaceBuilder = new TradingShadowingVerdictChronicleSurfaceBuilder();

    constructor(
        private readonly sciChartLoader: TradingShadowingVerdictChronicleSciChartLoaderService,
        private readonly defiIconsService: DefiIconsService
    ) {}

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
        this.harmonizeRightAxes();
        model.sciChartSurface.invalidateElement();
    }

    async synchronizeChartSurface(
        host: HTMLDivElement,
        overviewHost: HTMLDivElement,
        meta: ChronicleBucketMeta,
        options: ChronicleSurfaceSyncOptions,
        notifyChartReady: () => void
    ): Promise<void> {
        try {
            if (!this.chartModel) {
                if (!options.allowInitialBuild) {
                    return;
                }
                await this.buildFullChartSurface(host, overviewHost, meta, options.smaWindowBuckets);
                return;
            }
            this.updateChartData(meta, options.snapBucketData, options.smaWindowBuckets);
        } catch {
        } finally {
            if (this.chartModel) {
                notifyChartReady();
            }
        }
    }

    teardownChartSurface(): void {
        if (this.chartModel) {
            try {
                synchronizeCortexModelRolloutAnnotations(this.chartModel, undefined, '', '');
            } catch {}
            try {
                synchronizeChronicleSellPathTokenIconAnnotations(this.chartModel, this.defiIconsService, [], []);
            } catch {}
            try {
                deleteChronicleOverview(this.chartModel);
            } catch {}
        }
        this.displayArrays = null;
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
        applyChronicleGoldenZoneVisualState(model, this.goldenZoneThresholds);
    }

    private applySnapshotToSurface(meta: ChronicleBucketMeta, snapTimeVisibleRange: boolean): void {
        const model = this.chartModel;
        if (!model || !this.displayArrays) {
            return;
        }
        synchronizeChronicleSeriesFromArrays(model, this.displayArrays, this.goldenZoneThresholds);
        try {
            this.synchronizeGoldenZones(meta);
            this.synchronizeCortexModelRollouts(meta);
            synchronizeChronicleSellPathTokenIconAnnotations(
                model,
                this.defiIconsService,
                this.displayArrays.sellPathProfitablePaths,
                this.displayArrays.sellPathLossPaths
            );
        } catch {}
        this.harmonizeRightAxes();
        if (snapTimeVisibleRange) {
            this.applyTimeVisibleRange(meta);
        }
        try {
            model.sciChartSurface.invalidateElement();
            model.sciChartOverview.overviewSciChartSurface.invalidateElement();
        } catch {}
    }

    private applyTimeVisibleRange(meta: ChronicleBucketMeta): void {
        const model = this.chartModel;
        if (!model || !this.displayArrays) {
            return;
        }
        const { EAutoRange, NumberRange } = model.sci;
        const rightEdgeMilliseconds = parseIsoTimestampToEpochMilliseconds(meta.response.as_of_iso) ?? Date.now();
        const earliestDisplayXMilliseconds = chronicleMinimumDisplayXMilliseconds(this.displayArrays);
        const naturalLeftEdgeMilliseconds = rightEdgeMilliseconds - model.viewportWidthMilliseconds;
        const leftEdgeClampMilliseconds =
            earliestDisplayXMilliseconds - TradingShadowingVerdictChronicleSurfaceCoordinator.TIME_VISIBLE_RANGE_LEADING_PAD_MILLISECONDS;
        const leftEdgeMilliseconds = Math.max(naturalLeftEdgeMilliseconds, leftEdgeClampMilliseconds);
        model.xAxis.autoRange = EAutoRange.Never;
        model.xAxis.visibleRange = new NumberRange(leftEdgeMilliseconds, rightEdgeMilliseconds);
    }

    private async buildFullChartSurface(
        host: HTMLDivElement,
        overviewHost: HTMLDivElement,
        meta: ChronicleBucketMeta,
        smaWindowBuckets: number
    ): Promise<void> {
        this.teardownChartSurface();

        this.chartModel = await this.surfaceBuilder.buildFullChartSurface(host, overviewHost, meta, this.sciChartLoader, smaWindowBuckets);
        this.sciChartSurface = this.chartModel.sciChartSurface;
        this.displayArrays = buildChronicleArraysFromBucket(meta, smaWindowBuckets);
        this.applySnapshotToSurface(meta, true);
    }

    private harmonizeRightAxes(): void {
        const model = this.chartModel;
        if (!model || !this.displayArrays) {
            return;
        }
        harmonizeChronicleRightAxes(
            model,
            this.displayArrays,
            TradingShadowingVerdictChronicleSurfaceCoordinator.RIGHT_AXIS_MAJOR_TICK_COUNT,
            this.goldenZoneThresholds
        );
    }

    private synchronizeCortexModelRollouts(meta: ChronicleBucketMeta): void {
        const model = this.chartModel;
        if (!model) {
            return;
        }
        synchronizeCortexModelRolloutAnnotations(model, meta.response.cortex_model_rollouts, meta.bucket.from_iso, meta.bucket.to_iso);
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
        const nextArrays = buildChronicleArraysFromBucket(meta, smaWindowBuckets);
        const computedViewportWidthMilliseconds = computeChronicleViewportWidthMilliseconds(
            nextArrays,
            meta.bucket.bucket_label as ChronicleBucketLabel,
            meta.bucket
        );
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
        this.displayArrays = nextArrays;
        this.applySnapshotToSurface(meta, snapBucketData);
    }
}
