import { DCA_STRATEGY_PATH_SERIES } from './dca-strategy-path-projection-series-names';

export const DCA_STRATEGY_PATH_BAND_METRIC_SERIES_NAMES: string[] = [
    DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand,
    DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand
];

export const DCA_STRATEGY_PATH_EFFECTIVE_METRIC_SERIES_NAMES: string[] = [
    DCA_STRATEGY_PATH_SERIES.effectiveMarketPrice,
    DCA_STRATEGY_PATH_SERIES.effectiveSmartAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.effectiveBaselineAverageUnitPrice
];

export const DCA_STRATEGY_PATH_BACKTESTING_METRIC_SERIES_NAMES: string[] = [
    DCA_STRATEGY_PATH_SERIES.backtestingMarketPrice,
    DCA_STRATEGY_PATH_SERIES.backtestingSmartAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.backtestingBaselineAverageUnitPrice
];

export const DCA_STRATEGY_PATH_PROJECTED_METRIC_SERIES_NAMES: string[] = [
    DCA_STRATEGY_PATH_SERIES.projectedMarketPrice,
    DCA_STRATEGY_PATH_SERIES.projectedBaselineAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.projectedSmartAverageUnitPrice
];

export function resolveDcaStrategyPathSeriesDefaultVisible(seriesName: string): boolean {
    if (DCA_STRATEGY_PATH_BAND_METRIC_SERIES_NAMES.includes(seriesName)) {
        return false;
    }

    return (
        DCA_STRATEGY_PATH_EFFECTIVE_METRIC_SERIES_NAMES.includes(seriesName) ||
        DCA_STRATEGY_PATH_BACKTESTING_METRIC_SERIES_NAMES.includes(seriesName) ||
        DCA_STRATEGY_PATH_PROJECTED_METRIC_SERIES_NAMES.includes(seriesName)
    );
}
