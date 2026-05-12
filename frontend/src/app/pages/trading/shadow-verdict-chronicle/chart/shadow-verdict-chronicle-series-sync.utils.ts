import type { XyzDataSeries } from 'scichart';
import type {
    ChronicleArrays,
    ChronicleCartesianPoint,
    ChronicleChartModel,
    ChronicleGoldenZoneThresholds,
    SciChartModule
} from '../data/shadow-verdict-chronicle.models';
import { buildChronicleGoldenZoneExpectedValueBandValues, buildChronicleGoldenZoneProfitFactorBandValues } from './shadow-verdict-chronicle-golden-zone.utils';

function synchronizeXySeries(dataSeries: InstanceType<SciChartModule['XyDataSeries']>, xValues: number[], yValues: number[]): void {
    dataSeries.clear();
    if (xValues.length > 0) {
        dataSeries.appendRange(xValues, yValues);
    }
}

function synchronizeXyzSeries(dataSeries: XyzDataSeries, points: ChronicleCartesianPoint[]): void {
    dataSeries.clear();
    for (const point of points) {
        dataSeries.append(point.x, point.y, point.z);
    }
}

function synchronizeChronicleVerdictCloud(model: ChronicleChartModel, arrays: ChronicleArrays): void {
    synchronizeXyzSeries(model.profitableVerdictXyzDataSeries, arrays.verdictCloudProfitablePoints);
    synchronizeXyzSeries(model.lossVerdictXyzDataSeries, arrays.verdictCloudLossPoints);
}

function synchronizeChronicleTapeBoundMetrics(model: ChronicleChartModel, arrays: ChronicleArrays, thresholds: ChronicleGoldenZoneThresholds): void {
    synchronizeXySeries(model.volumeMountainDataSeries, arrays.volumeBucketTimestampsMilliseconds, arrays.volumeBucketVerdictCounts);
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

    const metricLineSeriesValues: number[][] = [
        arrays.averagePnlPercentageSeries,
        arrays.averageWinRatePercentageSeries,
        arrays.expectedValuePerTradeUsdSeries,
        arrays.profitFactorSeries,
        arrays.capitalVelocityPerHourSeries
    ];
    const movingAverageSeriesValues: number[][] = [
        arrays.movingAveragePnlSeries,
        arrays.movingAverageWinRateSeries,
        arrays.movingAverageExpectedValueSeries,
        arrays.movingAverageProfitFactorSeries,
        arrays.movingAverageVelocitySeries
    ];
    for (let index = 0; index < model.metricLineRenderableSeries.length; index++) {
        const lineSeries = model.metricLineRenderableSeries[index];
        const lineDataSeries = lineSeries.dataSeries as InstanceType<SciChartModule['XyDataSeries']>;
        synchronizeXySeries(lineDataSeries, arrays.metricTimestampsMilliseconds, metricLineSeriesValues[index] ?? []);
    }
    for (let index = 0; index < model.movingAverageLineRenderableSeries.length; index++) {
        const lineSeries = model.movingAverageLineRenderableSeries[index];
        const lineDataSeries = lineSeries.dataSeries as InstanceType<SciChartModule['XyDataSeries']>;
        synchronizeXySeries(lineDataSeries, arrays.metricTimestampsMilliseconds, movingAverageSeriesValues[index] ?? []);
    }
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
