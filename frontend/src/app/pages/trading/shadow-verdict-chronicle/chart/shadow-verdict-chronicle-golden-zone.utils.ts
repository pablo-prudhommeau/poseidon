import type { ChronicleArrays, ChronicleBucketMeta, ChronicleChartModel, ChronicleGoldenZoneThresholds } from '../data/shadow-verdict-chronicle.models';

function toFiniteThreshold(value: number | string | null | undefined): number | undefined {
    const numeric = typeof value === 'string' ? Number(value) : value;
    return typeof numeric === 'number' && Number.isFinite(numeric) ? numeric : undefined;
}

export function resolveChronicleGoldenZoneThresholds(meta: ChronicleBucketMeta): ChronicleGoldenZoneThresholds {
    return {
        sparseExpectedValueThreshold: toFiniteThreshold(meta.sparseExpectedValueUsdThreshold),
        chronicleProfitFactorThreshold: toFiniteThreshold(meta.chronicleProfitFactorThreshold)
    };
}

export function raiseChronicleGateThresholdAnnotations(model: ChronicleChartModel): void {
    const annotations = model.sciChartSurface.annotations;
    for (const annotation of [model.goldenZoneExpectedValueAnnotation, model.goldenZoneProfitFactorAnnotation]) {
        if (!annotation) {
            continue;
        }
        annotations.remove(annotation);
        annotations.add(annotation);
    }
}

export function applyChronicleGoldenZoneVisualState(model: ChronicleChartModel, thresholds: ChronicleGoldenZoneThresholds): void {
    if (model.goldenZoneExpectedValueAnnotation) {
        if (thresholds.sparseExpectedValueThreshold == null) {
            model.goldenZoneExpectedValueAnnotation.isHidden = true;
            model.goldenZoneExpectedValueBandSeries.isVisible = false;
            for (const bundle of model.regimeEvGateSubmergedBandSegmentBundles) {
                bundle.series.isVisible = false;
            }
        } else {
            model.goldenZoneExpectedValueAnnotation.y1 = thresholds.sparseExpectedValueThreshold;
            model.goldenZoneExpectedValueAnnotation.isHidden = !model.evGateThresholdUserVisible;
            model.goldenZoneExpectedValueBandSeries.zeroLineY = thresholds.sparseExpectedValueThreshold;
            model.goldenZoneExpectedValueBandSeries.isVisible = model.evGateThresholdUserVisible;
            for (const bundle of model.regimeEvGateSubmergedBandSegmentBundles) {
                bundle.series.isVisible = model.evGateThresholdUserVisible;
            }
        }
    }
    if (model.goldenZoneProfitFactorAnnotation) {
        if (thresholds.chronicleProfitFactorThreshold == null) {
            model.goldenZoneProfitFactorAnnotation.isHidden = true;
            model.goldenZoneProfitFactorBandSeries.isVisible = false;
            for (const bundle of model.regimePfGateSubmergedBandSegmentBundles) {
                bundle.series.isVisible = false;
            }
        } else {
            model.goldenZoneProfitFactorAnnotation.y1 = thresholds.chronicleProfitFactorThreshold;
            model.goldenZoneProfitFactorAnnotation.isHidden = !model.pfGateThresholdUserVisible;
            model.goldenZoneProfitFactorBandSeries.zeroLineY = thresholds.chronicleProfitFactorThreshold;
            model.goldenZoneProfitFactorBandSeries.isVisible = model.pfGateThresholdUserVisible;
            for (const bundle of model.regimePfGateSubmergedBandSegmentBundles) {
                bundle.series.isVisible = model.pfGateThresholdUserVisible;
            }
        }
    }
    raiseChronicleGateThresholdAnnotations(model);
}

function resolveRegimeSparseExpectedValueSmaSeries(arrays: ChronicleArrays): number[] {
    const hasRegimeSeries = arrays.regimeSparseExpectedValueUsdSmaSeries.some((value) => Number.isFinite(value));
    return hasRegimeSeries ? arrays.regimeSparseExpectedValueUsdSmaSeries : arrays.movingAverageExpectedValueSeries;
}

function resolveRegimeProfitFactorSmaSeries(arrays: ChronicleArrays): number[] {
    const hasRegimeSeries = arrays.regimeProfitFactorSmaSeries.some((value) => Number.isFinite(value));
    return hasRegimeSeries ? arrays.regimeProfitFactorSmaSeries : arrays.movingAverageProfitFactorSeries;
}

const ILLUMINATED_GATE_MOUNTAIN_WATERLINE_ANCHOR_BUCKETS = 2;

function regimeSmaIsAboveGateThreshold(value: number, threshold: number): boolean {
    return Number.isFinite(value) && value > threshold;
}

function distanceToNearestAboveThresholdBucket(aboveThreshold: boolean[]): number[] {
    const length = aboveThreshold.length;
    const distance = Array.from({ length }, (_, index) => (aboveThreshold[index] ? 0 : Number.POSITIVE_INFINITY));

    for (let index = 1; index < length; index++) {
        if (Number.isFinite(distance[index - 1])) {
            distance[index] = Math.min(distance[index], distance[index - 1] + 1);
        }
    }
    for (let index = length - 2; index >= 0; index--) {
        if (Number.isFinite(distance[index + 1])) {
            distance[index] = Math.min(distance[index], distance[index + 1] + 1);
        }
    }
    return distance;
}

function buildIlluminatedGateMountainBandValues(regimeSmaSeries: number[], threshold: number): number[] {
    const aboveThreshold = regimeSmaSeries.map((value) => regimeSmaIsAboveGateThreshold(value, threshold));
    const distanceToPeak = distanceToNearestAboveThresholdBucket(aboveThreshold);

    return regimeSmaSeries.map((value, index) => {
        if (aboveThreshold[index]) {
            return value;
        }
        if (!Number.isFinite(value)) {
            return Number.NaN;
        }
        const distance = distanceToPeak[index] ?? Number.POSITIVE_INFINITY;
        if (distance > 0 && distance <= ILLUMINATED_GATE_MOUNTAIN_WATERLINE_ANCHOR_BUCKETS) {
            return threshold;
        }
        return Number.NaN;
    });
}

export function buildChronicleGoldenZoneExpectedValueBandValues(arrays: ChronicleArrays, sparseExpectedValueThreshold: number | undefined): number[] {
    const regimeSparseExpectedValueSmaSeries = resolveRegimeSparseExpectedValueSmaSeries(arrays);
    if (sparseExpectedValueThreshold == null) {
        return regimeSparseExpectedValueSmaSeries.map(() => 0);
    }
    return buildIlluminatedGateMountainBandValues(regimeSparseExpectedValueSmaSeries, sparseExpectedValueThreshold);
}

export function buildChronicleGoldenZoneExpectedValueSubmergedBandValues(arrays: ChronicleArrays, sparseExpectedValueThreshold: number | undefined): number[] {
    const regimeSparseExpectedValueSmaSeries = resolveRegimeSparseExpectedValueSmaSeries(arrays);
    if (sparseExpectedValueThreshold == null) {
        return regimeSparseExpectedValueSmaSeries.map(() => 0);
    }
    return regimeSparseExpectedValueSmaSeries.map((value: number) => {
        if (!Number.isFinite(value) || value >= sparseExpectedValueThreshold) {
            return sparseExpectedValueThreshold;
        }
        return value;
    });
}

export function buildChronicleGoldenZoneProfitFactorBandValues(arrays: ChronicleArrays, chronicleProfitFactorThreshold: number | undefined): number[] {
    const regimeProfitFactorSmaSeries = resolveRegimeProfitFactorSmaSeries(arrays);
    if (chronicleProfitFactorThreshold == null) {
        return regimeProfitFactorSmaSeries.map(() => 0);
    }
    return buildIlluminatedGateMountainBandValues(regimeProfitFactorSmaSeries, chronicleProfitFactorThreshold);
}

export function buildChronicleGoldenZoneProfitFactorSubmergedBandValues(arrays: ChronicleArrays, chronicleProfitFactorThreshold: number | undefined): number[] {
    const regimeProfitFactorSmaSeries = resolveRegimeProfitFactorSmaSeries(arrays);
    if (chronicleProfitFactorThreshold == null) {
        return regimeProfitFactorSmaSeries.map(() => 0);
    }
    return regimeProfitFactorSmaSeries.map((value: number) => {
        if (!Number.isFinite(value) || value >= chronicleProfitFactorThreshold) {
            return chronicleProfitFactorThreshold;
        }
        return value;
    });
}

export function resolveRegimeGateExpectedValueSmaSeries(arrays: ChronicleArrays): number[] {
    return resolveRegimeSparseExpectedValueSmaSeries(arrays);
}

export function resolveRegimeGateProfitFactorSmaSeries(arrays: ChronicleArrays): number[] {
    return resolveRegimeProfitFactorSmaSeries(arrays);
}
