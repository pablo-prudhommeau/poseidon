import type {LabelProvider, TSciChart} from 'scichart';
import {
    buildChronicleArraysFromBucket,
    CHRONICLE_STREAM_LAG_MS_FALLBACK,
    type ChronicleBucketMeta,
    type ChronicleChartModel,
    computeChronicleViewportWidthMilliseconds,
    formatChronicleAxisLocalDateTimeMilliseconds,
    formatChronicleAxisTickLabelMilliseconds,
    formatChronicleCrosshairTooltip,
    resolveChronicleStreamLagMilliseconds,
    type SciChartModule,
} from '../data/shadow-verdict-chronicle-chart-data';
import type {ShadowVerdictChronicleSciChartLoaderService} from '../services/shadow-verdict-chronicle-scichart-loader.service';

export class ShadowVerdictChronicleChartSurfaceBuildController {
    private applyUniformColumnWidthForTimeBuckets(
        columnSeries: InstanceType<SciChartModule['FastColumnRenderableSeries']>,
        granularitySeconds: number,
        sci: SciChartModule,
    ): void {
        const bucketMilliseconds = Math.max(1000, granularitySeconds * 1000);
        columnSeries.dataPointWidthMode = sci.EDataPointWidthMode.Range;
        columnSeries.dataPointWidth = bucketMilliseconds * 0.88;
    }

    private createSplineMetricLine(
        sci: SciChartModule,
        wasmContext: TSciChart,
        xValues: number[],
        yValues: number[],
        dataSeriesName: string,
        stroke: string,
        yAxisId: string,
        glow: InstanceType<SciChartModule['GlowEffect']>,
    ): InstanceType<SciChartModule['SplineLineRenderableSeries']> {
        const {XyDataSeries, SplineLineRenderableSeries} = sci;
        const dataSeries = new XyDataSeries(wasmContext, {
            xValues,
            yValues,
            dataSeriesName,
            isSorted: true,
            containsNaN: false,
        });
        return new SplineLineRenderableSeries(wasmContext, {
            yAxisId,
            xAxisId: 'xTime',
            dataSeries,
            seriesName: dataSeriesName,
            stroke,
            strokeThickness: 2.5,
            opacity: 0.95,
            effect: glow,
        });
    }

    private createSplineSmaLine(
        sci: SciChartModule,
        wasmContext: TSciChart,
        xValues: number[],
        yValues: number[],
        dataSeriesName: string,
        stroke: string,
        yAxisId: string,
    ): InstanceType<SciChartModule['SplineLineRenderableSeries']> {
        const {XyDataSeries, SplineLineRenderableSeries} = sci;
        const dataSeries = new XyDataSeries(wasmContext, {
            xValues,
            yValues,
            dataSeriesName,
            isSorted: true,
            containsNaN: false,
        });
        return new SplineLineRenderableSeries(wasmContext, {
            yAxisId,
            xAxisId: 'xTime',
            dataSeries,
            seriesName: dataSeriesName,
            stroke,
            strokeThickness: 1.5,
            strokeDashArray: [4, 4],
            opacity: 0.65,
        });
    }

    async buildFullChartSurface(
        host: HTMLDivElement,
        meta: ChronicleBucketMeta,
        sciChartLoader: ShadowVerdictChronicleSciChartLoaderService,
        smaWindowBuckets: number,
    ): Promise<ChronicleChartModel> {
        const sci = await sciChartLoader.loadModule();
        const {
            BubbleAnimation,
            ColumnAnimation,
            CursorModifier,
            DateTimeNumericAxis,
            EAutoRange,
            EAxisAlignment,
            EDatePrecision,
            EllipsePointMarker,
            ELegendPlacement,
            FastBubbleRenderableSeries,
            FastColumnRenderableSeries,
            GlowEffect,
            GradientParams,
            LegendModifier,
            MouseWheelZoomModifier,
            MountainAnimation,
            NumberRange,
            NumericAxis,
            Point,
            SciChartJSDarkTheme,
            SciChartSurface,
            ShadowEffect,
            SplineMountainRenderableSeries,
            SweepAnimation,
            Thickness,
            XyDataSeries,
            XyzDataSeries,
            ZoomExtentsModifier,
            ZoomPanModifier,
            easing,
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
            padding: new Thickness(6, 12, 6, 6),
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
        });

        const axisLabelProvider = xAxis.labelProvider as LabelProvider;
        axisLabelProvider.formatLabel = formatChronicleAxisTickLabelMilliseconds;
        axisLabelProvider.formatCursorLabel = formatChronicleAxisLocalDateTimeMilliseconds;

        const yPercentage = new NumericAxis(wasmContext, {
            id: 'yPct',
            axisAlignment: EAxisAlignment.Left,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0.12, 0.12),
            drawMajorBands: false,
            drawMajorGridLines: true,
            drawMinorGridLines: true,
            maxAutoTicks: 12,
            minorsPerMajor: 4,
            axisTitle: 'PnL % · win rate %',
            axisTitleStyle: {fontSize: 11, color: '#e9d5ff'},
        });

        const yVolume = new NumericAxis(wasmContext, {
            id: 'yVol',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0, 0.28),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            axisTitle: 'verdict count / bucket',
            axisTitleStyle: {fontSize: 11, color: '#c084fc'},
        });

        const yExpectedValueUsd = new NumericAxis(wasmContext, {
            id: 'yUsd',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0.1, 0.1),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            axisTitle: 'EV per trade ($)',
            axisTitleStyle: {fontSize: 11, color: '#34d399'},
        });

        const yProfitFactor = new NumericAxis(wasmContext, {
            id: 'yPf',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0.05, 0.2),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            axisTitle: 'profit factor (gross win / gross loss)',
            axisTitleStyle: {fontSize: 11, color: '#fbbf24'},
        });

        const yVelocity = new NumericAxis(wasmContext, {
            id: 'yVel',
            axisAlignment: EAxisAlignment.Right,
            autoRange: EAutoRange.Always,
            growBy: new NumberRange(0.08, 0.18),
            drawMajorBands: false,
            drawMajorGridLines: false,
            drawMinorGridLines: false,
            axisTitle: 'velocity (closed / hour)',
            axisTitleStyle: {fontSize: 11, color: '#38bdf8'},
        });

        sciChartSurface.xAxes.add(xAxis);
        sciChartSurface.yAxes.add(yPercentage, yVolume, yExpectedValueUsd, yProfitFactor, yVelocity);

        const volumeMountainDataSeries = new XyDataSeries(wasmContext, {
            xValues: chronicleArrays.volumeBucketTimestampsMilliseconds,
            yValues: chronicleArrays.volumeBucketVerdictCounts,
            dataSeriesName: 'volume · area',
            isSorted: true,
            containsNaN: false,
        });

        const mountain = new SplineMountainRenderableSeries(wasmContext, {
            yAxisId: 'yVol',
            xAxisId: 'xTime',
            dataSeries: volumeMountainDataSeries,
            seriesName: 'volume · area',
            stroke: 'rgba(168, 85, 247, 0.35)',
            strokeThickness: 2,
            fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
                {offset: 0, color: 'rgba(168, 85, 247, 0.55)'},
                {offset: 0.55, color: 'rgba(6, 182, 212, 0.22)'},
                {offset: 1, color: 'rgba(6, 182, 212, 0.01)'},
            ]),
            effect: new ShadowEffect(wasmContext, {offset: new Point(0, 3), range: 4, brightness: 42}),
        });

        const volumeColumnDataSeries = new XyDataSeries(wasmContext, {
            xValues: chronicleArrays.volumeBucketTimestampsMilliseconds,
            yValues: chronicleArrays.volumeBucketVerdictCounts,
            dataSeriesName: 'volume · columns',
            isSorted: true,
            containsNaN: false,
        });
        const volumeColumnRenderableSeries = new FastColumnRenderableSeries(wasmContext, {
            yAxisId: 'yVol',
            xAxisId: 'xTime',
            dataSeries: volumeColumnDataSeries,
            seriesName: 'volume · columns',
            fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
                {offset: 0, color: 'rgba(236, 72, 153, 0.42)'},
                {offset: 1, color: 'rgba(99, 102, 241, 0.06)'},
            ]),
            stroke: 'rgba(244, 114, 182, 0.35)',
            strokeThickness: 1,
            cornerRadius: 4,
            opacity: 0.88,
        });
        this.applyUniformColumnWidthForTimeBuckets(
            volumeColumnRenderableSeries,
            meta.bucket.granularity_seconds,
            sci,
        );

        const lineAveragePnl = this.createSplineMetricLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.averagePnlPercentageSeries,
            'average PnL % (bucket)',
            '#f472b6',
            'yPct',
            new GlowEffect(wasmContext, {intensity: 0.52, range: 2.5}),
        );
        const lineWinRate = this.createSplineMetricLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.averageWinRatePercentageSeries,
            'average win rate % (bucket)',
            '#a78bfa',
            'yPct',
            new GlowEffect(wasmContext, {intensity: 0.45, range: 2}),
        );
        const lineExpectedValue = this.createSplineMetricLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.expectedValuePerTradeUsdSeries,
            'EV per trade ($) (bucket)',
            '#34d399',
            'yUsd',
            new GlowEffect(wasmContext, {intensity: 0.48, range: 2}),
        );
        const lineProfitFactor = this.createSplineMetricLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.profitFactorSeries,
            'profit factor (bucket)',
            '#fbbf24',
            'yPf',
            new GlowEffect(wasmContext, {intensity: 0.46, range: 2}),
        );
        const lineVelocity = this.createSplineMetricLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.capitalVelocityPerHourSeries,
            'velocity (closed / hour, bucket)',
            '#38bdf8',
            'yVel',
            new GlowEffect(wasmContext, {intensity: 0.46, range: 2}),
        );

        const smaLineAveragePnl = this.createSplineSmaLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.movingAveragePnlSeries,
            'SMA average PnL %',
            '#f472b6',
            'yPct',
        );
        const smaLineWinRate = this.createSplineSmaLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.movingAverageWinRateSeries,
            'SMA win rate %',
            '#a78bfa',
            'yPct',
        );
        const smaLineExpectedValue = this.createSplineSmaLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.movingAverageExpectedValueSeries,
            'SMA EV per trade',
            '#34d399',
            'yUsd',
        );
        const smaLineProfitFactor = this.createSplineSmaLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.movingAverageProfitFactorSeries,
            'SMA profit factor',
            '#fbbf24',
            'yPf',
        );
        const smaLineVelocity = this.createSplineSmaLine(
            sci,
            wasmContext,
            chronicleArrays.metricTimestampsMilliseconds,
            chronicleArrays.movingAverageVelocitySeries,
            'SMA velocity',
            '#38bdf8',
            'yVel',
        );

        const profitableVerdictXyzDataSeries = new XyzDataSeries(wasmContext, {
            dataSeriesName: 'verdict · win (PnL %)',
        });
        const lossVerdictXyzDataSeries = new XyzDataSeries(wasmContext, {
            dataSeriesName: 'verdict · loss (PnL %)',
        });
        for (const row of chronicleArrays.verdictCloudProfitablePoints) {
            profitableVerdictXyzDataSeries.append(row.x, row.y, row.z);
        }
        for (const row of chronicleArrays.verdictCloudLossPoints) {
            lossVerdictXyzDataSeries.append(row.x, row.y, row.z);
        }

        const winBubbles = new FastBubbleRenderableSeries(wasmContext, {
            yAxisId: 'yPct',
            xAxisId: 'xTime',
            dataSeries: profitableVerdictXyzDataSeries,
            pointMarker: new EllipsePointMarker(wasmContext, {
                width: 64,
                height: 64,
                stroke: 'rgba(16, 185, 129, 0.75)',
                fill: 'rgba(16, 185, 129, 0.46)',
                strokeThickness: 1.2,
            }),
            stroke: 'rgba(16, 185, 129, 0.75)',
            strokeThickness: 1.2,
            zMultiplier: 0.48,
            opacity: 0.82,
            effect: new GlowEffect(wasmContext, {
                intensity: 1.1,
                range: 3,
            }),
        });

        const lossBubbles = new FastBubbleRenderableSeries(wasmContext, {
            yAxisId: 'yPct',
            xAxisId: 'xTime',
            dataSeries: lossVerdictXyzDataSeries,
            seriesName: 'verdict · loss (PnL %)',
            pointMarker: new EllipsePointMarker(wasmContext, {
                width: 64,
                height: 64,
                stroke: 'rgba(239, 68, 68, 0.78)',
                fill: 'rgba(239, 68, 68, 0.48)',
                strokeThickness: 1.2,
            }),
            stroke: 'rgba(239, 68, 68, 0.78)',
            strokeThickness: 1.2,
            zMultiplier: 0.48,
            opacity: 0.78,
            effect: new GlowEffect(wasmContext, {
                intensity: 0.95,
                range: 2,
            }),
        });

        sciChartSurface.renderableSeries.add(
            mountain,
            volumeColumnRenderableSeries,
            lineAveragePnl,
            lineWinRate,
            lineExpectedValue,
            lineProfitFactor,
            lineVelocity,
            smaLineAveragePnl,
            smaLineWinRate,
            smaLineExpectedValue,
            smaLineProfitFactor,
            smaLineVelocity,
            lossBubbles,
            winBubbles,
        );

        const sweep = {duration: 2200, ease: easing.outExpo};
        mountain.runAnimation(new MountainAnimation({...sweep, dataSeries: volumeMountainDataSeries}));
        volumeColumnRenderableSeries.runAnimation(
            new ColumnAnimation({...sweep, dataSeries: volumeColumnDataSeries}),
        );
        for (const series of [
            lineAveragePnl,
            lineWinRate,
            lineExpectedValue,
            lineProfitFactor,
            lineVelocity,
            smaLineAveragePnl,
            smaLineWinRate,
            smaLineExpectedValue,
            smaLineProfitFactor,
            smaLineVelocity,
        ]) {
            series.runAnimation(new SweepAnimation(sweep));
        }
        winBubbles.runAnimation(new BubbleAnimation({...sweep, dataSeries: profitableVerdictXyzDataSeries}));
        lossBubbles.runAnimation(new BubbleAnimation({...sweep, dataSeries: lossVerdictXyzDataSeries}));

        sciChartSurface.chartModifiers.add(
            new ZoomPanModifier(),
            new MouseWheelZoomModifier(),
            new ZoomExtentsModifier(),
            new CursorModifier({
                crosshairStroke: 'rgba(167, 139, 250, 0.45)',
                crosshairStrokeThickness: 1,
                showTooltip: true,
                tooltipContainerBackground: '#0f172acc',
                tooltipTextStroke: '#f8fafc',
                axisLabelFill: '#1e1b4b',
                tooltipDataTemplate: (seriesInfos, _tooltipTitle) =>
                    formatChronicleCrosshairTooltip(seriesInfos),
            }),
            new LegendModifier({
                showCheckboxes: true,
                showLegend: true,
                placement: ELegendPlacement.TopRight,
                margin: 10,
                backgroundColor: '#110b2478',
                textColor: '#f5f3ff',
            }),
        );

        return {
            sciChartSurface,
            wasmContext,
            sci,
            xAxis,
            viewportWidthMilliseconds,
            volumeMountainDataSeries,
            volumeColumnDataSeries,
            volumeColumnRenderableSeries,
            metricLineRenderableSeries: [
                lineAveragePnl,
                lineWinRate,
                lineExpectedValue,
                lineProfitFactor,
                lineVelocity,
            ],
            movingAverageLineRenderableSeries: [
                smaLineAveragePnl,
                smaLineWinRate,
                smaLineExpectedValue,
                smaLineProfitFactor,
                smaLineVelocity,
            ],
            profitableVerdictXyzDataSeries,
            lossVerdictXyzDataSeries,
        };
    }
}
