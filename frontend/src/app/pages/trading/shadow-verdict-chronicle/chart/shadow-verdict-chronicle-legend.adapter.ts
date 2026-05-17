import type {
    ChronicleChartModel,
    ChronicleLegendRenderableSeriesLike,
    ChronicleRenderableSeriesCollectionLike,
    ChronicleVisibilityToggleSeriesLike
} from '../data/shadow-verdict-chronicle.models';
import {
    chronicleLegendSwatchKind,
    chronicleSeriesUsesDashedLegendSwatch,
    type ChronicleLegendSwatchKind
} from '../data/shadow-verdict-chronicle-legend.utils';
import { CHRONICLE_LEGEND_PREFERRED_ORDER, CHRONICLE_METRIC_COLORS } from '../data/shadow-verdict-chronicle-metrics.catalog';
import { CHRONICLE_SERIES } from '../data/shadow-verdict-chronicle-series-names';

export interface ChronicleLegendSeriesItem {
    name: string;
    visible: boolean;
    stroke: string;
    dashed: boolean;
    swatchKind: ChronicleLegendSwatchKind;
}

const CHRONICLE_LEGEND_ORDER_INDEX = new Map<string, number>(CHRONICLE_LEGEND_PREFERRED_ORDER.map((seriesName, index) => [seriesName, index]));

function sortChronicleLegendItems(items: ChronicleLegendSeriesItem[]): ChronicleLegendSeriesItem[] {
    return [...items].sort((left, right) => {
        const leftOrder = CHRONICLE_LEGEND_ORDER_INDEX.get(left.name) ?? Number.MAX_SAFE_INTEGER;
        const rightOrder = CHRONICLE_LEGEND_ORDER_INDEX.get(right.name) ?? Number.MAX_SAFE_INTEGER;
        if (leftOrder !== rightOrder) {
            return leftOrder - rightOrder;
        }
        return left.name.localeCompare(right.name);
    });
}

export function listChronicleLegendSeries(model: ChronicleChartModel): ChronicleLegendSeriesItem[] {
    const rawSeries = model.sciChartSurface.renderableSeries as unknown as ChronicleRenderableSeriesCollectionLike;
    const seriesList = rawSeries.asArray ? rawSeries.asArray() : (rawSeries.items ?? []);
    const legendItems: ChronicleLegendSeriesItem[] = [];
    const seenSeriesNames = new Set<string>();
    for (const entry of seriesList) {
        const series = entry as ChronicleLegendRenderableSeriesLike;
        const seriesName = (series.seriesName ?? '').trim();
        if (seriesName.length === 0 || seenSeriesNames.has(seriesName)) {
            continue;
        }
        seenSeriesNames.add(seriesName);
        const swatchKind = chronicleLegendSwatchKind(seriesName);
        const visible =
            seriesName === CHRONICLE_SERIES.cortexCalibrationBand
                ? model.cortexCalibrationBandUserVisible
                : seriesName === CHRONICLE_SERIES.evGateThreshold
                  ? model.evGateThresholdUserVisible
                  : seriesName === CHRONICLE_SERIES.pfGateThreshold
                    ? model.pfGateThresholdUserVisible
                    : (series.isVisible ?? true);
        legendItems.push({
            name: seriesName,
            visible,
            stroke:
                (series.stroke && series.stroke !== CHRONICLE_METRIC_COLORS.transparent ? series.stroke : series.fill) ??
                CHRONICLE_METRIC_COLORS.legendFallbackStroke,
            dashed: chronicleSeriesUsesDashedLegendSwatch(seriesName, series.strokeDashArray),
            swatchKind
        });
    }
    legendItems.push({
        name: CHRONICLE_SERIES.cortexModelRolloutMarker,
        visible: model.cortexModelRolloutUserVisible,
        stroke: CHRONICLE_METRIC_COLORS.cortexRolloutLegendStroke,
        dashed: true,
        swatchKind: chronicleLegendSwatchKind(CHRONICLE_SERIES.cortexModelRolloutMarker)
    });
    return sortChronicleLegendItems(legendItems);
}

export function setChronicleSeriesVisibility(model: ChronicleChartModel, seriesName: string, isVisible: boolean): void {
    const rawSeries = model.sciChartSurface.renderableSeries as unknown as ChronicleRenderableSeriesCollectionLike;
    const seriesList = rawSeries.asArray ? rawSeries.asArray() : (rawSeries.items ?? []);
    if (seriesName === CHRONICLE_SERIES.cortexCalibrationBand) {
        model.cortexCalibrationBandUserVisible = isVisible;
        for (const bundle of model.cortexCalibrationBandSegmentBundles) {
            bundle.series.isVisible = isVisible;
        }
        return;
    }
    if (seriesName === CHRONICLE_SERIES.cortexModelRolloutMarker) {
        model.cortexModelRolloutUserVisible = isVisible;
        for (const bundle of model.cortexModelRolloutAnnotationBundles) {
            bundle.verticalLine.isHidden = !isVisible;
            bundle.textLabel.isHidden = !isVisible;
        }
        return;
    }
    if (seriesName === CHRONICLE_SERIES.evGateThreshold) {
        model.evGateThresholdUserVisible = isVisible;
        for (const bundle of model.regimeEvGateSubmergedBandSegmentBundles) {
            bundle.series.isVisible = isVisible;
        }
        model.goldenZoneExpectedValueBandSeries.isVisible = isVisible;
        if (model.goldenZoneExpectedValueAnnotation) {
            model.goldenZoneExpectedValueAnnotation.isHidden = !isVisible;
        }
        return;
    }
    if (seriesName === CHRONICLE_SERIES.pfGateThreshold) {
        model.pfGateThresholdUserVisible = isVisible;
        for (const bundle of model.regimePfGateSubmergedBandSegmentBundles) {
            bundle.series.isVisible = isVisible;
        }
        model.goldenZoneProfitFactorBandSeries.isVisible = isVisible;
        if (model.goldenZoneProfitFactorAnnotation) {
            model.goldenZoneProfitFactorAnnotation.isHidden = !isVisible;
        }
        return;
    }
    for (const entry of seriesList) {
        const series = entry as ChronicleVisibilityToggleSeriesLike;
        if ((series.seriesName ?? '').trim() === seriesName) {
            series.isVisible = isVisible;
            break;
        }
    }
}
