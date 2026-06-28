import type { TSciChart } from 'scichart';
import {
    DCA_STRATEGY_PATH_MARKET_BAND_SERIES_NAME,
    DCA_STRATEGY_PATH_PRU_BAND_SERIES_NAME,
    DcaStrategyPathBandSegment,
    DcaStrategyPathBandSegmentBundle,
    DcaStrategyPathChartModel,
    DcaStrategyPathSciChartModule
} from '../data/dca-strategy-path-projection.models';
import { DCA_STRATEGY_PATH_METRIC_COLORS, DCA_STRATEGY_PATH_TIME_AXIS_IDS } from '../data/dca-strategy-path-projection-metrics.catalog';

function createBandSegmentBundle(
    sciChartModule: DcaStrategyPathSciChartModule,
    wasmContext: TSciChart,
    segment: DcaStrategyPathBandSegment,
    seriesName: string,
    includeInLegend: boolean,
    isVisible: boolean,
    bandFillWhenYLessThanY1: string,
    bandFillWhenYGreaterThanY1: string
): DcaStrategyPathBandSegmentBundle {
    const { XyyDataSeries, SplineBandRenderableSeries } = sciChartModule;
    const dataSeries = new XyyDataSeries(wasmContext, {
        xValues: segment.xValues,
        yValues: segment.yValues,
        y1Values: segment.y1Values,
        dataSeriesName: seriesName,
        isSorted: true,
        containsNaN: false
    });
    const series = new SplineBandRenderableSeries(wasmContext, {
        dataSeries,
        yAxisId: 'yPrice',
        xAxisId: DCA_STRATEGY_PATH_TIME_AXIS_IDS.strategy,
        seriesName: includeInLegend ? seriesName : '',
        stroke: DCA_STRATEGY_PATH_METRIC_COLORS.transparent,
        strokeY1: DCA_STRATEGY_PATH_METRIC_COLORS.transparent,
        strokeThickness: 0,
        fill: bandFillWhenYLessThanY1,
        fillY1: bandFillWhenYGreaterThanY1,
        opacity: 0.72
    });
    series.isVisible = isVisible;
    return { dataSeries, series };
}

function synchronizeBandSegmentBundle(bundle: DcaStrategyPathBandSegmentBundle, segment: DcaStrategyPathBandSegment): void {
    bundle.dataSeries.clear();
    if (segment.xValues.length > 0) {
        bundle.dataSeries.appendRange(segment.xValues, segment.yValues, segment.y1Values);
    }
}

function buildBandSegmentBundles(
    sciChartModule: DcaStrategyPathSciChartModule,
    wasmContext: TSciChart,
    segments: DcaStrategyPathBandSegment[],
    seriesName: string,
    isVisible: boolean,
    bandFillWhenYLessThanY1: string,
    bandFillWhenYGreaterThanY1: string
): DcaStrategyPathBandSegmentBundle[] {
    return segments.map((segment: DcaStrategyPathBandSegment, index: number) =>
        createBandSegmentBundle(sciChartModule, wasmContext, segment, seriesName, index === 0, isVisible, bandFillWhenYLessThanY1, bandFillWhenYGreaterThanY1)
    );
}

function synchronizeBandSegmentBundles(
    chartModel: DcaStrategyPathChartModel,
    sciChartModule: DcaStrategyPathSciChartModule,
    wasmContext: TSciChart,
    existingBundles: DcaStrategyPathBandSegmentBundle[],
    segments: DcaStrategyPathBandSegment[],
    seriesName: string,
    isVisible: boolean,
    bandFillWhenYLessThanY1: string,
    bandFillWhenYGreaterThanY1: string
): DcaStrategyPathBandSegmentBundle[] {
    const synchronizedBundles: DcaStrategyPathBandSegmentBundle[] = [...existingBundles];

    for (let index = 0; index < segments.length; index++) {
        const segment: DcaStrategyPathBandSegment = segments[index];
        if (index < synchronizedBundles.length) {
            synchronizeBandSegmentBundle(synchronizedBundles[index], segment);
            synchronizedBundles[index].series.isVisible = isVisible;
            continue;
        }
        const bundle = createBandSegmentBundle(
            sciChartModule,
            wasmContext,
            segment,
            seriesName,
            index === 0,
            isVisible,
            bandFillWhenYLessThanY1,
            bandFillWhenYGreaterThanY1
        );
        chartModel.sciChartSurface.renderableSeries.add(bundle.series);
        synchronizedBundles.push(bundle);
    }

    for (let index = segments.length; index < synchronizedBundles.length; index++) {
        synchronizedBundles[index].dataSeries.clear();
        synchronizedBundles[index].series.isVisible = false;
    }

    return synchronizedBundles;
}

export function buildMarketPriceExecutionBandSegmentBundles(
    sciChartModule: DcaStrategyPathSciChartModule,
    wasmContext: TSciChart,
    segments: DcaStrategyPathBandSegment[],
    isVisible: boolean
): DcaStrategyPathBandSegmentBundle[] {
    return buildBandSegmentBundles(
        sciChartModule,
        wasmContext,
        segments,
        DCA_STRATEGY_PATH_MARKET_BAND_SERIES_NAME,
        isVisible,
        DCA_STRATEGY_PATH_METRIC_COLORS.marketBandFillWhenEffectiveAbove,
        DCA_STRATEGY_PATH_METRIC_COLORS.marketBandFillWhenProjectedAbove
    );
}

export function buildSmartVsProjectedEffectiveBandSegmentBundles(
    sciChartModule: DcaStrategyPathSciChartModule,
    wasmContext: TSciChart,
    segments: DcaStrategyPathBandSegment[],
    isVisible: boolean
): DcaStrategyPathBandSegmentBundle[] {
    return buildBandSegmentBundles(
        sciChartModule,
        wasmContext,
        segments,
        DCA_STRATEGY_PATH_PRU_BAND_SERIES_NAME,
        isVisible,
        DCA_STRATEGY_PATH_METRIC_COLORS.pruBandFillWhenProjectedAbove,
        DCA_STRATEGY_PATH_METRIC_COLORS.pruBandFillWhenEffectiveAbove
    );
}

export function synchronizeMarketPriceExecutionBandSegmentBundles(
    chartModel: DcaStrategyPathChartModel,
    sciChartModule: DcaStrategyPathSciChartModule,
    wasmContext: TSciChart,
    segments: DcaStrategyPathBandSegment[]
): DcaStrategyPathBandSegmentBundle[] {
    return synchronizeBandSegmentBundles(
        chartModel,
        sciChartModule,
        wasmContext,
        chartModel.marketPriceExecutionBandSegmentBundles,
        segments,
        DCA_STRATEGY_PATH_MARKET_BAND_SERIES_NAME,
        chartModel.marketPriceExecutionBandUserVisible,
        DCA_STRATEGY_PATH_METRIC_COLORS.marketBandFillWhenEffectiveAbove,
        DCA_STRATEGY_PATH_METRIC_COLORS.marketBandFillWhenProjectedAbove
    );
}

export function synchronizeSmartVsProjectedEffectiveBandSegmentBundles(
    chartModel: DcaStrategyPathChartModel,
    sciChartModule: DcaStrategyPathSciChartModule,
    wasmContext: TSciChart,
    segments: DcaStrategyPathBandSegment[]
): DcaStrategyPathBandSegmentBundle[] {
    return synchronizeBandSegmentBundles(
        chartModel,
        sciChartModule,
        wasmContext,
        chartModel.smartVsProjectedEffectiveBandSegmentBundles,
        segments,
        DCA_STRATEGY_PATH_PRU_BAND_SERIES_NAME,
        chartModel.smartVsProjectedEffectiveBandUserVisible,
        DCA_STRATEGY_PATH_METRIC_COLORS.pruBandFillWhenProjectedAbove,
        DCA_STRATEGY_PATH_METRIC_COLORS.pruBandFillWhenEffectiveAbove
    );
}
