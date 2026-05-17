import type { LabelProvider } from 'scichart';
import type { ChronicleBucketMeta, ChronicleChartModel } from '../data/shadow-verdict-chronicle.models';
import {
    buildChronicleArraysFromBucket,
    CHRONICLE_STREAM_LAG_MS_FALLBACK,
    computeChronicleViewportWidthMilliseconds,
    formatChronicleAxisLocalDateTimeMilliseconds,
    formatChronicleAxisTickLabelMilliseconds,
    resolveChronicleStreamLagMilliseconds
} from '../data/shadow-verdict-chronicle-arrays.utils';
import { CHRONICLE_AXIS_TITLES, CHRONICLE_METRIC_COLORS } from '../data/shadow-verdict-chronicle-metrics.catalog';
import type { ShadowVerdictChronicleSciChartLoaderService } from '../services/shadow-verdict-chronicle-scichart-loader.service';
import { buildChronicleSeriesBundle } from './shadow-verdict-chronicle-series.builder';

export class ShadowVerdictChronicleSurfaceBuilder {
    async buildFullChartSurface(
        host: HTMLDivElement,
        meta: ChronicleBucketMeta,
        sciChartLoader: ShadowVerdictChronicleSciChartLoaderService,
        smaWindowBuckets: number
    ): Promise<ChronicleChartModel> {
        const sci = await sciChartLoader.loadModule();
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

        const streamLagMilliseconds = resolveChronicleStreamLagMilliseconds(meta.response.series_end_lag_seconds);
        const chronicleArrays = buildChronicleArraysFromBucket(meta, streamLagMilliseconds, smaWindowBuckets);
        const viewportWidthMilliseconds = computeChronicleViewportWidthMilliseconds(chronicleArrays);
        const initialRightEdgeMilliseconds = Date.now() - CHRONICLE_STREAM_LAG_MS_FALLBACK;

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
        sciChartSurface.yAxes.add(yPercentage, yVolume, yExpectedValueAxis, yProfitFactorAxis, yTradesPerHourAxis, yRegimeEvAxis, yRegimePfAxis);

        const seriesBundle = buildChronicleSeriesBundle(sci, wasmContext, sciChartSurface, chronicleArrays, meta);

        return {
            sciChartSurface,
            wasmContext,
            sci,
            xAxis,
            viewportWidthMilliseconds,
            volumeColumnDataSeries: seriesBundle.volumeColumnDataSeries,
            volumeColumnRenderableSeries: seriesBundle.volumeColumnRenderableSeries,
            yVolumeAxis: yVolume,
            yExpectedValueAxis,
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
            cortexCalibrationBandSegmentBundles: seriesBundle.cortexCalibrationBandSegmentBundles,
            cortexCalibrationBandUserVisible: true,
            cortexModelRolloutUserVisible: true,
            evGateThresholdUserVisible: true,
            pfGateThresholdUserVisible: true,
            goldenZoneExpectedValueAnnotation: seriesBundle.goldenZoneExpectedValueAnnotation,
            goldenZoneProfitFactorAnnotation: seriesBundle.goldenZoneProfitFactorAnnotation,
            cortexModelRolloutAnnotationBundles: []
        };
    }
}
