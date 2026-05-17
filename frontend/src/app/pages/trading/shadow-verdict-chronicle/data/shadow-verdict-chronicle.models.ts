import type { SciChartSurface, TSciChart } from 'scichart';
import type { ShadowVerdictChronicleBucketPayload, ShadowVerdictChronicleResponse } from '../../../../core/models';

export type SciChartModule = typeof import('scichart');

export interface ChronicleCartesianPoint {
    x: number;
    y: number;
    cortexProbability?: number | null;
    orderNotionalUsd?: number | null;
}

export interface ChronicleVerdictBubblePointMetadata {
    cortexProbability?: number | null;
    orderNotionalUsd?: number | null;
    isSelected: boolean;
}

export interface ChronicleNumericBounds {
    min: number;
    max: number;
}

export interface ChronicleAxisTickBounds extends ChronicleNumericBounds {
    majorDelta: number;
}

export interface CortexCalibrationBandSegmentBundle {
    dataSeries: InstanceType<SciChartModule['XyyDataSeries']>;
    series: InstanceType<SciChartModule['SplineBandRenderableSeries']>;
}

export interface GateSubmergedBandSegmentBundle {
    dataSeries: InstanceType<SciChartModule['XyyDataSeries']>;
    series: InstanceType<SciChartModule['FastBandRenderableSeries']>;
}

export interface CortexModelRolloutAnnotationBundle {
    verticalLine: InstanceType<SciChartModule['VerticalLineAnnotation']>;
    textLabel: InstanceType<SciChartModule['CustomAnnotation']>;
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
    pointMetadata?: any;
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
    isVisible?: boolean;
}

export interface ChronicleChartModel {
    sciChartSurface: SciChartSurface;
    wasmContext: TSciChart;
    sci: SciChartModule;
    xAxis: InstanceType<SciChartModule['DateTimeNumericAxis']>;
    viewportWidthMilliseconds: number;
    volumeColumnDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    volumeColumnRenderableSeries: InstanceType<SciChartModule['FastColumnRenderableSeries']>;
    yVolumeAxis: InstanceType<SciChartModule['NumericAxis']>;
    yExpectedValueAxis: InstanceType<SciChartModule['NumericAxis']>;
    yProfitFactorAxis: InstanceType<SciChartModule['NumericAxis']>;
    yTradesPerHourAxis: InstanceType<SciChartModule['NumericAxis']>;
    yRegimeEvAxis: InstanceType<SciChartModule['NumericAxis']>;
    yRegimePfAxis: InstanceType<SciChartModule['NumericAxis']>;
    goldenZoneExpectedValueBandDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneProfitFactorBandDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneExpectedValueBandSeries: InstanceType<SciChartModule['SplineMountainRenderableSeries']>;
    goldenZoneProfitFactorBandSeries: InstanceType<SciChartModule['SplineMountainRenderableSeries']>;
    regimeEvGateSubmergedBandSegmentBundles: GateSubmergedBandSegmentBundle[];
    regimePfGateSubmergedBandSegmentBundles: GateSubmergedBandSegmentBundle[];
    metricLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    movingAverageLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    profitableVerdictXyDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    lossVerdictXyDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    cortexCalibrationBandSegmentBundles: CortexCalibrationBandSegmentBundle[];
    cortexCalibrationBandUserVisible: boolean;
    cortexModelRolloutUserVisible: boolean;
    evGateThresholdUserVisible: boolean;
    pfGateThresholdUserVisible: boolean;
    goldenZoneExpectedValueAnnotation?: InstanceType<SciChartModule['HorizontalLineAnnotation']>;
    goldenZoneProfitFactorAnnotation?: InstanceType<SciChartModule['HorizontalLineAnnotation']>;
    cortexModelRolloutAnnotationBundles: CortexModelRolloutAnnotationBundle[];
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
    closedVerdictsPerHourSeries: number[];
    averageCortexPredictionWinRatePercentageSeries: number[];
    movingAveragePnlSeries: number[];
    movingAverageWinRateSeries: number[];
    movingAverageExpectedValueSeries: number[];
    movingAverageProfitFactorSeries: number[];
    movingAverageTradesPerHourSeries: number[];
    movingAverageCortexPredictionWinRatePercentageSeries: number[];
    regimeProfitFactorSmaSeries: number[];
    regimeSparseExpectedValueUsdSmaSeries: number[];
    profitFactorGateOpenSeries: boolean[];
    sparseExpectedValueGateOpenSeries: boolean[];
    hardGateOpenSeries: boolean[];
    volumeBucketTimestampsMilliseconds: number[];
    volumeBucketVerdictCounts: number[];
    verdictCloudProfitablePoints: ChronicleCartesianPoint[];
    verdictCloudLossPoints: ChronicleCartesianPoint[];
}
