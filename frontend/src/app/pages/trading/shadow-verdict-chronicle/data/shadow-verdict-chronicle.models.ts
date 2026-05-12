import type { SciChartSurface, TSciChart, XyzDataSeries } from 'scichart';
import type { ShadowVerdictChronicleBucketPayload, ShadowVerdictChronicleResponse } from '../../../../core/models';

export type SciChartModule = typeof import('scichart');

export interface ChronicleCartesianPoint {
    x: number;
    y: number;
    z: number;
}

export interface ChronicleNumericBounds {
    min: number;
    max: number;
}

export interface ChronicleAxisTickBounds extends ChronicleNumericBounds {
    majorDelta: number;
}

export interface ChronicleThresholdPaletteController {
    setThreshold: (value: number | undefined) => void;
}

export interface ChronicleThresholdPaletteBinding extends ChronicleThresholdPaletteController {
    paletteProvider: unknown;
}

export interface ChronicleGoldenZoneThresholds {
    sparseExpectedValueThreshold: number | undefined;
    chronicleProfitFactorThreshold: number | undefined;
}

export interface ChronicleSurfaceSyncOptions {
    allowInitialBuild: boolean;
    snapBucketData: boolean;
    smaWindowBuckets: number;
}

export interface ChronicleAdjustTooltipPositionHost {
    adjustTooltipPosition?: (width: number, height: number, annotation: unknown) => void;
}

export interface ChronicleTooltipRenderableSeriesShape {
    strokeDashArray?: number[];
}

export interface ChronicleTooltipSeriesInfoLike {
    seriesName?: string;
    formattedXValue?: string;
    formattedYValue?: string;
    isHit?: boolean;
    stroke?: string;
    renderableSeries?: ChronicleTooltipRenderableSeriesShape;
    zValue?: number;
    xValue?: number;
}

export interface ChronicleRenderableSeriesCollectionLike {
    asArray?: () => unknown[];
    items?: unknown[];
}

export interface ChronicleLegendRenderableSeriesLike {
    seriesName?: string;
    isVisible?: boolean;
    stroke?: string;
    fill?: string;
    strokeDashArray?: number[];
}

export interface ChronicleVisibilityToggleSeriesLike {
    seriesName?: string;
    isVisible?: boolean;
}

export interface ChronicleAxisDescriptor<TAxis> {
    axis: TAxis;
    values: number[];
}

export interface ChronicleConfigurableAxisOptions {
    autoTicks?: boolean;
    majorDelta?: number;
    minorDelta?: number;
}

export interface ChronicleChartModel {
    sciChartSurface: SciChartSurface;
    wasmContext: TSciChart;
    sci: SciChartModule;
    xAxis: InstanceType<SciChartModule['DateTimeNumericAxis']>;
    viewportWidthMilliseconds: number;
    volumeMountainDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    volumeColumnDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    volumeColumnRenderableSeries: InstanceType<SciChartModule['FastColumnRenderableSeries']>;
    yVolumeAxis: InstanceType<SciChartModule['NumericAxis']>;
    yExpectedValueAxis: InstanceType<SciChartModule['NumericAxis']>;
    yProfitFactorAxis: InstanceType<SciChartModule['NumericAxis']>;
    yVelocityAxis: InstanceType<SciChartModule['NumericAxis']>;
    goldenZoneExpectedValueBandDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneProfitFactorBandDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneExpectedValueBandSeries: InstanceType<SciChartModule['SplineMountainRenderableSeries']>;
    goldenZoneProfitFactorBandSeries: InstanceType<SciChartModule['SplineMountainRenderableSeries']>;
    goldenZoneExpectedValueSmaPaletteController: ChronicleThresholdPaletteController;
    goldenZoneProfitFactorSmaPaletteController: ChronicleThresholdPaletteController;
    metricLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    movingAverageLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    profitableVerdictXyzDataSeries: XyzDataSeries;
    lossVerdictXyzDataSeries: XyzDataSeries;
    goldenZoneExpectedValueAnnotation?: InstanceType<SciChartModule['HorizontalLineAnnotation']>;
    goldenZoneProfitFactorAnnotation?: InstanceType<SciChartModule['HorizontalLineAnnotation']>;
}

export interface ChronicleBucketMeta {
    bucket: ShadowVerdictChronicleBucketPayload;
    response: ShadowVerdictChronicleResponse;
    sparseExpectedValueUsdThreshold?: number | string | null;
    chronicleProfitFactorThreshold?: number | string | null;
}

export interface ChronicleArrays {
    metricTimestampsMilliseconds: number[];
    averagePnlPercentageSeries: number[];
    averageWinRatePercentageSeries: number[];
    expectedValuePerTradeUsdSeries: number[];
    profitFactorSeries: number[];
    capitalVelocityPerHourSeries: number[];
    movingAveragePnlSeries: number[];
    movingAverageWinRateSeries: number[];
    movingAverageExpectedValueSeries: number[];
    movingAverageProfitFactorSeries: number[];
    movingAverageVelocitySeries: number[];
    volumeBucketTimestampsMilliseconds: number[];
    volumeBucketVerdictCounts: number[];
    verdictCloudProfitablePoints: ChronicleCartesianPoint[];
    verdictCloudLossPoints: ChronicleCartesianPoint[];
}
