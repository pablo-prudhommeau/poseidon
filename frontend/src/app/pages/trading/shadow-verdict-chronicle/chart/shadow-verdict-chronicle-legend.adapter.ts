import type {
    ChronicleChartModel,
    ChronicleLegendRenderableSeriesLike,
    ChronicleRenderableSeriesCollectionLike,
    ChronicleVisibilityToggleSeriesLike
} from '../data/shadow-verdict-chronicle.models';
import type { ChronicleTooltipSwatchKind } from '../data/shadow-verdict-chronicle-tooltip.formatter';
import { chronicleTooltipSwatchKind } from '../data/shadow-verdict-chronicle-tooltip.formatter';

export interface ChronicleLegendSeriesItem {
    name: string;
    visible: boolean;
    stroke: string;
    dashed: boolean;
    swatchKind: ChronicleTooltipSwatchKind;
}

export function listChronicleLegendSeries(model: ChronicleChartModel): ChronicleLegendSeriesItem[] {
    const rawSeries = model.sciChartSurface.renderableSeries as unknown as ChronicleRenderableSeriesCollectionLike;
    const seriesList = rawSeries.asArray ? rawSeries.asArray() : (rawSeries.items ?? []);
    return seriesList
        .map((entry) => entry as ChronicleLegendRenderableSeriesLike)
        .filter((entry) => (entry.seriesName ?? '').trim().length > 0)
        .map((entry) => ({
            name: (entry.seriesName ?? '').trim(),
            visible: entry.isVisible ?? true,
            stroke: (entry.stroke && entry.stroke !== '#00000000' ? entry.stroke : entry.fill) ?? '#94a3b8',
            dashed: Array.isArray(entry.strokeDashArray) && entry.strokeDashArray.length > 0,
            swatchKind: chronicleTooltipSwatchKind((entry.seriesName ?? '').trim())
        }));
}

export function setChronicleSeriesVisibility(model: ChronicleChartModel, seriesName: string, isVisible: boolean): void {
    const rawSeries = model.sciChartSurface.renderableSeries as unknown as ChronicleRenderableSeriesCollectionLike;
    const seriesList = rawSeries.asArray ? rawSeries.asArray() : (rawSeries.items ?? []);
    for (const entry of seriesList) {
        const series = entry as ChronicleVisibilityToggleSeriesLike;
        if ((series.seriesName ?? '').trim() === seriesName) {
            series.isVisible = isVisible;
            break;
        }
    }
}
