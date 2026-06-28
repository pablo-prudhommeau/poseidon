import type { DcaStrategyPathLegendSeriesItem } from '../chart/dca-strategy-path-projection-legend.adapter';

export interface DcaStrategyPathMetricGroupToggleState {
    available: boolean;
    checked: boolean;
    mixed: boolean;
}

export function resolveDcaStrategyPathMetricGroupToggleState(
    legendItems: DcaStrategyPathLegendSeriesItem[],
    seriesNames: string[]
): DcaStrategyPathMetricGroupToggleState {
    const groupItems: DcaStrategyPathLegendSeriesItem[] = legendItems.filter((legendItem: DcaStrategyPathLegendSeriesItem) =>
        seriesNames.includes(legendItem.name)
    );
    if (groupItems.length === 0) {
        return {
            available: false,
            checked: false,
            mixed: false
        };
    }

    const visibleCount: number = groupItems.filter((legendItem: DcaStrategyPathLegendSeriesItem) => legendItem.visible).length;
    return {
        available: true,
        checked: visibleCount === groupItems.length,
        mixed: visibleCount > 0 && visibleCount < groupItems.length
    };
}
