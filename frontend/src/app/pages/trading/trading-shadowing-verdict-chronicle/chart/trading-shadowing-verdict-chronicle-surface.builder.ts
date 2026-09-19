import type { IRenderableSeries, LabelProvider, SciChartOverview, SciChartSurface } from 'scichart';
import type { ChronicleBucketMeta, ChronicleChartModel } from '../data/trading-shadowing-verdict-chronicle.models';
import {
    buildChronicleArraysFromBucket,
    computeChronicleViewportWidthMilliseconds,
    formatChronicleAxisLocalDateTimeMilliseconds,
    formatChronicleAxisTickLabelMilliseconds,
    parseIsoTimestampToEpochMilliseconds,
    type ChronicleBucketLabel
} from '../data/trading-shadowing-verdict-chronicle-arrays.utils';
import { CHRONICLE_AXIS_TITLES, CHRONICLE_DEFAULT_VISIBLE_SERIES, CHRONICLE_METRIC_COLORS } from '../data/trading-shadowing-verdict-chronicle-metrics.catalog';
import { CHRONICLE_SERIES } from '../data/trading-shadowing-verdict-chronicle-series-names';
import type { TradingShadowingVerdictChronicleSciChartLoaderService } from '../services/trading-shadowing-verdict-chronicle-scichart-loader.service';
import { patchChronicleSciChartAnnotationDetach } from './trading-shadowing-verdict-chronicle-annotation-detach.utils';
import {
    assignChronicleSciChartHostElementIds,
    configureChronicleOverviewSurface,
    ensureChronicleOverviewWalletValueDataSeries,
    transformChronicleOverviewRenderableSeries
} from './trading-shadowing-verdict-chronicle-overview.utils';
import { buildChronicleSeriesBundle } from './trading-shadowing-verdict-chronicle-series.builder';

export class TradingShadowingVerdictChronicleSurfaceBuilder {
    async buildFullChartSurface(
        host: HTMLDivElement,
        overviewHost: HTMLDivElement,
        meta: ChronicleBucketMeta,
        sciChartLoader: TradingShadowingVerdictChronicleSciChartLoaderService,
        smaWindowBuckets: number
    ): Promise<ChronicleChartModel> {
        const sci = await sciChartLoader.loadModule();
        assignChronicleSciChartHostElementIds(host, overviewHost);
        const { DateTimeNumericAxis, EAutoRange, EAxisAlignment, EDatePrecision, NumberRange, NumericAxis, SciChartJSDarkTheme, SciChartSurface, Thickness } =
            sci;

        const customTheme = new SciChartJSDarkTheme();
        customTheme.sciChartBackground = CHRONICLE_METRIC_COLORS.chartBackground;
        customTheme.axisBandsFill = CHRONICLE_METRIC_COLORS.transparent;
        customTheme.gridBackgroundBrush = CHRONICLE_METRIC_COLORS.chartBackground;
        customTheme.majorGridLineBrush = CHRONICLE_METRIC_COLORS.majorGridLine;
        customTheme.minorGridLineBrush = CHRONICLE_METRIC_COLORS.minorGridLine;
        customTheme.axisBorder = CHRONICLE_METRIC_COLORS.axisBorder;
        customTheme.tickTextBrush = CHRONICLE_METRIC_COLORS.themeTickText;
        customTheme.legendBackgroundBrush = CHRONICLE_METRIC_COLORS.themeLegendBackground;

        const { sciChartSurface, wasmContext } = await SciChartSurface.create(host, {
            theme: customTheme,
            background: CHRONICLE_METRIC_COLORS.chartBackground,
            padding: new Thickness(6, 6, 6, 6)
        });
        patchChronicleSciChartAnnotationDetach(sciChartSurface);

        const chronicleArrays = buildChronicleArraysFromBucket(meta, smaWindowBuckets);
        const viewportWidthMilliseconds = computeChronicleViewportWidthMilliseconds(
            chronicleArrays,
            meta.bucket.bucket_label as ChronicleBucketLabel,
            meta.bucket
        );
        const initialRightEdgeMilliseconds = parseIsoTimestampToEpochMilliseconds(meta.response.as_of_iso) ?? Date.now();

        const xAxis = new DateTimeNumericAxis(wasmContext, {
            id: 'xTime',
            axisAlignment: EAxisAlignment.Bottom,
            autoRange: EAutoRange.Never,
            visibleRange: new NumberRange(initialRightEdgeMilliseconds - viewportWidthMilliseconds, initialRightEdgeMilliseconds),
            drawMajorBands: false,
            drawMajorGridLines: true,
            drawMinorGridLines: true,
            maxAutoTicks: 14,
            minTicks: 10,
            minorsPerMajor: 4,
            datePrecision: EDatePrecision.Milliseconds,
            showYearOnWiderDate: true,
            labelStyle: { fontSize: 11, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        const axisLabelProvider = xAxis.labelProvider as LabelProvider;
        axisLabelProvider.formatLabel = formatChronicleAxisTickLabelMilliseconds;
        axisLabelProvider.formatCursorLabel = formatChronicleAxisLocalDateTimeMilliseconds;

        const yPercentage = new NumericAxis(wasmContext, {
            id: 'yPct',
            axisAlignment: EAxisAlignment.Left,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0.135, 0.09),
            drawMajorBands: false,
            drawMajorGridLines: true,
            drawMinorGridLines: true,
            maxAutoTicks: 12,
            minorsPerMajor: 4,
            axisTitle: CHRONICLE_AXIS_TITLES.percentage,
            axisTitleStyle: { fontSize: 11, color: CHRONICLE_METRIC_COLORS.percentageAxisTitle },
            labelStyle: { fontSize: 11, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        const yVolume = new NumericAxis(wasmContext, {
            id: 'yVol',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 10,
            minorsPerMajor: 4,
            axisTitle: CHRONICLE_AXIS_TITLES.volume,
            axisTitleStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.cortexPrediction },
            labelStyle: { fontSize: 11, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        const yExpectedValueAxis = new NumericAxis(wasmContext, {
            id: 'yUsd',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 10,
            minorsPerMajor: 4,
            axisTitle: CHRONICLE_AXIS_TITLES.expectedValue,
            axisTitleStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.expectedValue },
            labelStyle: { fontSize: 11, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        const yPortfolioWalletValueAxis = new NumericAxis(wasmContext, {
            id: 'yWalletValue',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 10,
            minorsPerMajor: 4,
            axisTitle: CHRONICLE_AXIS_TITLES.portfolioWalletValue,
            axisTitleStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.portfolioWalletValue },
            labelStyle: { fontSize: 11, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        const yProfitFactorAxis = new NumericAxis(wasmContext, {
            id: 'yPf',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 10,
            minorsPerMajor: 4,
            axisTitle: CHRONICLE_AXIS_TITLES.profitFactor,
            axisTitleStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.profitFactor },
            labelStyle: { fontSize: 11, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        const yTradesPerHourAxis = new NumericAxis(wasmContext, {
            id: 'yVel',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 10,
            minorsPerMajor: 4,
            axisTitle: CHRONICLE_AXIS_TITLES.tradesPerHour,
            axisTitleStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.tradesPerHour },
            labelStyle: { fontSize: 11, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        const yRegimeEvAxis = new NumericAxis(wasmContext, {
            id: 'yRegimeEv',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 7,
            minorsPerMajor: 4,
            axisTitle: CHRONICLE_AXIS_TITLES.regimeExpectedValue,
            axisTitleStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.regimeExpectedValue },
            labelStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        const yRegimePfAxis = new NumericAxis(wasmContext, {
            id: 'yRegimePf',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 7,
            minorsPerMajor: 4,
            axisTitle: CHRONICLE_AXIS_TITLES.regimeProfitFactor,
            axisTitleStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.regimeProfitFactor },
            labelStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.axisTick }
        });

        sciChartSurface.xAxes.add(xAxis);
        sciChartSurface.yAxes.add(
            yPercentage,
            yVolume,
            yExpectedValueAxis,
            yPortfolioWalletValueAxis,
            yProfitFactorAxis,
            yTradesPerHourAxis,
            yRegimeEvAxis,
            yRegimePfAxis
        );

        const seriesBundle = buildChronicleSeriesBundle(sci, wasmContext, sciChartSurface, chronicleArrays, meta);
        const sciChartOverview: SciChartOverview = await sci.SciChartOverview.create(sciChartSurface, overviewHost, {
            theme: customTheme,
            background: CHRONICLE_METRIC_COLORS.chartBackground,
            padding: new Thickness(0, 6, 4, 6),
            mainAxisId: 'xTime',
            secondaryAxisId: 'yWalletValue',
            overviewXAxisOptions: {
                isVisible: true,
                autoRange: EAutoRange.Always,
                drawMajorBands: false,
                drawMajorGridLines: true,
                drawMinorGridLines: false,
                maxAutoTicks: 6,
                minorsPerMajor: 1,
                labelStyle: { fontSize: 10, color: CHRONICLE_METRIC_COLORS.axisTick }
            },
            overviewYAxisOptions: {
                isVisible: true,
                isInnerAxis: true,
                autoRange: EAutoRange.Always,
                growBy: new NumberRange(0.08, 0.12),
                axisTitle: '',
                drawLabels: false,
                drawMajorBands: false,
                drawMajorGridLines: true,
                drawMinorGridLines: false,
                drawMajorTickLines: false,
                drawMinorTickLines: false,
                maxAutoTicks: 4,
                minorsPerMajor: 1
            },
            transformRenderableSeries: (parentSeries: IRenderableSeries, overviewSurface?: SciChartSurface): IRenderableSeries | undefined => {
                return transformChronicleOverviewRenderableSeries(sci, parentSeries, overviewSurface);
            }
        });
        patchChronicleSciChartAnnotationDetach(sciChartOverview.overviewSciChartSurface);
        configureChronicleOverviewSurface(sciChartOverview);
        const overviewWalletValueDataSeries: ChronicleChartModel['overviewWalletValueDataSeries'] = ensureChronicleOverviewWalletValueDataSeries(
            sci,
            sciChartSurface,
            sciChartOverview
        );

        return {
            sciChartSurface,
            sciChartOverview,
            overviewWalletValueDataSeries,
            wasmContext,
            sci,
            xAxis,
            viewportWidthMilliseconds,
            volumeColumnDataSeries: seriesBundle.volumeColumnDataSeries,
            volumeColumnRenderableSeries: seriesBundle.volumeColumnRenderableSeries,
            yVolumeAxis: yVolume,
            yExpectedValueAxis,
            yPortfolioWalletValueAxis,
            yProfitFactorAxis,
            yTradesPerHourAxis,
            yRegimeEvAxis,
            yRegimePfAxis,
            goldenZoneExpectedValueBandDataSeries: seriesBundle.goldenZoneExpectedValueBandDataSeries,
            goldenZoneProfitFactorBandDataSeries: seriesBundle.goldenZoneProfitFactorBandDataSeries,
            goldenZoneExpectedValueBandSeries: seriesBundle.goldenZoneExpectedValueBandSeries,
            goldenZoneProfitFactorBandSeries: seriesBundle.goldenZoneProfitFactorBandSeries,
            regimeEvGateSubmergedBandSegmentBundles: seriesBundle.regimeEvGateSubmergedBandSegmentBundles,
            regimePfGateSubmergedBandSegmentBundles: seriesBundle.regimePfGateSubmergedBandSegmentBundles,
            metricLineRenderableSeries: seriesBundle.metricLineRenderableSeries,
            movingAverageLineRenderableSeries: seriesBundle.movingAverageLineRenderableSeries,
            profitableVerdictXyDataSeries: seriesBundle.profitableVerdictXyDataSeries,
            lossVerdictXyDataSeries: seriesBundle.lossVerdictXyDataSeries,
            profitableSellXyDataSeries: seriesBundle.profitableSellXyDataSeries,
            lossSellXyDataSeries: seriesBundle.lossSellXyDataSeries,
            profitableSellPathSegmentBundles: seriesBundle.profitableSellPathSegmentBundles,
            lossSellPathSegmentBundles: seriesBundle.lossSellPathSegmentBundles,
            sellPathTokenIconAnnotations: [],
            cursorModifier: seriesBundle.cursorModifier,
            cortexCalibrationBandSegmentBundles: seriesBundle.cortexCalibrationBandSegmentBundles,
            cortexCalibrationBandUserVisible: CHRONICLE_DEFAULT_VISIBLE_SERIES.includes(CHRONICLE_SERIES.cortexCalibrationBand),
            cortexModelRolloutUserVisible: CHRONICLE_DEFAULT_VISIBLE_SERIES.includes(CHRONICLE_SERIES.cortexModelRolloutMarker),
            evGateThresholdUserVisible: CHRONICLE_DEFAULT_VISIBLE_SERIES.includes(CHRONICLE_SERIES.evGateThreshold),
            pfGateThresholdUserVisible: CHRONICLE_DEFAULT_VISIBLE_SERIES.includes(CHRONICLE_SERIES.pfGateThreshold),
            goldenZoneExpectedValueAnnotation: seriesBundle.goldenZoneExpectedValueAnnotation,
            goldenZoneProfitFactorAnnotation: seriesBundle.goldenZoneProfitFactorAnnotation,
            cortexModelRolloutAnnotationBundles: []
        };
    }
}
