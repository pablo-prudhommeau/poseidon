import type {LabelProvider} from 'scichart';
import {
    buildChronicleArraysFromBucket,
    CHRONICLE_STREAM_LAG_MS_FALLBACK,
    computeChronicleViewportWidthMilliseconds,
    formatChronicleAxisLocalDateTimeMilliseconds,
    formatChronicleAxisTickLabelMilliseconds,
    resolveChronicleStreamLagMilliseconds,
} from '../data/shadow-verdict-chronicle-arrays.utils';
import type {ChronicleBucketMeta, ChronicleChartModel} from '../data/shadow-verdict-chronicle.models';
import type {ShadowVerdictChronicleSciChartLoaderService} from '../services/shadow-verdict-chronicle-scichart-loader.service';
import {buildChronicleSeriesBundle} from './shadow-verdict-chronicle-series.builder';

export class ShadowVerdictChronicleSurfaceBuilder {
    async buildFullChartSurface(
        host: HTMLDivElement,
        meta: ChronicleBucketMeta,
        sciChartLoader: ShadowVerdictChronicleSciChartLoaderService,
        smaWindowBuckets: number,
    ): Promise<ChronicleChartModel> {
        const sci = await sciChartLoader.loadModule();
        const {
            DateTimeNumericAxis,
            EAutoRange,
            EAxisAlignment,
            EDatePrecision,
            NumberRange,
            NumericAxis,
            SciChartJSDarkTheme,
            SciChartSurface,
            Thickness,
        } = sci;

        const customTheme = new SciChartJSDarkTheme();
        customTheme.sciChartBackground = '#050914';
        customTheme.axisBandsFill = '#00000000';
        customTheme.gridBackgroundBrush = '#050914';
        customTheme.majorGridLineBrush = 'rgba(148, 163, 184, 0.28)';
        customTheme.minorGridLineBrush = 'rgba(148, 163, 184, 0.14)';
        customTheme.axisBorder = 'rgba(255, 255, 255, 0.12)';
        customTheme.tickTextBrush = '#c4b5fdcc';
        customTheme.legendBackgroundBrush = '#0b102878';

        const {sciChartSurface, wasmContext} = await SciChartSurface.create(host, {
            theme: customTheme,
            background: '#050914',
            padding: new Thickness(6, 6, 6, 6),
        });

        const streamLagMilliseconds = resolveChronicleStreamLagMilliseconds(meta.response.series_end_lag_seconds);
        const chronicleArrays = buildChronicleArraysFromBucket(meta, streamLagMilliseconds, smaWindowBuckets);
        const viewportWidthMilliseconds = computeChronicleViewportWidthMilliseconds(chronicleArrays);
        const initialRightEdgeMilliseconds = Date.now() - CHRONICLE_STREAM_LAG_MS_FALLBACK;

        const xAxis = new DateTimeNumericAxis(wasmContext, {
            id: 'xTime',
            axisAlignment: EAxisAlignment.Bottom,
            autoRange: EAutoRange.Never,
            visibleRange: new NumberRange(
                initialRightEdgeMilliseconds - viewportWidthMilliseconds,
                initialRightEdgeMilliseconds,
            ),
            drawMajorBands: false,
            drawMajorGridLines: true,
            drawMinorGridLines: true,
            maxAutoTicks: 14,
            minTicks: 10,
            minorsPerMajor: 4,
            datePrecision: EDatePrecision.Milliseconds,
            showYearOnWiderDate: true,
            labelStyle: {fontSize: 11, color: '#cbd5e1d9'},
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
            axisTitle: 'PnL % · win rate %',
            axisTitleStyle: {fontSize: 11, color: '#e9d5ff'},
            labelStyle: {fontSize: 11, color: '#cbd5e1d9'},
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
            axisTitle: 'Verdict count / bucket',
            axisTitleStyle: {fontSize: 10, color: '#c084fc'},
            labelStyle: {fontSize: 11, color: '#cbd5e1d9'},
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
            axisTitle: 'EV per trade ($)',
            axisTitleStyle: {fontSize: 10, color: '#34d399'},
            labelStyle: {fontSize: 11, color: '#cbd5e1d9'},
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
            axisTitle: 'Profit factor (gross win / gross loss)',
            axisTitleStyle: {fontSize: 10, color: '#fbbf24'},
            labelStyle: {fontSize: 11, color: '#cbd5e1d9'},
        });

        const yVelocityAxis = new NumericAxis(wasmContext, {
            id: 'yVel',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            maxAutoTicks: 10,
            minorsPerMajor: 4,
            axisTitle: 'Velocity (closed / hour)',
            axisTitleStyle: {fontSize: 10, color: '#38bdf8'},
            labelStyle: {fontSize: 11, color: '#cbd5e1d9'},
        });

        sciChartSurface.xAxes.add(xAxis);
        sciChartSurface.yAxes.add(
            yPercentage,
            yVolume,
            yExpectedValueAxis,
            yProfitFactorAxis,
            yVelocityAxis,
        );

        const seriesBundle = buildChronicleSeriesBundle(
            sci,
            wasmContext,
            sciChartSurface,
            chronicleArrays,
            meta,
        );

        return {
            sciChartSurface,
            wasmContext,
            sci,
            xAxis,
            viewportWidthMilliseconds,
            volumeMountainDataSeries: seriesBundle.volumeMountainDataSeries,
            volumeColumnDataSeries: seriesBundle.volumeColumnDataSeries,
            volumeColumnRenderableSeries: seriesBundle.volumeColumnRenderableSeries,
            yVolumeAxis: yVolume,
            yExpectedValueAxis,
            yProfitFactorAxis,
            yVelocityAxis,
            goldenZoneExpectedValueBandDataSeries: seriesBundle.goldenZoneExpectedValueBandDataSeries,
            goldenZoneProfitFactorBandDataSeries: seriesBundle.goldenZoneProfitFactorBandDataSeries,
            goldenZoneExpectedValueBandSeries: seriesBundle.goldenZoneExpectedValueBandSeries,
            goldenZoneProfitFactorBandSeries: seriesBundle.goldenZoneProfitFactorBandSeries,
            goldenZoneExpectedValueSmaPaletteController: seriesBundle.goldenZoneExpectedValueSmaPaletteController,
            goldenZoneProfitFactorSmaPaletteController: seriesBundle.goldenZoneProfitFactorSmaPaletteController,
            metricLineRenderableSeries: seriesBundle.metricLineRenderableSeries,
            movingAverageLineRenderableSeries: seriesBundle.movingAverageLineRenderableSeries,
            profitableVerdictXyzDataSeries: seriesBundle.profitableVerdictXyzDataSeries,
            lossVerdictXyzDataSeries: seriesBundle.lossVerdictXyzDataSeries,
            goldenZoneExpectedValueAnnotation: seriesBundle.goldenZoneExpectedValueAnnotation,
            goldenZoneProfitFactorAnnotation: seriesBundle.goldenZoneProfitFactorAnnotation,
        };
    }
}
