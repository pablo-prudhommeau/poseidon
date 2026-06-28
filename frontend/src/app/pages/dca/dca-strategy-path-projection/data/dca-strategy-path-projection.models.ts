import type { SciChartSurface, TSciChart } from 'scichart';
import { DCA_STRATEGY_PATH_SERIES } from './dca-strategy-path-projection-series-names';

export type DcaStrategyPathSciChartModule = typeof import('scichart');

export interface DcaStrategyPathChartPoint {
    timestampMilliseconds: number;
    value: number;
}

export interface DcaStrategyPathBandSegment {
    xValues: number[];
    yValues: number[];
    y1Values: number[];
}

export interface DcaStrategyPathBandSegmentBundle {
    dataSeries: InstanceType<DcaStrategyPathSciChartModule['XyyDataSeries']>;
    series: InstanceType<DcaStrategyPathSciChartModule['SplineBandRenderableSeries']>;
}

export interface DcaStrategyPathBacktestingSeriesBundle {
    backtestingMarketPrice: DcaStrategyPathChartPoint[];
    backtestingBaselineAverageUnitPrice: DcaStrategyPathChartPoint[];
    backtestingSmartAverageUnitPrice: DcaStrategyPathChartPoint[];
}

export interface DcaStrategyPathProjectedSeriesBundle {
    projectedMarketPrice: DcaStrategyPathChartPoint[];
    projectedBaselineAverageUnitPrice: DcaStrategyPathChartPoint[];
    projectedSmartAverageUnitPrice: DcaStrategyPathChartPoint[];
}

export interface DcaStrategyPathEffectiveSeriesBundle {
    effectiveMarketPrice: DcaStrategyPathChartPoint[];
    effectiveSmartAverageUnitPrice: DcaStrategyPathChartPoint[];
    effectiveBaselineAverageUnitPrice: DcaStrategyPathChartPoint[];
}

export interface DcaStrategyPathChartSeriesBundle
    extends DcaStrategyPathProjectedSeriesBundle,
        DcaStrategyPathBacktestingSeriesBundle,
        DcaStrategyPathEffectiveSeriesBundle {
    marketPriceExecutionBandSegments: DcaStrategyPathBandSegment[];
    smartVsProjectedEffectiveBandSegments: DcaStrategyPathBandSegment[];
    lastExecutedTimestampMilliseconds: number;
}

export interface DcaStrategyPathRenderableSeriesCollectionLike {
    asArray?: () => unknown[];
    items?: unknown[];
}

export interface DcaStrategyPathLegendRenderableSeriesLike {
    seriesName?: string;
    stroke?: string;
    fill?: string;
    strokeDashArray?: number[];
    isVisible?: boolean;
}

export interface DcaStrategyPathVisibilityToggleSeriesLike {
    seriesName?: string;
    isVisible?: boolean;
}

export interface DcaStrategyPathTooltipSeriesInfoLike {
    seriesName?: string;
    formattedXValue?: string;
    formattedYValue?: string;
    stroke?: string;
    isHit?: boolean;
    renderableSeries?: { strokeDashArray?: number[] };
}

export interface DcaStrategyPathAdjustTooltipPositionHost {
    adjustTooltipPosition?: (width: number, height: number, svgAnnotation: unknown) => void;
}

export interface DcaStrategyPathChartModel {
    sciChartSurface: SciChartSurface;
    wasmContext: TSciChart;
    strategyTimeAxis: InstanceType<DcaStrategyPathSciChartModule['DateTimeNumericAxis']>;
    backtestReferenceTimeAxis: InstanceType<DcaStrategyPathSciChartModule['DateTimeNumericAxis']>;
    projectedMarketPriceLineSeries: InstanceType<DcaStrategyPathSciChartModule['SplineLineRenderableSeries']>;
    projectedMarketPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    projectedBaselineAverageUnitPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    projectedSmartAverageUnitPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    backtestingMarketPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    backtestingBaselineAverageUnitPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    backtestingSmartAverageUnitPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    effectiveMarketPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    effectiveSmartAverageUnitPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    effectiveBaselineAverageUnitPriceDataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    marketPriceExecutionBandSegmentBundles: DcaStrategyPathBandSegmentBundle[];
    smartVsProjectedEffectiveBandSegmentBundles: DcaStrategyPathBandSegmentBundle[];
    marketPriceExecutionBandUserVisible: boolean;
    smartVsProjectedEffectiveBandUserVisible: boolean;
}

export const DCA_STRATEGY_PATH_MARKET_BAND_SERIES_NAME = DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand;
export const DCA_STRATEGY_PATH_PRU_BAND_SERIES_NAME = DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand;
