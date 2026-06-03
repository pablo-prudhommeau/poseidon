import type {
    ChronicleArrays,
    ChronicleCartesianPoint,
    ChronicleChartModel,
    ChronicleGoldenZoneThresholds,
    ChronicleVerdictBubblePointMetadata,
    SciChartModule
} from '../data/trading-shadowing-verdict-chronicle.models';
import {
    buildChronicleGoldenZoneExpectedValueBandValues,
    buildChronicleGoldenZoneProfitFactorBandValues
} from './trading-shadowing-verdict-chronicle-golden-zone.utils';
import {
    buildCortexCalibrationBandSegments,
    synchronizeCortexCalibrationBandSegmentBundles
} from './trading-shadowing-verdict-chronicle-cortex-calibration-band.utils';
import {
    buildRegimeEvGateSubmergedBandSegmentsFromArrays,
    buildRegimePfGateSubmergedBandSegmentsFromArrays,
    synchronizeRegimeEvGateSubmergedBandSegmentBundles,
    synchronizeRegimePfGateSubmergedBandSegmentBundles
} from './trading-shadowing-verdict-chronicle-gate-submerged-band.utils';
import { buildSplineSafeXyValues } from './trading-shadowing-verdict-chronicle-spline-data.utils';

function synchronizeXySeries(dataSeries: InstanceType<SciChartModule['XyDataSeries']>, xValues: number[], yValues: number[]): void {
    dataSeries.clear();
    if (xValues.length > 0) {
        dataSeries.appendRange(xValues, yValues);
    }
}

function synchronizeSplineXySeries(dataSeries: InstanceType<SciChartModule['XyDataSeries']>, xValues: number[], yValues: number[]): void {
    const safeValues = buildSplineSafeXyValues(xValues, yValues);
    synchronizeXySeries(dataSeries, safeValues.xValues, safeValues.yValues);
}

function buildVerdictCloudPointMetadata(point: ChronicleCartesianPoint): ChronicleVerdictBubblePointMetadata {
    return {
        cortexProbability: point.cortexProbability,
        orderNotionalUsd: point.orderNotionalUsd,
        isSelected: false
    };
}

function synchronizeVerdictCloudXySeries(dataSeries: InstanceType<SciChartModule['XyDataSeries']>, points: ChronicleCartesianPoint[]): void {
    dataSeries.clear();
    for (const point of points) {
        dataSeries.append(point.x, point.y, buildVerdictCloudPointMetadata(point));
    }
}

function synchronizeChronicleVerdictCloud(model: ChronicleChartModel, arrays: ChronicleArrays): void {
    synchronizeVerdictCloudXySeries(model.profitableVerdictXyDataSeries, arrays.verdictCloudProfitablePoints);
    synchronizeVerdictCloudXySeries(model.lossVerdictXyDataSeries, arrays.verdictCloudLossPoints);
}

function synchronizeChronicleTapeBoundMetrics(model: ChronicleChartModel, arrays: ChronicleArrays, thresholds: ChronicleGoldenZoneThresholds): void {
    synchronizeXySeries(model.volumeColumnDataSeries, arrays.volumeBucketTimestampsMilliseconds, arrays.volumeBucketVerdictCounts);
    synchronizeXySeries(
        model.goldenZoneExpectedValueBandDataSeries,
        arrays.metricTimestampsMilliseconds,
        buildChronicleGoldenZoneExpectedValueBandValues(arrays, thresholds.sparseExpectedValueThreshold)
    );
    synchronizeXySeries(
        model.goldenZoneProfitFactorBandDataSeries,
        arrays.metricTimestampsMilliseconds,
        buildChronicleGoldenZoneProfitFactorBandValues(arrays, thresholds.chronicleProfitFactorThreshold)
    );
    synchronizeRegimeEvGateSubmergedBandSegmentBundles(
        model,
        model.sci,
        model.wasmContext,
        buildRegimeEvGateSubmergedBandSegmentsFromArrays(arrays.metricTimestampsMilliseconds, arrays, thresholds.sparseExpectedValueThreshold)
    );
    synchronizeRegimePfGateSubmergedBandSegmentBundles(
        model,
        model.sci,
        model.wasmContext,
        buildRegimePfGateSubmergedBandSegmentsFromArrays(arrays.metricTimestampsMilliseconds, arrays, thresholds.chronicleProfitFactorThreshold)
    );

    const metricLineSeriesValues: number[][] = [
        arrays.averagePnlPercentageSeries,
        arrays.averageWinRatePercentageSeries,
        arrays.averageCortexPredictionWinRatePercentageSeries,
        arrays.cortexSkillScorePercentageSeries,
        arrays.cortexCalibrationGapPercentagePointsSeries,
        arrays.cortexHighConvictionAccuracyPercentageSeries,
        arrays.cortexHighConvictionSharePercentageSeries,
        arrays.cortexGatePrecisionPercentageSeries,
        arrays.cortexGatePassRatePercentageSeries,
        arrays.expectedValuePerTradeUsdSeries,
        arrays.portfolioWalletValueUsdSeries,
        arrays.profitFactorSeries,
        arrays.closedVerdictsPerHourSeries
    ];
    const movingAverageSeriesValues: number[][] = [
        arrays.movingAveragePnlSeries,
        arrays.movingAverageWinRateSeries,
        arrays.movingAverageCortexPredictionWinRatePercentageSeries,
        arrays.movingAverageCortexSkillScorePercentageSeries,
        arrays.movingAverageCortexCalibrationGapPercentagePointsSeries,
        arrays.movingAverageCortexHighConvictionAccuracyPercentageSeries,
        arrays.movingAverageCortexHighConvictionSharePercentageSeries,
        arrays.movingAverageCortexGatePrecisionPercentageSeries,
        arrays.movingAverageCortexGatePassRatePercentageSeries,
        arrays.movingAverageExpectedValueSeries,
        arrays.movingAveragePortfolioWalletValueUsdSeries,
        arrays.movingAverageProfitFactorSeries,
        arrays.movingAverageTradesPerHourSeries
    ];
    for (let index = 0; index < model.metricLineRenderableSeries.length; index++) {
        const lineSeries = model.metricLineRenderableSeries[index];
        const lineDataSeries = lineSeries.dataSeries as InstanceType<SciChartModule['XyDataSeries']>;
        synchronizeSplineXySeries(lineDataSeries, arrays.metricTimestampsMilliseconds, metricLineSeriesValues[index] ?? []);
    }
    for (let index = 0; index < model.movingAverageLineRenderableSeries.length; index++) {
        const lineSeries = model.movingAverageLineRenderableSeries[index];
        const lineDataSeries = lineSeries.dataSeries as InstanceType<SciChartModule['XyDataSeries']>;
        synchronizeSplineXySeries(lineDataSeries, arrays.metricTimestampsMilliseconds, movingAverageSeriesValues[index] ?? []);
    }

    const cortexCalibrationBandSegments = buildCortexCalibrationBandSegments(
        arrays.metricTimestampsMilliseconds,
        arrays.averageWinRatePercentageSeries,
        arrays.averageCortexPredictionWinRatePercentageSeries
    );
    synchronizeCortexCalibrationBandSegmentBundles(model, model.sci, model.wasmContext, cortexCalibrationBandSegments);
}

export function synchronizeChronicleSeriesFromArrays(model: ChronicleChartModel, arrays: ChronicleArrays, thresholds: ChronicleGoldenZoneThresholds): void {
    synchronizeChronicleTapeBoundMetrics(model, arrays, thresholds);
    synchronizeChronicleVerdictCloud(model, arrays);
}

export function synchronizeChronicleTapeBoundSeries(model: ChronicleChartModel, arrays: ChronicleArrays, thresholds: ChronicleGoldenZoneThresholds): void {
    synchronizeChronicleTapeBoundMetrics(model, arrays, thresholds);
}

export function synchronizeChronicleVerdictCloudSeries(model: ChronicleChartModel, arrays: ChronicleArrays): void {
    synchronizeChronicleVerdictCloud(model, arrays);
}
