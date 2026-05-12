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

export function isChronicleMovingAverageSeriesVisible(model: ChronicleChartModel, seriesName: string): boolean {
    const series = model.movingAverageLineRenderableSeries.find((entry) => entry.seriesName === seriesName);
    return series?.isVisible ?? false;
}

export function applyChronicleGoldenZoneVisualState(
    model: ChronicleChartModel,
    thresholds: ChronicleGoldenZoneThresholds,
    isSmaExpectedValueVisible: boolean,
    isSmaProfitFactorVisible: boolean
): void {
    const isSmaExpectedValueAreaVisible = model.goldenZoneExpectedValueBandSeries.isVisible;
    const isSmaProfitFactorAreaVisible = model.goldenZoneProfitFactorBandSeries.isVisible;
    model.goldenZoneExpectedValueSmaPaletteController.setThreshold(thresholds.sparseExpectedValueThreshold);
    if (model.goldenZoneExpectedValueAnnotation) {
        if (thresholds.sparseExpectedValueThreshold == null) {
            model.goldenZoneExpectedValueAnnotation.isHidden = true;
            model.goldenZoneExpectedValueBandSeries.isVisible = false;
        } else {
            model.goldenZoneExpectedValueAnnotation.y1 = thresholds.sparseExpectedValueThreshold;
            model.goldenZoneExpectedValueAnnotation.isHidden = !(isSmaExpectedValueVisible || isSmaExpectedValueAreaVisible);
            model.goldenZoneExpectedValueBandSeries.zeroLineY = thresholds.sparseExpectedValueThreshold;
        }
    }
    model.goldenZoneProfitFactorSmaPaletteController.setThreshold(thresholds.chronicleProfitFactorThreshold);
    if (model.goldenZoneProfitFactorAnnotation) {
        if (thresholds.chronicleProfitFactorThreshold == null) {
            model.goldenZoneProfitFactorAnnotation.isHidden = true;
            model.goldenZoneProfitFactorBandSeries.isVisible = false;
        } else {
            model.goldenZoneProfitFactorAnnotation.y1 = thresholds.chronicleProfitFactorThreshold;
            model.goldenZoneProfitFactorAnnotation.isHidden = !(isSmaProfitFactorVisible || isSmaProfitFactorAreaVisible);
            model.goldenZoneProfitFactorBandSeries.zeroLineY = thresholds.chronicleProfitFactorThreshold;
        }
    }
}

export function buildChronicleGoldenZoneExpectedValueBandValues(arrays: ChronicleArrays, sparseExpectedValueThreshold: number | undefined): number[] {
    if (sparseExpectedValueThreshold == null) {
        return arrays.movingAverageExpectedValueSeries.map(() => 0);
    }
    return arrays.movingAverageExpectedValueSeries.map((value: number) => (value > sparseExpectedValueThreshold ? value : sparseExpectedValueThreshold));
}

export function buildChronicleGoldenZoneProfitFactorBandValues(arrays: ChronicleArrays, chronicleProfitFactorThreshold: number | undefined): number[] {
    if (chronicleProfitFactorThreshold == null) {
        return arrays.movingAverageProfitFactorSeries.map(() => 0);
    }
    return arrays.movingAverageProfitFactorSeries.map((value: number) => (value > chronicleProfitFactorThreshold ? value : chronicleProfitFactorThreshold));
}
