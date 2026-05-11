import type {
    ChronicleArrays,
    ChronicleAxisDescriptor,
    ChronicleAxisTickBounds,
    ChronicleChartModel,
    ChronicleConfigurableAxisOptions,
    ChronicleGoldenZoneThresholds,
    ChronicleNumericBounds,
} from '../data/shadow-verdict-chronicle.models';

const CHRONICLE_AXIS_PADDING_RATIO = 0.01;
const CHRONICLE_VOLUME_AXIS_TOP_PADDING_RATIO = 0.08;

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
        return {min: minimum - epsilon, max: maximum + epsilon};
    }
    return {min: minimum, max: maximum};
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
    return {min: normalizedMinimum, max: normalizedMaximum, majorDelta};
}

function normalizeBoundsToStep(
    minimum: number,
    maximum: number,
    targetTicks: number,
    step: number,
): ChronicleAxisTickBounds {
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
    return {min: normalizedMinimum, max: normalizedMaximum, majorDelta};
}

function normalizeBoundsToStepFromZero(maximum: number, targetTicks: number, step: number): ChronicleAxisTickBounds {
    const safeStep = Math.max(1e-9, step);
    const minimum = 0;
    const span = Math.max(safeStep, maximum - minimum);
    const paddedMaximum = maximum + span * CHRONICLE_VOLUME_AXIS_TOP_PADDING_RATIO;
    const rawDelta = Math.max(safeStep, (paddedMaximum - minimum) / Math.max(1, targetTicks - 1));
    const majorDelta = Math.ceil(rawDelta / safeStep) * safeStep;
    return {min: minimum, max: minimum + majorDelta * (targetTicks - 1), majorDelta};
}

export function harmonizeChronicleRightAxes(
    model: ChronicleChartModel,
    arrays: ChronicleArrays,
    rightAxisMajorTickCount: number,
    goldenZoneThresholds?: ChronicleGoldenZoneThresholds,
): void {
    const targetTicks = Math.max(3, rightAxisMajorTickCount);
    const {NumberRange, EAutoRange} = model.sci;
    const axisDescriptors: Array<ChronicleAxisDescriptor<ChronicleChartModel['yVolumeAxis']>> = [
        {axis: model.yVolumeAxis, values: arrays.volumeBucketVerdictCounts},
        {
            axis: model.yExpectedValueAxis,
            values: [
                ...arrays.expectedValuePerTradeUsdSeries,
                ...arrays.movingAverageExpectedValueSeries,
                ...(goldenZoneThresholds?.sparseExpectedValueThreshold != null
                    ? [goldenZoneThresholds.sparseExpectedValueThreshold]
                    : []),
            ],
        },
        {
            axis: model.yProfitFactorAxis,
            values: [
                ...arrays.profitFactorSeries,
                ...arrays.movingAverageProfitFactorSeries,
                ...(goldenZoneThresholds?.chronicleProfitFactorThreshold != null
                    ? [goldenZoneThresholds.chronicleProfitFactorThreshold]
                    : []),
            ],
        },
        {
            axis: model.yVelocityAxis,
            values: [...arrays.capitalVelocityPerHourSeries, ...arrays.movingAverageVelocitySeries],
        },
    ];

    for (const descriptor of axisDescriptors) {
        const bounds = computeFiniteBounds(descriptor.values);
        if (!bounds) {
            continue;
        }
        const usesSplineLineHeadroom =
            descriptor.axis === model.yExpectedValueAxis
            || descriptor.axis === model.yProfitFactorAxis
            || descriptor.axis === model.yVelocityAxis;
        const normalizedBounds = usesSplineLineHeadroom
            ? {
                min: bounds.min,
                max: bounds.max + computeAdaptiveSplineOvershootPadding(descriptor.values, bounds),
            }
            : bounds;
        const normalized =
            descriptor.axis === model.yVolumeAxis
                ? normalizeBoundsToStepFromZero(bounds.max, targetTicks, 5)
                : descriptor.axis === model.yExpectedValueAxis || descriptor.axis === model.yVelocityAxis
                    ? normalizeBoundsToStep(normalizedBounds.min, normalizedBounds.max, targetTicks, 1)
                    : normalizeBoundsToTickCount(normalizedBounds.min, normalizedBounds.max, targetTicks);
        descriptor.axis.autoRange = EAutoRange.Never;
        descriptor.axis.visibleRange = new NumberRange(normalized.min, normalized.max);
        const axisOptions = descriptor.axis as unknown as ChronicleConfigurableAxisOptions;
        axisOptions.autoTicks = false;
        axisOptions.majorDelta = normalized.majorDelta;
        axisOptions.minorDelta =
            descriptor.axis === model.yVolumeAxis
                ? Math.max(1, normalized.majorDelta / 5)
                : descriptor.axis === model.yExpectedValueAxis || descriptor.axis === model.yVelocityAxis
                    ? Math.max(1, normalized.majorDelta / 5)
                    : normalized.majorDelta / 4;
    }
}
