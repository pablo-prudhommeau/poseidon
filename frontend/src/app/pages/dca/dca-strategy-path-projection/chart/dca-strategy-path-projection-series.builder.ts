import type { LabelProvider } from 'scichart';
import { DcaStrategyPayload } from '../../../../core/models';
import { buildDcaStrategyPathCursorTooltipSvg } from './dca-strategy-path-projection-tooltip.formatter';
import {
    buildMarketPriceExecutionBandSegmentBundles,
    buildSmartVsProjectedEffectiveBandSegmentBundles,
    synchronizeMarketPriceExecutionBandSegmentBundles,
    synchronizeSmartVsProjectedEffectiveBandSegmentBundles
} from './dca-strategy-path-projection-band.utils';
import {
    DcaStrategyPathAdjustTooltipPositionHost,
    DcaStrategyPathChartModel,
    DcaStrategyPathChartSeriesBundle,
    DcaStrategyPathSciChartModule
} from '../data/dca-strategy-path-projection.models';
import {
    DCA_STRATEGY_PATH_AXIS_TITLES,
    DCA_STRATEGY_PATH_METRIC_COLORS,
    DCA_STRATEGY_PATH_TIME_AXIS_IDS
} from '../data/dca-strategy-path-projection-metrics.catalog';
import { DCA_STRATEGY_PATH_SERIES } from '../data/dca-strategy-path-projection-series-names';
import {
    resolveDcaStrategyPathSeriesDefaultVisible
} from '../data/dca-strategy-path-projection-metric-groups';
import {
    extractChartPointCoordinates,
    resolveBacktestReferenceVisibleRangeMilliseconds,
    resolveStrategyPathVisibleRangeMilliseconds
} from '../data/dca-strategy-path-projection-series-data.utils';
import { DcaStrategyPathProjectionSciChartLoaderService } from '../services/dca-strategy-path-projection-scichart-loader.service';

function formatAxisTimestampLabel(timestampMilliseconds: number | undefined): string {
    if (timestampMilliseconds === undefined || !Number.isFinite(timestampMilliseconds)) {
        return '';
    }
    return new Date(timestampMilliseconds).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric'
    });
}

function formatBacktestReferenceAxisTimestampLabel(timestampMilliseconds: number | undefined): string {
    if (timestampMilliseconds === undefined || !Number.isFinite(timestampMilliseconds)) {
        return '';
    }
    return new Date(timestampMilliseconds).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
    });
}

function formatAxisCursorTimestampLabel(timestampMilliseconds: number | undefined): string {
    if (timestampMilliseconds === undefined || !Number.isFinite(timestampMilliseconds)) {
        return '';
    }
    return new Date(timestampMilliseconds).toLocaleString(undefined, {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatPriceLabel(priceValue: number | undefined): string {
    if (priceValue === undefined || !Number.isFinite(priceValue)) {
        return '';
    }
    return `$${priceValue.toFixed(0)}`;
}

function appendSeriesData(
    dataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>,
    chartPoints: { timestampMilliseconds: number; value: number }[]
): void {
    const coordinates = extractChartPointCoordinates(chartPoints);
    dataSeries.clear();
    if (coordinates.xValues.length > 0) {
        dataSeries.appendRange(coordinates.xValues, coordinates.yValues);
    }
}

function createSplineMetricLine(
    sciChartModule: DcaStrategyPathSciChartModule,
    wasmContext: InstanceType<DcaStrategyPathSciChartModule['SciChartSurface']>['webAssemblyContext2D'],
    chartPoints: { timestampMilliseconds: number; value: number }[],
    dataSeriesName: string,
    stroke: string,
    glow: InstanceType<DcaStrategyPathSciChartModule['GlowEffect']>,
    strokeThickness: number,
    xAxisId: string,
    strokeDashArray?: number[],
    isVisible = true
): {
    dataSeries: InstanceType<DcaStrategyPathSciChartModule['XyDataSeries']>;
    series: InstanceType<DcaStrategyPathSciChartModule['SplineLineRenderableSeries']>;
} {
    const coordinates = extractChartPointCoordinates(chartPoints);
    const dataSeries = new sciChartModule.XyDataSeries(wasmContext, {
        dataSeriesName,
        containsNaN: false,
        isSorted: true
    });
    if (coordinates.xValues.length > 0) {
        dataSeries.appendRange(coordinates.xValues, coordinates.yValues);
    }

    const series = new sciChartModule.SplineLineRenderableSeries(wasmContext, {
        dataSeries,
        yAxisId: 'yPrice',
        xAxisId,
        seriesName: dataSeriesName,
        stroke,
        strokeThickness,
        strokeDashArray,
        opacity: 0.95,
        effect: glow,
        isVisible
    });

    return { dataSeries, series };
}

export class DcaStrategyPathProjectionSeriesBuilder {
    async buildChartModel(
        host: HTMLDivElement,
        strategy: DcaStrategyPayload,
        seriesBundle: DcaStrategyPathChartSeriesBundle,
        sciChartLoader: DcaStrategyPathProjectionSciChartLoaderService
    ): Promise<DcaStrategyPathChartModel> {
        const sciChartModule: DcaStrategyPathSciChartModule = await sciChartLoader.loadModule();
        const {
            CursorModifier,
            DateTimeNumericAxis,
            EAutoRange,
            EAxisAlignment,
            EDatePrecision,
            GlowEffect,
            NumberRange,
            NumericAxis,
            SciChartSurface,
            Thickness,
            ZoomExtentsModifier
        } = sciChartModule;

        const customTheme = new sciChartModule.SciChartJSDarkTheme();
        customTheme.sciChartBackground = DCA_STRATEGY_PATH_METRIC_COLORS.chartBackground;
        customTheme.axisBandsFill = DCA_STRATEGY_PATH_METRIC_COLORS.transparent;
        customTheme.gridBackgroundBrush = DCA_STRATEGY_PATH_METRIC_COLORS.chartBackground;
        customTheme.majorGridLineBrush = DCA_STRATEGY_PATH_METRIC_COLORS.majorGridLine;
        customTheme.minorGridLineBrush = DCA_STRATEGY_PATH_METRIC_COLORS.minorGridLine;
        customTheme.tickTextBrush = DCA_STRATEGY_PATH_METRIC_COLORS.themeTickText;

        const { sciChartSurface, wasmContext } = await SciChartSurface.create(host, {
            theme: customTheme,
            background: DCA_STRATEGY_PATH_METRIC_COLORS.chartBackground,
            padding: new Thickness(28, 8, 28, 8)
        });

        const strategyVisibleRange = resolveStrategyPathVisibleRangeMilliseconds(strategy);
        const backtestReferenceVisibleRange = resolveBacktestReferenceVisibleRangeMilliseconds(strategy);

        const strategyTimeAxis = new DateTimeNumericAxis(wasmContext, {
            id: DCA_STRATEGY_PATH_TIME_AXIS_IDS.strategy,
            axisAlignment: EAxisAlignment.Top,
            autoRange: EAutoRange.Never,
            visibleRange: new NumberRange(strategyVisibleRange.minimumTimestampMilliseconds, strategyVisibleRange.maximumTimestampMilliseconds),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 12,
            datePrecision: EDatePrecision.Milliseconds,
            showYearOnWiderDate: true,
            axisTitle: DCA_STRATEGY_PATH_AXIS_TITLES.strategyTime,
            axisTitleStyle: { fontSize: 10, color: DCA_STRATEGY_PATH_METRIC_COLORS.strategyTimeAxisTitle },
            labelStyle: { fontSize: 11, color: DCA_STRATEGY_PATH_METRIC_COLORS.axisTick }
        });
        const strategyAxisLabelProvider = strategyTimeAxis.labelProvider as LabelProvider;
        strategyAxisLabelProvider.formatLabel = formatAxisTimestampLabel;
        strategyAxisLabelProvider.formatCursorLabel = formatAxisCursorTimestampLabel;

        const backtestReferenceTimeAxis = new DateTimeNumericAxis(wasmContext, {
            id: DCA_STRATEGY_PATH_TIME_AXIS_IDS.backtestReference,
            axisAlignment: EAxisAlignment.Bottom,
            autoRange: EAutoRange.Never,
            visibleRange: new NumberRange(
                backtestReferenceVisibleRange.minimumTimestampMilliseconds,
                backtestReferenceVisibleRange.maximumTimestampMilliseconds
            ),
            drawMajorBands: false,
            drawMajorGridLines: true,
            drawMinorGridLines: true,
            maxAutoTicks: 10,
            datePrecision: EDatePrecision.Milliseconds,
            showYearOnWiderDate: true,
            axisTitle: DCA_STRATEGY_PATH_AXIS_TITLES.backtestReferenceTime,
            axisTitleStyle: { fontSize: 10, color: DCA_STRATEGY_PATH_METRIC_COLORS.backtestReferenceAxisTitle },
            labelStyle: { fontSize: 10, color: DCA_STRATEGY_PATH_METRIC_COLORS.backtestReferenceAxisTick }
        });
        const backtestReferenceAxisLabelProvider = backtestReferenceTimeAxis.labelProvider as LabelProvider;
        backtestReferenceAxisLabelProvider.formatLabel = formatBacktestReferenceAxisTimestampLabel;
        backtestReferenceAxisLabelProvider.formatCursorLabel = formatAxisCursorTimestampLabel;

        const yAxis = new NumericAxis(wasmContext, {
            id: 'yPrice',
            axisAlignment: EAxisAlignment.Left,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0.08, 0.08),
            drawMajorBands: false,
            drawMajorGridLines: true,
            drawMinorGridLines: true,
            maxAutoTicks: 8,
            labelStyle: { fontSize: 11, color: DCA_STRATEGY_PATH_METRIC_COLORS.axisTick }
        });
        yAxis.labelProvider.formatLabel = formatPriceLabel;
        yAxis.labelProvider.formatCursorLabel = formatPriceLabel;

        sciChartSurface.xAxes.add(strategyTimeAxis, backtestReferenceTimeAxis);
        sciChartSurface.yAxes.add(yAxis);

        const strategyTimeAxisId: string = DCA_STRATEGY_PATH_TIME_AXIS_IDS.strategy;
        const backtestReferenceTimeAxisId: string = DCA_STRATEGY_PATH_TIME_AXIS_IDS.backtestReference;
        const marketPriceExecutionBandDefaultVisible = resolveDcaStrategyPathSeriesDefaultVisible(
            DCA_STRATEGY_PATH_SERIES.marketPriceExecutionBand
        );
        const smartVsProjectedEffectiveBandDefaultVisible = resolveDcaStrategyPathSeriesDefaultVisible(
            DCA_STRATEGY_PATH_SERIES.smartVsProjectedEffectiveBand
        );

        const marketPriceExecutionBandSegmentBundles = buildMarketPriceExecutionBandSegmentBundles(
            sciChartModule,
            wasmContext,
            seriesBundle.marketPriceExecutionBandSegments,
            marketPriceExecutionBandDefaultVisible
        );
        for (const bundle of marketPriceExecutionBandSegmentBundles) {
            sciChartSurface.renderableSeries.add(bundle.series);
        }

        const smartVsProjectedEffectiveBandSegmentBundles = buildSmartVsProjectedEffectiveBandSegmentBundles(
            sciChartModule,
            wasmContext,
            seriesBundle.smartVsProjectedEffectiveBandSegments,
            smartVsProjectedEffectiveBandDefaultVisible
        );
        for (const bundle of smartVsProjectedEffectiveBandSegmentBundles) {
            sciChartSurface.renderableSeries.add(bundle.series);
        }

        const projectedMarket = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.projectedMarketPrice,
            DCA_STRATEGY_PATH_SERIES.projectedMarketPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.projectedMarketPriceStroke,
            new GlowEffect(wasmContext, { intensity: 0.35, range: 1.8 }),
            2.5,
            strategyTimeAxisId,
            undefined,
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.projectedMarketPrice)
        );
        sciChartSurface.renderableSeries.add(projectedMarket.series);

        const projectedBaseline = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.projectedBaselineAverageUnitPrice,
            DCA_STRATEGY_PATH_SERIES.projectedBaselineAverageUnitPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.projectedBaselineAverageUnitPrice,
            new GlowEffect(wasmContext, { intensity: 0, range: 0 }),
            2,
            strategyTimeAxisId,
            [6, 4],
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.projectedBaselineAverageUnitPrice)
        );
        sciChartSurface.renderableSeries.add(projectedBaseline.series);

        const projectedSmart = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.projectedSmartAverageUnitPrice,
            DCA_STRATEGY_PATH_SERIES.projectedSmartAverageUnitPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.projectedSmartAverageUnitPrice,
            new GlowEffect(wasmContext, { intensity: 0.5, range: 2.2 }),
            2.5,
            strategyTimeAxisId,
            undefined,
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.projectedSmartAverageUnitPrice)
        );
        sciChartSurface.renderableSeries.add(projectedSmart.series);

        const backtestingMarket = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.backtestingMarketPrice,
            DCA_STRATEGY_PATH_SERIES.backtestingMarketPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.backtestingMarketPriceStroke,
            new GlowEffect(wasmContext, { intensity: 0.15, range: 1.2 }),
            2,
            backtestReferenceTimeAxisId,
            undefined,
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.backtestingMarketPrice)
        );
        sciChartSurface.renderableSeries.add(backtestingMarket.series);

        const backtestingBaseline = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.backtestingBaselineAverageUnitPrice,
            DCA_STRATEGY_PATH_SERIES.backtestingBaselineAverageUnitPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.backtestingBaselineAverageUnitPrice,
            new GlowEffect(wasmContext, { intensity: 0, range: 0 }),
            1.75,
            backtestReferenceTimeAxisId,
            [6, 4],
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.backtestingBaselineAverageUnitPrice)
        );
        sciChartSurface.renderableSeries.add(backtestingBaseline.series);

        const backtestingSmart = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.backtestingSmartAverageUnitPrice,
            DCA_STRATEGY_PATH_SERIES.backtestingSmartAverageUnitPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.backtestingSmartAverageUnitPrice,
            new GlowEffect(wasmContext, { intensity: 0.2, range: 1.4 }),
            2,
            backtestReferenceTimeAxisId,
            undefined,
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.backtestingSmartAverageUnitPrice)
        );
        sciChartSurface.renderableSeries.add(backtestingSmart.series);

        const effectiveBaseline = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.effectiveBaselineAverageUnitPrice,
            DCA_STRATEGY_PATH_SERIES.effectiveBaselineAverageUnitPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.effectiveBaselineAverageUnitPrice,
            new GlowEffect(wasmContext, { intensity: 0, range: 0 }),
            2,
            strategyTimeAxisId,
            [6, 4],
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.effectiveBaselineAverageUnitPrice)
        );
        sciChartSurface.renderableSeries.add(effectiveBaseline.series);

        const effectiveMarket = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.effectiveMarketPrice,
            DCA_STRATEGY_PATH_SERIES.effectiveMarketPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.effectiveMarketPrice,
            new GlowEffect(wasmContext, { intensity: 0.48, range: 2.1 }),
            2.5,
            strategyTimeAxisId,
            undefined,
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.effectiveMarketPrice)
        );
        sciChartSurface.renderableSeries.add(effectiveMarket.series);

        const effectiveSmart = createSplineMetricLine(
            sciChartModule,
            wasmContext,
            seriesBundle.effectiveSmartAverageUnitPrice,
            DCA_STRATEGY_PATH_SERIES.effectiveSmartAverageUnitPrice,
            DCA_STRATEGY_PATH_METRIC_COLORS.effectiveSmartAverageUnitPrice,
            new GlowEffect(wasmContext, { intensity: 0.52, range: 2.4 }),
            3,
            strategyTimeAxisId,
            undefined,
            resolveDcaStrategyPathSeriesDefaultVisible(DCA_STRATEGY_PATH_SERIES.effectiveSmartAverageUnitPrice)
        );
        sciChartSurface.renderableSeries.add(effectiveSmart.series);

        const tooltipHost = sciChartModule as unknown as DcaStrategyPathAdjustTooltipPositionHost;
        sciChartSurface.chartModifiers.add(
            new CursorModifier({
                crosshairStroke: DCA_STRATEGY_PATH_METRIC_COLORS.crosshair,
                crosshairStrokeThickness: 1,
                showTooltip: true,
                showAxisLabels: true,
                tooltipContainerBackground: DCA_STRATEGY_PATH_METRIC_COLORS.tooltipContainerBackground,
                tooltipTextStroke: DCA_STRATEGY_PATH_METRIC_COLORS.tooltipText,
                axisLabelFill: DCA_STRATEGY_PATH_METRIC_COLORS.tooltipAxisLabelFill,
                tooltipSvgTemplate: (seriesInfos, svgAnnotation) => buildDcaStrategyPathCursorTooltipSvg(tooltipHost, seriesInfos as never, svgAnnotation)
            }),
            new ZoomExtentsModifier()
        );

        sciChartSurface.zoomExtents();

        return {
            sciChartSurface,
            wasmContext,
            strategyTimeAxis,
            backtestReferenceTimeAxis,
            projectedMarketPriceLineSeries: projectedMarket.series,
            projectedMarketPriceDataSeries: projectedMarket.dataSeries,
            projectedBaselineAverageUnitPriceDataSeries: projectedBaseline.dataSeries,
            projectedSmartAverageUnitPriceDataSeries: projectedSmart.dataSeries,
            backtestingMarketPriceDataSeries: backtestingMarket.dataSeries,
            backtestingBaselineAverageUnitPriceDataSeries: backtestingBaseline.dataSeries,
            backtestingSmartAverageUnitPriceDataSeries: backtestingSmart.dataSeries,
            effectiveMarketPriceDataSeries: effectiveMarket.dataSeries,
            effectiveSmartAverageUnitPriceDataSeries: effectiveSmart.dataSeries,
            effectiveBaselineAverageUnitPriceDataSeries: effectiveBaseline.dataSeries,
            marketPriceExecutionBandSegmentBundles,
            smartVsProjectedEffectiveBandSegmentBundles,
            marketPriceExecutionBandUserVisible: marketPriceExecutionBandDefaultVisible,
            smartVsProjectedEffectiveBandUserVisible: smartVsProjectedEffectiveBandDefaultVisible
        };
    }

    synchronizeChartModel(
        chartModel: DcaStrategyPathChartModel,
        seriesBundle: DcaStrategyPathChartSeriesBundle,
        sciChartModule: DcaStrategyPathSciChartModule
    ): void {
        const { NumberRange } = sciChartModule;

        if (seriesBundle.projectedMarketPrice.length > 0) {
            chartModel.strategyTimeAxis.visibleRange = new NumberRange(
                seriesBundle.projectedMarketPrice[0].timestampMilliseconds,
                seriesBundle.projectedMarketPrice[seriesBundle.projectedMarketPrice.length - 1].timestampMilliseconds
            );
        }

        if (seriesBundle.backtestingMarketPrice.length > 0) {
            chartModel.backtestReferenceTimeAxis.visibleRange = new NumberRange(
                seriesBundle.backtestingMarketPrice[0].timestampMilliseconds,
                seriesBundle.backtestingMarketPrice[seriesBundle.backtestingMarketPrice.length - 1].timestampMilliseconds
            );
        }

        appendSeriesData(chartModel.projectedMarketPriceDataSeries, seriesBundle.projectedMarketPrice);
        appendSeriesData(chartModel.projectedBaselineAverageUnitPriceDataSeries, seriesBundle.projectedBaselineAverageUnitPrice);
        appendSeriesData(chartModel.projectedSmartAverageUnitPriceDataSeries, seriesBundle.projectedSmartAverageUnitPrice);
        appendSeriesData(chartModel.backtestingMarketPriceDataSeries, seriesBundle.backtestingMarketPrice);
        appendSeriesData(chartModel.backtestingBaselineAverageUnitPriceDataSeries, seriesBundle.backtestingBaselineAverageUnitPrice);
        appendSeriesData(chartModel.backtestingSmartAverageUnitPriceDataSeries, seriesBundle.backtestingSmartAverageUnitPrice);
        appendSeriesData(chartModel.effectiveMarketPriceDataSeries, seriesBundle.effectiveMarketPrice);
        appendSeriesData(chartModel.effectiveSmartAverageUnitPriceDataSeries, seriesBundle.effectiveSmartAverageUnitPrice);
        appendSeriesData(chartModel.effectiveBaselineAverageUnitPriceDataSeries, seriesBundle.effectiveBaselineAverageUnitPrice);

        chartModel.marketPriceExecutionBandSegmentBundles = synchronizeMarketPriceExecutionBandSegmentBundles(
            chartModel,
            sciChartModule,
            chartModel.wasmContext,
            seriesBundle.marketPriceExecutionBandSegments
        );
        chartModel.smartVsProjectedEffectiveBandSegmentBundles = synchronizeSmartVsProjectedEffectiveBandSegmentBundles(
            chartModel,
            sciChartModule,
            chartModel.wasmContext,
            seriesBundle.smartVsProjectedEffectiveBandSegments
        );

        chartModel.sciChartSurface.zoomExtents();
        chartModel.sciChartSurface.invalidateElement();
    }
}
