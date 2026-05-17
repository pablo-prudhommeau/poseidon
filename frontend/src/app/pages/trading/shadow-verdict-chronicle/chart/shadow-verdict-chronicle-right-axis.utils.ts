import type {
    ChronicleArrays,
    ChronicleAxisDescriptor,
    ChronicleAxisTickBounds,
    ChronicleChartModel,
    ChronicleConfigurableAxisOptions,
    ChronicleGoldenZoneThresholds,
    ChronicleNumericBounds,
    ChronicleRenderableSeriesCollectionLike,
    ChronicleVisibilityToggleSeriesLike
} from '../data/shadow-verdict-chronicle.models';
import { CHRONICLE_SERIES } from '../data/shadow-verdict-chronicle-series-names';
import {
    buildChronicleGoldenZoneExpectedValueBandValues,
    buildChronicleGoldenZoneExpectedValueSubmergedBandValues,
    buildChronicleGoldenZoneProfitFactorBandValues,
    buildChronicleGoldenZoneProfitFactorSubmergedBandValues,
    resolveRegimeGateExpectedValueSmaSeries,
    resolveRegimeGateProfitFactorSmaSeries
} from './shadow-verdict-chronicle-golden-zone.utils';

const CHRONICLE_AXIS_PADDING_RATIO = 0.01;
const CHRONICLE_VOLUME_AXIS_TOP_PADDING_RATIO = 0.08;
const CHRONICLE_REGIME_GATE_AXIS_PADDING_RATIO = 0.26;
const CHRONICLE_REGIME_GATE_SPLINE_HEADROOM_MULTIPLIER = 1.35;

function computeFiniteBounds(values: number[]): ChronicleNumericBounds | null {
    let minimum = Number.POSITIVE_INFINITY;
    let maximum = Number.NEGATIVE_INFINITY;
    for (const value of values) {
        if (!Number.isFinite(value)) {
            continue;
        }
        if (value < minimum) {
            minimum = value;
        }
        if (value > maximum) {
            maximum = value;
        }
    }
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
        return null;
    }
    if (minimum === maximum) {
        const epsilon = Math.max(1e-6, Math.abs(minimum) * 0.05);
        return { min: minimum - epsilon, max: maximum + epsilon };
    }
    return { min: minimum, max: maximum };
}

function computeAdaptiveSplineOvershootPadding(values: number[], bounds: ChronicleNumericBounds): number {
    const finiteValues = values.filter((value: number) => Number.isFinite(value));
    if (finiteValues.length < 3) {
        return 0;
    }
    let maximumDelta = 0;
    let totalDelta = 0;
    let deltaCount = 0;
    for (let index = 1; index < finiteValues.length; index++) {
        const delta = Math.abs(finiteValues[index] - finiteValues[index - 1]);
        maximumDelta = Math.max(maximumDelta, delta);
        totalDelta += delta;
        deltaCount += 1;
    }
    if (deltaCount === 0) {
        return 0;
    }
    const averageDelta = totalDelta / deltaCount;
    const span = Math.max(1e-9, bounds.max - bounds.min);
    const rawPadding = Math.max(averageDelta * 0.9, maximumDelta * 0.35);
    const cappedPadding = Math.min(span * 0.35, rawPadding);
    return Math.max(0, cappedPadding);
}

function normalizeBoundsToTickCount(minimum: number, maximum: number, targetTicks: number): ChronicleAxisTickBounds {
    const span = Math.max(1e-9, maximum - minimum);
    const paddedMinimum = minimum - span * CHRONICLE_AXIS_PADDING_RATIO;
    const paddedMaximum = maximum + span * CHRONICLE_AXIS_PADDING_RATIO;
    const majorDelta = Math.max(1e-9, (paddedMaximum - paddedMinimum) / (targetTicks - 1));
    const normalizedSpan = majorDelta * (targetTicks - 1);
    const center = (paddedMinimum + paddedMaximum) / 2;
    const centeredMinimum = center - normalizedSpan / 2;
    let normalizedMinimum = Math.floor(centeredMinimum / majorDelta) * majorDelta;
    let normalizedMaximum = normalizedMinimum + normalizedSpan;
    if (normalizedMaximum < paddedMaximum) {
        const stepsToRaise = Math.ceil((paddedMaximum - normalizedMaximum) / majorDelta);
        normalizedMinimum += stepsToRaise * majorDelta;
        normalizedMaximum += stepsToRaise * majorDelta;
    }
    if (normalizedMinimum > paddedMinimum) {
        const stepsToLower = Math.ceil((normalizedMinimum - paddedMinimum) / majorDelta);
        normalizedMinimum -= stepsToLower * majorDelta;
        normalizedMaximum -= stepsToLower * majorDelta;
    }
    return { min: normalizedMinimum, max: normalizedMaximum, majorDelta };
}

function normalizeBoundsToStep(minimum: number, maximum: number, targetTicks: number, step: number): ChronicleAxisTickBounds {
    const safeStep = Math.max(1e-9, step);
    const span = Math.max(safeStep, maximum - minimum);
    const paddedMinimum = minimum - span * CHRONICLE_AXIS_PADDING_RATIO;
    const paddedMaximum = maximum + span * CHRONICLE_AXIS_PADDING_RATIO;
    const rawDelta = Math.max(safeStep, (paddedMaximum - paddedMinimum) / Math.max(1, targetTicks - 1));
    const majorDelta = Math.ceil(rawDelta / safeStep) * safeStep;
    const normalizedSpan = majorDelta * (targetTicks - 1);
    const center = (paddedMinimum + paddedMaximum) / 2;
    const centeredMinimum = center - normalizedSpan / 2;
    let normalizedMinimum = Math.floor(centeredMinimum / majorDelta) * majorDelta;
    let normalizedMaximum = normalizedMinimum + normalizedSpan;
    if (normalizedMaximum < paddedMaximum) {
        const stepsToRaise = Math.ceil((paddedMaximum - normalizedMaximum) / majorDelta);
        normalizedMinimum += stepsToRaise * majorDelta;
        normalizedMaximum += stepsToRaise * majorDelta;
    }
    if (normalizedMinimum > paddedMinimum) {
        const stepsToLower = Math.ceil((normalizedMinimum - paddedMinimum) / majorDelta);
        normalizedMinimum -= stepsToLower * majorDelta;
        normalizedMaximum -= stepsToLower * majorDelta;
    }
    return { min: normalizedMinimum, max: normalizedMaximum, majorDelta };
}

function normalizeRegimeGateAxisBounds(minimum: number, maximum: number, targetTicks: number): ChronicleAxisTickBounds {
    const span = Math.max(1e-9, maximum - minimum);
    const paddedMinimum = minimum - span * CHRONICLE_REGIME_GATE_AXIS_PADDING_RATIO;
    const paddedMaximum = maximum + span * CHRONICLE_REGIME_GATE_AXIS_PADDING_RATIO;
    return normalizeBoundsToTickCount(paddedMinimum, paddedMaximum, targetTicks);
}

function normalizeBoundsToStepFromZero(maximum: number, targetTicks: number, step: number): ChronicleAxisTickBounds {
    const safeStep = Math.max(1e-9, step);
    const minimum = 0;
    const span = Math.max(safeStep, maximum - minimum);
    const paddedMaximum = maximum + span * CHRONICLE_VOLUME_AXIS_TOP_PADDING_RATIO;
    const rawDelta = Math.max(safeStep, (paddedMaximum - minimum) / Math.max(1, targetTicks - 1));
    const majorDelta = Math.ceil(rawDelta / safeStep) * safeStep;
    return { min: minimum, max: minimum + majorDelta * (targetTicks - 1), majorDelta };
}

function finiteSeriesValues(values: number[]): number[] {
    return values.filter((value) => Number.isFinite(value));
}

function isChronicleRenderableSeriesVisible(model: ChronicleChartModel, seriesName: string): boolean {
    if (seriesName === CHRONICLE_SERIES.evGateThreshold) {
        return model.evGateThresholdUserVisible;
    }
    if (seriesName === CHRONICLE_SERIES.pfGateThreshold) {
        return model.pfGateThresholdUserVisible;
    }
    if (seriesName === CHRONICLE_SERIES.cortexCalibrationBand) {
        return model.cortexCalibrationBandUserVisible;
    }
    const rawSeries = model.sciChartSurface.renderableSeries as unknown as ChronicleRenderableSeriesCollectionLike;
    const seriesList = rawSeries.asArray ? rawSeries.asArray() : (rawSeries.items ?? []);
    for (const entry of seriesList) {
        const series = entry as ChronicleVisibilityToggleSeriesLike;
        if ((series.seriesName ?? '').trim() === seriesName) {
            return series.isVisible ?? true;
        }
    }
    return false;
}

function valuesIfSeriesVisible(model: ChronicleChartModel, seriesName: string, values: number[]): number[] {
    return isChronicleRenderableSeriesVisible(model, seriesName) ? finiteSeriesValues(values) : [];
}

function isVolumeVisible(model: ChronicleChartModel): boolean {
    return isChronicleRenderableSeriesVisible(model, CHRONICLE_SERIES.volumeColumns);
}

function buildRegimeEvGateAxisValues(model: ChronicleChartModel, arrays: ChronicleArrays, goldenZoneThresholds?: ChronicleGoldenZoneThresholds): number[] {
    if (!model.evGateThresholdUserVisible) {
        return [];
    }
    const threshold = goldenZoneThresholds?.sparseExpectedValueThreshold;
    return [
        ...finiteSeriesValues(resolveRegimeGateExpectedValueSmaSeries(arrays)),
        ...(threshold != null ? [threshold] : []),
        ...finiteSeriesValues(buildChronicleGoldenZoneExpectedValueSubmergedBandValues(arrays, threshold)),
        ...finiteSeriesValues(buildChronicleGoldenZoneExpectedValueBandValues(arrays, threshold))
    ];
}

function buildRegimePfGateAxisValues(model: ChronicleChartModel, arrays: ChronicleArrays, goldenZoneThresholds?: ChronicleGoldenZoneThresholds): number[] {
    if (!model.pfGateThresholdUserVisible) {
        return [];
    }
    const threshold = goldenZoneThresholds?.chronicleProfitFactorThreshold;
    return [
        ...finiteSeriesValues(resolveRegimeGateProfitFactorSmaSeries(arrays)),
        ...(threshold != null ? [threshold] : []),
        ...finiteSeriesValues(buildChronicleGoldenZoneProfitFactorSubmergedBandValues(arrays, threshold)),
        ...finiteSeriesValues(buildChronicleGoldenZoneProfitFactorBandValues(arrays, threshold))
    ];
}

type AxisNormalizationMode = 'volume' | 'step-one' | 'tick' | 'regime-gate';

interface ChronicleRightAxisHarmonizationDescriptor {
    axis: ChronicleChartModel['yVolumeAxis'];
    values: number[];
    normalization: AxisNormalizationMode;
    usesSplineLineHeadroom?: boolean;
}

function applyHarmonizedAxisRange(model: ChronicleChartModel, descriptor: ChronicleRightAxisHarmonizationDescriptor, targetTicks: number): void {
    const { NumberRange, EAutoRange } = model.sci;
    const axisOptions = descriptor.axis as unknown as ChronicleConfigurableAxisOptions;

    if (descriptor.values.length === 0) {
        axisOptions.isVisible = false;
        return;
    }

    const bounds = computeFiniteBounds(descriptor.values);
    if (!bounds) {
        axisOptions.isVisible = false;
        return;
    }

    axisOptions.isVisible = true;

    const usesSplineLineHeadroom = descriptor.usesSplineLineHeadroom ?? false;
    const isRegimeGateAxis = descriptor.normalization === 'regime-gate';
    const normalizedBounds = usesSplineLineHeadroom
        ? {
              min: bounds.min,
              max:
                  bounds.max +
                  computeAdaptiveSplineOvershootPadding(descriptor.values, bounds) * (isRegimeGateAxis ? CHRONICLE_REGIME_GATE_SPLINE_HEADROOM_MULTIPLIER : 1)
          }
        : bounds;

    const normalized =
        descriptor.normalization === 'volume'
            ? normalizeBoundsToStepFromZero(bounds.max, targetTicks, 5)
            : descriptor.normalization === 'step-one'
              ? normalizeBoundsToStep(normalizedBounds.min, normalizedBounds.max, targetTicks, 1)
              : descriptor.normalization === 'regime-gate'
                ? normalizeRegimeGateAxisBounds(normalizedBounds.min, normalizedBounds.max, targetTicks)
                : normalizeBoundsToTickCount(normalizedBounds.min, normalizedBounds.max, targetTicks);

    descriptor.axis.autoRange = EAutoRange.Never;
    descriptor.axis.visibleRange = new NumberRange(normalized.min, normalized.max);
    axisOptions.autoTicks = false;
    axisOptions.majorDelta = normalized.majorDelta;
    axisOptions.minorDelta =
        descriptor.normalization === 'volume' || descriptor.normalization === 'step-one' ? Math.max(1, normalized.majorDelta / 5) : normalized.majorDelta / 4;
}

export function harmonizeChronicleRightAxes(
    model: ChronicleChartModel,
    arrays: ChronicleArrays,
    rightAxisMajorTickCount: number,
    goldenZoneThresholds?: ChronicleGoldenZoneThresholds
): void {
    const targetTicks = Math.max(3, rightAxisMajorTickCount);
    const axisDescriptors: ChronicleRightAxisHarmonizationDescriptor[] = [
        {
            axis: model.yVolumeAxis,
            values: isVolumeVisible(model) ? finiteSeriesValues(arrays.volumeBucketVerdictCounts) : [],
            normalization: 'volume'
        },
        {
            axis: model.yExpectedValueAxis,
            values: [
                ...valuesIfSeriesVisible(model, CHRONICLE_SERIES.expectedValueLine, arrays.expectedValuePerTradeUsdSeries),
                ...valuesIfSeriesVisible(model, CHRONICLE_SERIES.smaExpectedValueLine, arrays.movingAverageExpectedValueSeries)
            ],
            normalization: 'step-one',
            usesSplineLineHeadroom: true
        },
        {
            axis: model.yProfitFactorAxis,
            values: [
                ...valuesIfSeriesVisible(model, CHRONICLE_SERIES.profitFactorLine, arrays.profitFactorSeries),
                ...valuesIfSeriesVisible(model, CHRONICLE_SERIES.smaProfitFactorLine, arrays.movingAverageProfitFactorSeries)
            ],
            normalization: 'tick',
            usesSplineLineHeadroom: true
        },
        {
            axis: model.yTradesPerHourAxis,
            values: [
                ...valuesIfSeriesVisible(model, CHRONICLE_SERIES.tradesPerHourLine, arrays.closedVerdictsPerHourSeries),
                ...valuesIfSeriesVisible(model, CHRONICLE_SERIES.smaTradesPerHourLine, arrays.movingAverageTradesPerHourSeries)
            ],
            normalization: 'step-one',
            usesSplineLineHeadroom: true
        },
        {
            axis: model.yRegimeEvAxis,
            values: buildRegimeEvGateAxisValues(model, arrays, goldenZoneThresholds),
            normalization: 'regime-gate',
            usesSplineLineHeadroom: true
        },
        {
            axis: model.yRegimePfAxis,
            values: buildRegimePfGateAxisValues(model, arrays, goldenZoneThresholds),
            normalization: 'regime-gate',
            usesSplineLineHeadroom: true
        }
    ];

    for (const descriptor of axisDescriptors) {
        applyHarmonizedAxisRange(model, descriptor, targetTicks);
    }
}
