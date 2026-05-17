import type { TSciChart } from 'scichart';
import type { ChronicleChartModel, GateSubmergedBandSegmentBundle, SciChartModule } from '../data/shadow-verdict-chronicle.models';
import { CHRONICLE_METRIC_COLORS } from '../data/shadow-verdict-chronicle-metrics.catalog';
import {
    buildChronicleGoldenZoneExpectedValueSubmergedBandValues,
    buildChronicleGoldenZoneProfitFactorSubmergedBandValues,
    raiseChronicleGateThresholdAnnotations,
    resolveRegimeGateExpectedValueSmaSeries,
    resolveRegimeGateProfitFactorSmaSeries
} from './shadow-verdict-chronicle-golden-zone.utils';

const GATE_SUBMERGED_BAND_MIN_SEGMENT_POINTS = 2;
const GATE_SUBMERGED_BAND_UPPER_INSET_RATIO = 0.003;
const GATE_SUBMERGED_BAND_UPPER_INSET_MIN = 0.03;

function submergedBandUpperY(threshold: number): number {
    return threshold - Math.max(Math.abs(threshold) * GATE_SUBMERGED_BAND_UPPER_INSET_RATIO, GATE_SUBMERGED_BAND_UPPER_INSET_MIN);
}

export interface GateSubmergedBandSegment {
    xValues: number[];
    yValues: number[];
    y1Values: number[];
}

function buildGateSubmergedBandSegments(xValues: number[], regimeSmaSeries: number[], threshold: number | undefined): GateSubmergedBandSegment[] {
    if (threshold == null) {
        return [];
    }

    const segments: GateSubmergedBandSegment[] = [];
    const length = Math.min(xValues.length, regimeSmaSeries.length);
    let current: GateSubmergedBandSegment | null = null;

    const flushCurrent = (): void => {
        if (current && current.xValues.length >= GATE_SUBMERGED_BAND_MIN_SEGMENT_POINTS) {
            segments.push(current);
        }
        current = null;
    };

    for (let index = 0; index < length; index++) {
        const regimeSma = regimeSmaSeries[index];
        if (!Number.isFinite(regimeSma) || regimeSma >= threshold) {
            flushCurrent();
            continue;
        }
        if (!current) {
            current = { xValues: [], yValues: [], y1Values: [] };
        }
        current.xValues.push(xValues[index] ?? 0);
        current.yValues.push(submergedBandUpperY(threshold));
        current.y1Values.push(regimeSma);
    }
    flushCurrent();
    return segments;
}

export function buildRegimeEvGateSubmergedBandSegments(
    xValues: number[],
    regimeSmaSeries: number[],
    threshold: number | undefined
): GateSubmergedBandSegment[] {
    return buildGateSubmergedBandSegments(xValues, regimeSmaSeries, threshold);
}

export function buildRegimePfGateSubmergedBandSegments(
    xValues: number[],
    regimeSmaSeries: number[],
    threshold: number | undefined
): GateSubmergedBandSegment[] {
    return buildGateSubmergedBandSegments(xValues, regimeSmaSeries, threshold);
}

function createGateSubmergedBandSegmentBundle(
    sci: SciChartModule,
    wasmContext: TSciChart,
    segment: GateSubmergedBandSegment,
    yAxisId: string,
    fill: string,
    isVisible: boolean
): GateSubmergedBandSegmentBundle {
    const { XyyDataSeries, FastBandRenderableSeries } = sci;
    const dataSeries = new XyyDataSeries(wasmContext, {
        xValues: segment.xValues,
        yValues: segment.yValues,
        y1Values: segment.y1Values,
        dataSeriesName: '',
        isSorted: true,
        containsNaN: false
    });
    const series = new FastBandRenderableSeries(wasmContext, {
        dataSeries,
        yAxisId,
        xAxisId: 'xTime',
        seriesName: '',
        stroke: CHRONICLE_METRIC_COLORS.transparent,
        strokeY1: CHRONICLE_METRIC_COLORS.transparent,
        strokeThickness: 0,
        fill: CHRONICLE_METRIC_COLORS.transparent,
        fillY1: fill,
        opacity: 0.68
    });
    series.isVisible = isVisible;
    return { dataSeries, series };
}

function synchronizeGateSubmergedBandSegmentBundle(bundle: GateSubmergedBandSegmentBundle, segment: GateSubmergedBandSegment): void {
    bundle.dataSeries.clear();
    if (segment.xValues.length > 0) {
        bundle.dataSeries.appendRange(segment.xValues, segment.yValues, segment.y1Values);
    }
}

export function buildRegimeEvGateSubmergedBandSegmentBundles(
    sci: SciChartModule,
    wasmContext: TSciChart,
    segments: GateSubmergedBandSegment[],
    isVisible: boolean
): GateSubmergedBandSegmentBundle[] {
    return segments.map((segment) =>
        createGateSubmergedBandSegmentBundle(sci, wasmContext, segment, 'yRegimeEv', CHRONICLE_METRIC_COLORS.gateSubmergedExpectedValueFill, isVisible)
    );
}

export function buildRegimePfGateSubmergedBandSegmentBundles(
    sci: SciChartModule,
    wasmContext: TSciChart,
    segments: GateSubmergedBandSegment[],
    isVisible: boolean
): GateSubmergedBandSegmentBundle[] {
    return segments.map((segment) =>
        createGateSubmergedBandSegmentBundle(sci, wasmContext, segment, 'yRegimePf', CHRONICLE_METRIC_COLORS.gateSubmergedProfitFactorFill, isVisible)
    );
}

export function synchronizeRegimeEvGateSubmergedBandSegmentBundles(
    model: ChronicleChartModel,
    sci: SciChartModule,
    wasmContext: TSciChart,
    segments: GateSubmergedBandSegment[]
): void {
    synchronizeGateSubmergedBandSegmentBundles(
        model,
        sci,
        wasmContext,
        segments,
        model.regimeEvGateSubmergedBandSegmentBundles,
        (segment, isVisible) => buildRegimeEvGateSubmergedBandSegmentBundles(sci, wasmContext, [segment], isVisible)[0],
        model.evGateThresholdUserVisible
    );
}

export function synchronizeRegimePfGateSubmergedBandSegmentBundles(
    model: ChronicleChartModel,
    sci: SciChartModule,
    wasmContext: TSciChart,
    segments: GateSubmergedBandSegment[]
): void {
    synchronizeGateSubmergedBandSegmentBundles(
        model,
        sci,
        wasmContext,
        segments,
        model.regimePfGateSubmergedBandSegmentBundles,
        (segment, isVisible) => buildRegimePfGateSubmergedBandSegmentBundles(sci, wasmContext, [segment], isVisible)[0],
        model.pfGateThresholdUserVisible
    );
}

function synchronizeGateSubmergedBandSegmentBundles(
    model: ChronicleChartModel,
    sci: SciChartModule,
    wasmContext: TSciChart,
    segments: GateSubmergedBandSegment[],
    existingBundles: GateSubmergedBandSegmentBundle[],
    createBundle: (segment: GateSubmergedBandSegment, isVisible: boolean) => GateSubmergedBandSegmentBundle,
    defaultVisible: boolean
): void {
    const targetCount = segments.length;
    const bandVisible = defaultVisible;

    for (let index = 0; index < targetCount; index++) {
        const segment = segments[index];
        if (index < existingBundles.length) {
            synchronizeGateSubmergedBandSegmentBundle(existingBundles[index], segment);
            existingBundles[index].series.isVisible = bandVisible;
            continue;
        }
        const bundle = createBundle(segment, bandVisible);
        model.sciChartSurface.renderableSeries.add(bundle.series);
        existingBundles.push(bundle);
    }

    for (let index = targetCount; index < existingBundles.length; index++) {
        existingBundles[index].dataSeries.clear();
        existingBundles[index].series.isVisible = false;
    }
    raiseChronicleGateThresholdAnnotations(model);
}

export function buildRegimeEvGateSubmergedBandSegmentsFromArrays(
    metricTimestampsMilliseconds: number[],
    arrays: Parameters<typeof buildChronicleGoldenZoneExpectedValueSubmergedBandValues>[0],
    threshold: number | undefined
): GateSubmergedBandSegment[] {
    return buildRegimeEvGateSubmergedBandSegments(metricTimestampsMilliseconds, resolveRegimeGateExpectedValueSmaSeries(arrays), threshold);
}

export function buildRegimePfGateSubmergedBandSegmentsFromArrays(
    metricTimestampsMilliseconds: number[],
    arrays: Parameters<typeof buildChronicleGoldenZoneProfitFactorSubmergedBandValues>[0],
    threshold: number | undefined
): GateSubmergedBandSegment[] {
    return buildRegimePfGateSubmergedBandSegments(metricTimestampsMilliseconds, resolveRegimeGateProfitFactorSmaSeries(arrays), threshold);
}
