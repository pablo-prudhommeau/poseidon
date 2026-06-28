import { DCA_STRATEGY_PATH_SERIES } from './dca-strategy-path-projection-series-names';

export const DCA_STRATEGY_PATH_TIME_AXIS_IDS = {
    strategy: 'xStrategyTime',
    backtestReference: 'xBacktestReferenceTime'
} as const;

export const DCA_STRATEGY_PATH_AXIS_TITLES = {
    strategyTime: 'Strategy window',
    backtestReferenceTime: 'Backtest reference'
} as const;

export const DCA_STRATEGY_PATH_METRIC_COLORS = {
    chartBackground: '#121212',
    transparent: '#00000000',
    majorGridLine: 'rgba(255, 255, 255, 0.1)',
    minorGridLine: 'rgba(255, 255, 255, 0.05)',
    axisTick: '#d4d4d8d9',
    backtestReferenceAxisTick: '#a1a1aa',
    backtestReferenceAxisTitle: '#f472b6',
    strategyTimeAxisTitle: '#a78bfa',
    themeTickText: '#a1a1aa',
    projectedMarketPriceStroke: '#93c5fd',
    projectedBaselineAverageUnitPrice: '#60a5fa',
    projectedSmartAverageUnitPrice: '#2563eb',
    backtestingMarketPriceStroke: '#fda4af',
    backtestingBaselineAverageUnitPrice: '#f472b6',
    backtestingSmartAverageUnitPrice: '#da2665',
    effectiveMarketPrice: '#c4b5fd',
    effectiveSmartAverageUnitPrice: '#7c3aed',
    effectiveBaselineAverageUnitPrice: '#a78bfa',
    marketBandFillWhenProjectedAbove: 'rgba(147, 197, 253, 0.34)',
    marketBandFillWhenEffectiveAbove: 'rgba(167, 139, 250, 0.40)',
    marketBandLegendWhenProjectedAbove: '#93c5fd',
    marketBandLegendWhenEffectiveAbove: '#c4b5fd',
    pruBandFillWhenEffectiveAbove: 'rgba(124, 58, 237, 0.30)',
    pruBandFillWhenProjectedAbove: 'rgba(37, 99, 235, 0.32)',
    pruBandLegendWhenEffectiveAbove: '#7c3aed',
    pruBandLegendWhenProjectedAbove: '#2563eb',
    crosshair: 'rgba(255, 255, 255, 0.28)',
    tooltipContainerBackground: '#121212cc',
    tooltipText: '#fafafa',
    tooltipTextPrimary: '#fafafa',
    tooltipTitle: '#e9d5ff',
    tooltipAxisLabelFill: '#27272a',
    tooltipFallbackStroke: '#a1a1aa',
    tooltipGradientTop: '#1a1a1a',
    tooltipGradientBottom: '#121212',
    tooltipBorder: 'rgba(255, 255, 255, 0.12)',
    legendBackground: '#12121278',
    legendText: '#e4e4e7',
    legendFallbackStroke: '#a1a1aa'
} as const;

export const DCA_STRATEGY_PATH_LEGEND_PREFERRED_ORDER: string[] = [
    DCA_STRATEGY_PATH_SERIES.effectiveMarketPrice,
    DCA_STRATEGY_PATH_SERIES.effectiveSmartAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.effectiveBaselineAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.projectedMarketPrice,
    DCA_STRATEGY_PATH_SERIES.projectedSmartAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.projectedBaselineAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.backtestingMarketPrice,
    DCA_STRATEGY_PATH_SERIES.backtestingSmartAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.backtestingBaselineAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand,
    DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand
];

export const DCA_STRATEGY_PATH_TOOLTIP_PREFERRED_ORDER: string[] = [
    DCA_STRATEGY_PATH_SERIES.effectiveMarketPrice,
    DCA_STRATEGY_PATH_SERIES.effectiveSmartAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.effectiveBaselineAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.projectedMarketPrice,
    DCA_STRATEGY_PATH_SERIES.projectedSmartAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.projectedBaselineAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.backtestingMarketPrice,
    DCA_STRATEGY_PATH_SERIES.backtestingSmartAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.backtestingBaselineAverageUnitPrice,
    DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand,
    DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand
];

export const DCA_STRATEGY_PATH_TOOLTIP_COMPACT_LABEL: Record<string, string> = {
    [DCA_STRATEGY_PATH_SERIES.projectedMarketPrice]: 'Projected market',
    [DCA_STRATEGY_PATH_SERIES.backtestingMarketPrice]: 'Backtesting market',
    [DCA_STRATEGY_PATH_SERIES.effectiveMarketPrice]: 'Effective market',
    [DCA_STRATEGY_PATH_SERIES.projectedSmartAverageUnitPrice]: 'Projected smart PRU',
    [DCA_STRATEGY_PATH_SERIES.projectedBaselineAverageUnitPrice]: 'Projected baseline PRU',
    [DCA_STRATEGY_PATH_SERIES.backtestingSmartAverageUnitPrice]: 'Backtesting smart PRU',
    [DCA_STRATEGY_PATH_SERIES.backtestingBaselineAverageUnitPrice]: 'Backtesting baseline PRU',
    [DCA_STRATEGY_PATH_SERIES.effectiveSmartAverageUnitPrice]: 'Effective smart PRU',
    [DCA_STRATEGY_PATH_SERIES.effectiveBaselineAverageUnitPrice]: 'Effective baseline PRU'
};
