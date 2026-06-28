import type {
    DcaStrategyPathChartModel,
    DcaStrategyPathLegendRenderableSeriesLike,
    DcaStrategyPathRenderableSeriesCollectionLike,
    DcaStrategyPathVisibilityToggleSeriesLike
} from '../data/dca-strategy-path-projection.models';
import {
    dcaStrategyPathLegendSwatchKind,
    dcaStrategyPathSeriesUsesDashedLegendSwatch,
    type DcaStrategyPathLegendSwatchKind
} from '../data/dca-strategy-path-projection-legend.utils';
import { DCA_STRATEGY_PATH_LEGEND_PREFERRED_ORDER, DCA_STRATEGY_PATH_METRIC_COLORS } from '../data/dca-strategy-path-projection-metrics.catalog';
import { DCA_STRATEGY_PATH_SERIES } from '../data/dca-strategy-path-projection-series-names';

export interface DcaStrategyPathLegendSeriesItem {
    name: string;
    visible: boolean;
    stroke: string;
    dashed: boolean;
    swatchKind: DcaStrategyPathLegendSwatchKind;
    bandFillAbove?: string;
    bandFillBelow?: string;
}

const DCA_LEGEND_ORDER_INDEX = new Map<string, number>(DCA_STRATEGY_PATH_LEGEND_PREFERRED_ORDER.map((seriesName, index) => [seriesName, index]));

function sortDcaStrategyPathLegendItems(items: DcaStrategyPathLegendSeriesItem[]): DcaStrategyPathLegendSeriesItem[] {
    return [...items].sort((left, right) => {
        const leftOrder = DCA_LEGEND_ORDER_INDEX.get(left.name) ?? Number.MAX_SAFE_INTEGER;
        const rightOrder = DCA_LEGEND_ORDER_INDEX.get(right.name) ?? Number.MAX_SAFE_INTEGER;
        if (leftOrder !== rightOrder) {
            return leftOrder - rightOrder;
        }
        return left.name.localeCompare(right.name);
    });
}

function resolveLegendStroke(seriesName: string, series: DcaStrategyPathLegendRenderableSeriesLike): string {
    if (seriesName === DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand) {
        return DCA_STRATEGY_PATH_METRIC_COLORS.marketBandLegendWhenEffectiveAbove;
    }
    if (seriesName === DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand) {
        return DCA_STRATEGY_PATH_METRIC_COLORS.pruBandLegendWhenEffectiveAbove;
    }
    return (
        (series.stroke && series.stroke !== DCA_STRATEGY_PATH_METRIC_COLORS.transparent ? series.stroke : series.fill) ??
        DCA_STRATEGY_PATH_METRIC_COLORS.legendFallbackStroke
    );
}

function resolveBandFillColors(seriesName: string): { bandFillAbove?: string; bandFillBelow?: string } {
    if (seriesName === DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand) {
        return {
            bandFillAbove: DCA_STRATEGY_PATH_METRIC_COLORS.marketBandLegendWhenEffectiveAbove,
            bandFillBelow: DCA_STRATEGY_PATH_METRIC_COLORS.marketBandLegendWhenProjectedAbove
        };
    }
    if (seriesName === DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand) {
        return {
            bandFillAbove: DCA_STRATEGY_PATH_METRIC_COLORS.pruBandLegendWhenEffectiveAbove,
            bandFillBelow: DCA_STRATEGY_PATH_METRIC_COLORS.pruBandLegendWhenProjectedAbove
        };
    }
    return {};
}

export function listDcaStrategyPathLegendSeries(model: DcaStrategyPathChartModel): DcaStrategyPathLegendSeriesItem[] {
    const rawSeries = model.sciChartSurface.renderableSeries as unknown as DcaStrategyPathRenderableSeriesCollectionLike;
    const seriesList = rawSeries.asArray ? rawSeries.asArray() : (rawSeries.items ?? []);
    const legendItems: DcaStrategyPathLegendSeriesItem[] = [];
    const seenSeriesNames = new Set<string>();

    for (const entry of seriesList) {
        const series = entry as DcaStrategyPathLegendRenderableSeriesLike;
        const seriesName = (series.seriesName ?? '').trim();
        if (seriesName.length === 0 || seenSeriesNames.has(seriesName)) {
            continue;
        }
        seenSeriesNames.add(seriesName);

        const swatchKind = dcaStrategyPathLegendSwatchKind(seriesName);
        const visible =
            seriesName === DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand
                ? model.marketPriceExecutionBandUserVisible
                : seriesName === DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand
                  ? model.smartVsProjectedEffectiveBandUserVisible
                  : (series.isVisible ?? true);

        legendItems.push({
            name: seriesName,
            visible,
            stroke: resolveLegendStroke(seriesName, series),
            dashed: dcaStrategyPathSeriesUsesDashedLegendSwatch(seriesName, series.strokeDashArray),
            swatchKind,
            ...resolveBandFillColors(seriesName)
        });
    }

    return sortDcaStrategyPathLegendItems(legendItems);
}

export function setDcaStrategyPathSeriesVisibility(model: DcaStrategyPathChartModel, seriesName: string, isVisible: boolean): void {
    const rawSeries = model.sciChartSurface.renderableSeries as unknown as DcaStrategyPathRenderableSeriesCollectionLike;
    const seriesList = rawSeries.asArray ? rawSeries.asArray() : (rawSeries.items ?? []);

    if (seriesName === DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand) {
        model.marketPriceExecutionBandUserVisible = isVisible;
        for (const bundle of model.marketPriceExecutionBandSegmentBundles) {
            bundle.series.isVisible = isVisible;
        }
        return;
    }

    if (seriesName === DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand) {
        model.smartVsProjectedEffectiveBandUserVisible = isVisible;
        for (const bundle of model.smartVsProjectedEffectiveBandSegmentBundles) {
            bundle.series.isVisible = isVisible;
        }
        return;
    }

    for (const entry of seriesList) {
        const series = entry as DcaStrategyPathVisibilityToggleSeriesLike;
        if ((series.seriesName ?? '').trim() === seriesName) {
            series.isVisible = isVisible;
            break;
        }
    }
}
