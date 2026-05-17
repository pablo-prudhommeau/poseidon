import type { TSciChart } from 'scichart';
import type { ChronicleChartModel, CortexCalibrationBandSegmentBundle, SciChartModule } from '../data/shadow-verdict-chronicle.models';
import { CHRONICLE_METRIC_COLORS } from '../data/shadow-verdict-chronicle-metrics.catalog';
import { CHRONICLE_SERIES } from '../data/shadow-verdict-chronicle-series-names';

export const CORTEX_CALIBRATION_BAND_SERIES_NAME = CHRONICLE_SERIES.cortexCalibrationBand;

const CORTEX_CALIBRATION_BAND_MIN_SEGMENT_POINTS = 2;

export interface CortexCalibrationBandSegment {
    xValues: number[];
    yValues: number[];
    y1Values: number[];
}

export function buildCortexCalibrationBandSegments(
    xValues: number[],
    averageWinRatePercentageSeries: number[],
    averageCortexPredictionWinRatePercentageSeries: number[]
): CortexCalibrationBandSegment[] {
    const segments: CortexCalibrationBandSegment[] = [];
    const length = Math.min(xValues.length, averageWinRatePercentageSeries.length, averageCortexPredictionWinRatePercentageSeries.length);
    let current: CortexCalibrationBandSegment | null = null;

    const flushCurrent = (): void => {
        if (current && current.xValues.length >= CORTEX_CALIBRATION_BAND_MIN_SEGMENT_POINTS) {
            segments.push(current);
        }
        current = null;
    };

    for (let index = 0; index < length; index++) {
        const averageWinRate = averageWinRatePercentageSeries[index];
        const averageCortexPrediction = averageCortexPredictionWinRatePercentageSeries[index];
        if (Number.isFinite(averageWinRate) && Number.isFinite(averageCortexPrediction)) {
            if (!current) {
                current = { xValues: [], yValues: [], y1Values: [] };
            }
            current.xValues.push(xValues[index] ?? 0);
            current.yValues.push(averageWinRate);
            current.y1Values.push(averageCortexPrediction);
            continue;
        }
        flushCurrent();
    }
    flushCurrent();
    return segments;
}

function createCortexCalibrationBandSegmentBundle(
    sci: SciChartModule,
    wasmContext: TSciChart,
    segment: CortexCalibrationBandSegment,
    includeInLegend: boolean,
    isVisible: boolean
): CortexCalibrationBandSegmentBundle {
    const { XyyDataSeries, SplineBandRenderableSeries } = sci;
    const dataSeries = new XyyDataSeries(wasmContext, {
        xValues: segment.xValues,
        yValues: segment.yValues,
        y1Values: segment.y1Values,
        dataSeriesName: CORTEX_CALIBRATION_BAND_SERIES_NAME,
        isSorted: true,
        containsNaN: false
    });
    const series = new SplineBandRenderableSeries(wasmContext, {
        dataSeries,
        yAxisId: 'yPct',
        xAxisId: 'xTime',
        seriesName: includeInLegend ? CORTEX_CALIBRATION_BAND_SERIES_NAME : '',
        stroke: CHRONICLE_METRIC_COLORS.transparent,
        strokeY1: CHRONICLE_METRIC_COLORS.transparent,
        strokeThickness: 0,
        fill: CHRONICLE_METRIC_COLORS.cortexCalibrationBandAbove,
        fillY1: CHRONICLE_METRIC_COLORS.cortexCalibrationBandBelow,
        opacity: 0.85
    });
    series.isVisible = isVisible;
    return { dataSeries, series };
}

function synchronizeCortexCalibrationBandSegmentBundle(bundle: CortexCalibrationBandSegmentBundle, segment: CortexCalibrationBandSegment): void {
    bundle.dataSeries.clear();
    if (segment.xValues.length > 0) {
        bundle.dataSeries.appendRange(segment.xValues, segment.yValues, segment.y1Values);
    }
}

export function buildCortexCalibrationBandSegmentBundles(
    sci: SciChartModule,
    wasmContext: TSciChart,
    segments: CortexCalibrationBandSegment[],
    isVisible = true
): CortexCalibrationBandSegmentBundle[] {
    return segments.map((segment, index) => createCortexCalibrationBandSegmentBundle(sci, wasmContext, segment, index === 0, isVisible));
}

export function synchronizeCortexCalibrationBandSegmentBundles(
    model: ChronicleChartModel,
    sci: SciChartModule,
    wasmContext: TSciChart,
    segments: CortexCalibrationBandSegment[]
): void {
    const existingBundles = model.cortexCalibrationBandSegmentBundles;
    const targetCount = segments.length;
    const bandIsVisible = model.cortexCalibrationBandUserVisible;

    for (let index = 0; index < targetCount; index++) {
        const segment = segments[index];
        if (index < existingBundles.length) {
            synchronizeCortexCalibrationBandSegmentBundle(existingBundles[index], segment);
            existingBundles[index].series.isVisible = bandIsVisible;
            continue;
        }
        const bundle = createCortexCalibrationBandSegmentBundle(sci, wasmContext, segment, index === 0, bandIsVisible);
        model.sciChartSurface.renderableSeries.add(bundle.series);
        existingBundles.push(bundle);
    }

    for (let index = targetCount; index < existingBundles.length; index++) {
        existingBundles[index].dataSeries.clear();
        existingBundles[index].series.isVisible = false;
    }
}
