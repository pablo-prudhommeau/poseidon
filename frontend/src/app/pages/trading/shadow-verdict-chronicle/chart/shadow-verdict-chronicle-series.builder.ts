import type { TSciChart } from 'scichart';
import type {
    ChronicleAdjustTooltipPositionHost,
    ChronicleArrays,
    ChronicleBucketMeta,
    ChronicleChartModel,
    ChronicleThresholdPaletteBinding,
    SciChartModule
} from '../data/shadow-verdict-chronicle.models';
import { buildChronicleCursorTooltipSvg } from '../data/shadow-verdict-chronicle-tooltip.formatter';

export interface ChronicleSeriesBundle {
    volumeMountainDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    volumeColumnDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    volumeColumnRenderableSeries: InstanceType<SciChartModule['FastColumnRenderableSeries']>;
    goldenZoneExpectedValueBandDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneProfitFactorBandDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneExpectedValueBandSeries: InstanceType<SciChartModule['SplineMountainRenderableSeries']>;
    goldenZoneProfitFactorBandSeries: InstanceType<SciChartModule['SplineMountainRenderableSeries']>;
    goldenZoneExpectedValueSmaPaletteController: ChronicleThresholdPaletteBinding;
    goldenZoneProfitFactorSmaPaletteController: ChronicleThresholdPaletteBinding;
    metricLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    movingAverageLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    profitableVerdictXyzDataSeries: InstanceType<SciChartModule['XyzDataSeries']>;
    lossVerdictXyzDataSeries: InstanceType<SciChartModule['XyzDataSeries']>;
    goldenZoneExpectedValueAnnotation: InstanceType<SciChartModule['HorizontalLineAnnotation']>;
    goldenZoneProfitFactorAnnotation: InstanceType<SciChartModule['HorizontalLineAnnotation']>;
}

function resolveFiniteThreshold(value: number | string | null | undefined): number | undefined {
    const numeric = typeof value === 'string' ? Number(value) : value;
    return typeof numeric === 'number' && Number.isFinite(numeric) ? numeric : undefined;
}

function createGoldenZoneAnnotation(
    sci: SciChartModule,
    yAxisId: string,
    threshold: number | string | null | undefined,
    fill: string
): InstanceType<SciChartModule['HorizontalLineAnnotation']> {
    const thresholdValue = resolveFiniteThreshold(threshold);
    const { HorizontalLineAnnotation } = sci;
    return new HorizontalLineAnnotation({
        y1: thresholdValue ?? 0,
        yAxisId,
        stroke: fill,
        strokeThickness: 2,
        strokeDashArray: [6, 4],
        opacity: 0.9,
        isEditable: false,
        isHidden: thresholdValue == null,
        showLabel: false,
        annotationLayer: sci.EAnnotationLayer.AboveChart
    });
}

function createSmaThresholdPaletteController(sci: SciChartModule, highlightedColor: string, belowThresholdColor: string): ChronicleThresholdPaletteBinding {
    const highlightedArgb = sci.parseColorToUIntArgb(highlightedColor);
    const belowThresholdArgb = sci.parseColorToUIntArgb(belowThresholdColor);
    const defaultPaletteProviderConstructor = sci.DefaultPaletteProvider as unknown as new () => Record<string, unknown>;

    class ThresholdPaletteProvider extends defaultPaletteProviderConstructor {
        strokePaletteMode: unknown;
        thresholdValue: number | undefined;

        constructor() {
            super();
            this.strokePaletteMode = sci.EStrokePaletteMode.SOLID;
            this.thresholdValue = undefined;
        }

        overrideStrokeArgb(_xValue: number, yValue: number): number | undefined {
            if (!Number.isFinite(yValue)) {
                return undefined;
            }
            if (this.thresholdValue == null) {
                return belowThresholdArgb;
            }
            return yValue >= this.thresholdValue ? highlightedArgb : belowThresholdArgb;
        }
    }

    const provider = new ThresholdPaletteProvider();
    return {
        paletteProvider: provider,
        setThreshold: (value: number | undefined): void => {
            provider.thresholdValue = value;
        }
    };
}

function applyUniformColumnWidthForTimeBuckets(
    columnSeries: InstanceType<SciChartModule['FastColumnRenderableSeries']>,
    granularitySeconds: number,
    sci: SciChartModule
): void {
    const bucketMilliseconds = Math.max(1000, granularitySeconds * 1000);
    columnSeries.dataPointWidthMode = sci.EDataPointWidthMode.Range;
    columnSeries.dataPointWidth = bucketMilliseconds * 0.88;
}

function createSplineMetricLine(
    sci: SciChartModule,
    wasmContext: TSciChart,
    xValues: number[],
    yValues: number[],
    dataSeriesName: string,
    stroke: string,
    yAxisId: string,
    glow: InstanceType<SciChartModule['GlowEffect']>
): InstanceType<SciChartModule['SplineLineRenderableSeries']> {
    const { XyDataSeries, SplineLineRenderableSeries } = sci;
    const dataSeries = new XyDataSeries(wasmContext, {
        xValues,
        yValues,
        dataSeriesName,
        isSorted: true,
        containsNaN: false
    });
    return new SplineLineRenderableSeries(wasmContext, {
        yAxisId,
        xAxisId: 'xTime',
        dataSeries,
        seriesName: dataSeriesName,
        stroke,
        strokeThickness: 2.5,
        opacity: 0.95,
        effect: glow
    });
}

function createSplineMovingAverageLine(
    sci: SciChartModule,
    wasmContext: TSciChart,
    xValues: number[],
    yValues: number[],
    dataSeriesName: string,
    stroke: string,
    yAxisId: string
): InstanceType<SciChartModule['SplineLineRenderableSeries']> {
    const { XyDataSeries, SplineLineRenderableSeries } = sci;
    const dataSeries = new XyDataSeries(wasmContext, {
        xValues,
        yValues,
        dataSeriesName,
        isSorted: true,
        containsNaN: false
    });
    return new SplineLineRenderableSeries(wasmContext, {
        yAxisId,
        xAxisId: 'xTime',
        dataSeries,
        seriesName: dataSeriesName,
        stroke,
        strokeThickness: 1.5,
        strokeDashArray: [4, 4],
        opacity: 0.65
    });
}

export function buildChronicleSeriesBundle(
    sci: SciChartModule,
    wasmContext: TSciChart,
    sciChartSurface: ChronicleChartModel['sciChartSurface'],
    chronicleArrays: ChronicleArrays,
    meta: ChronicleBucketMeta
): ChronicleSeriesBundle {
    const {
        BubbleAnimation,
        ColumnAnimation,
        CursorModifier,
        ELegendPlacement,
        EllipsePointMarker,
        FastBubbleRenderableSeries,
        FastColumnRenderableSeries,
        GlowEffect,
        GradientParams,
        LegendModifier,
        MouseWheelZoomModifier,
        MountainAnimation,
        Point,
        ShadowEffect,
        SplineMountainRenderableSeries,
        SweepAnimation,
        XyDataSeries,
        XyzDataSeries,
        ZoomExtentsModifier,
        ZoomPanModifier,
        easing
    } = sci;

    const goldenZoneExpectedValueAnnotation = createGoldenZoneAnnotation(sci, 'yUsd', meta.sparseExpectedValueUsdThreshold, 'rgba(52, 211, 153, 0.95)');
    const goldenZoneProfitFactorAnnotation = createGoldenZoneAnnotation(sci, 'yPf', meta.chronicleProfitFactorThreshold, 'rgba(251, 191, 36, 0.95)');
    sciChartSurface.annotations.add(goldenZoneExpectedValueAnnotation);
    sciChartSurface.annotations.add(goldenZoneProfitFactorAnnotation);

    const expectedValueThreshold = resolveFiniteThreshold(meta.sparseExpectedValueUsdThreshold);
    const profitFactorThreshold = resolveFiniteThreshold(meta.chronicleProfitFactorThreshold);

    const goldenZoneExpectedValueBandDataSeries = new XyDataSeries(wasmContext, {
        xValues: chronicleArrays.metricTimestampsMilliseconds,
        yValues:
            expectedValueThreshold == null
                ? chronicleArrays.movingAverageExpectedValueSeries.map(() => 0)
                : chronicleArrays.movingAverageExpectedValueSeries.map((value: number) => (value > expectedValueThreshold ? value : expectedValueThreshold)),
        dataSeriesName: 'SMA EV per trade (area)',
        isSorted: true,
        containsNaN: false
    });

    const goldenZoneExpectedValueBandSeries = new SplineMountainRenderableSeries(wasmContext, {
        yAxisId: 'yUsd',
        xAxisId: 'xTime',
        dataSeries: goldenZoneExpectedValueBandDataSeries,
        seriesName: 'SMA EV per trade (area)',
        stroke: '#34d399',
        strokeThickness: 1,
        fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
            { offset: 0, color: 'rgba(52, 211, 153, 0.58)' },
            { offset: 0.55, color: 'rgba(52, 211, 153, 0.26)' },
            { offset: 1, color: 'rgba(52, 211, 153, 0.04)' }
        ]),
        zeroLineY: expectedValueThreshold ?? 0,
        opacity: 0.95,
        effect: new GlowEffect(wasmContext, { intensity: 0.52, range: 2 })
    });

    const goldenZoneProfitFactorBandDataSeries = new XyDataSeries(wasmContext, {
        xValues: chronicleArrays.metricTimestampsMilliseconds,
        yValues:
            profitFactorThreshold == null
                ? chronicleArrays.movingAverageProfitFactorSeries.map(() => 0)
                : chronicleArrays.movingAverageProfitFactorSeries.map((value: number) => (value > profitFactorThreshold ? value : profitFactorThreshold)),
        dataSeriesName: 'SMA profit factor (area)',
        isSorted: true,
        containsNaN: false
    });
    const goldenZoneProfitFactorBandSeries = new SplineMountainRenderableSeries(wasmContext, {
        yAxisId: 'yPf',
        xAxisId: 'xTime',
        dataSeries: goldenZoneProfitFactorBandDataSeries,
        seriesName: 'SMA profit factor (area)',
        stroke: '#fbbf24',
        strokeThickness: 1,
        fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
            { offset: 0, color: 'rgba(251, 191, 36, 0.55)' },
            { offset: 0.55, color: 'rgba(251, 191, 36, 0.24)' },
            { offset: 1, color: 'rgba(251, 191, 36, 0.04)' }
        ]),
        zeroLineY: profitFactorThreshold ?? 0,
        opacity: 0.95,
        effect: new GlowEffect(wasmContext, { intensity: 0.5, range: 2 })
    });

    const volumeMountainDataSeries = new XyDataSeries(wasmContext, {
        xValues: chronicleArrays.volumeBucketTimestampsMilliseconds,
        yValues: chronicleArrays.volumeBucketVerdictCounts,
        dataSeriesName: 'Volume · area',
        isSorted: true,
        containsNaN: false
    });

    const volumeMountainSeries = new SplineMountainRenderableSeries(wasmContext, {
        yAxisId: 'yVol',
        xAxisId: 'xTime',
        dataSeries: volumeMountainDataSeries,
        seriesName: 'Volume · area',
        stroke: 'rgba(168, 85, 247, 0.35)',
        strokeThickness: 2,
        fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
            { offset: 0, color: 'rgba(168, 85, 247, 0.55)' },
            { offset: 0.55, color: 'rgba(6, 182, 212, 0.22)' },
            { offset: 1, color: 'rgba(6, 182, 212, 0.01)' }
        ]),
        effect: new ShadowEffect(wasmContext, { offset: new Point(0, 3), range: 4, brightness: 42 })
    });
    volumeMountainSeries.isVisible = false;

    const volumeColumnDataSeries = new XyDataSeries(wasmContext, {
        xValues: chronicleArrays.volumeBucketTimestampsMilliseconds,
        yValues: chronicleArrays.volumeBucketVerdictCounts,
        dataSeriesName: 'Volume · columns',
        isSorted: true,
        containsNaN: false
    });

    const volumeColumnRenderableSeries = new FastColumnRenderableSeries(wasmContext, {
        yAxisId: 'yVol',
        xAxisId: 'xTime',
        dataSeries: volumeColumnDataSeries,
        seriesName: 'Volume · columns',
        fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
            { offset: 0, color: 'rgba(236, 72, 153, 0.42)' },
            { offset: 1, color: 'rgba(99, 102, 241, 0.06)' }
        ]),
        stroke: 'rgba(244, 114, 182, 0.35)',
        strokeThickness: 1,
        cornerRadius: 4,
        opacity: 0.88
    });
    volumeColumnRenderableSeries.isVisible = false;
    applyUniformColumnWidthForTimeBuckets(volumeColumnRenderableSeries, meta.bucket.granularity_seconds, sci);

    const averagePnlLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.averagePnlPercentageSeries,
        'Average PnL % (bucket)',
        '#f472b6',
        'yPct',
        new GlowEffect(wasmContext, { intensity: 0.52, range: 2.5 })
    );
    averagePnlLineSeries.isVisible = false;
    const averageWinRateLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.averageWinRatePercentageSeries,
        'Average win rate % (bucket)',
        '#a78bfa',
        'yPct',
        new GlowEffect(wasmContext, { intensity: 0.45, range: 2 })
    );
    averageWinRateLineSeries.isVisible = false;
    const expectedValueLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.expectedValuePerTradeUsdSeries,
        'EV per trade ($) (bucket)',
        '#34d399',
        'yUsd',
        new GlowEffect(wasmContext, { intensity: 0.48, range: 2 })
    );
    expectedValueLineSeries.isVisible = false;
    const profitFactorLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.profitFactorSeries,
        'Profit factor (bucket)',
        '#fbbf24',
        'yPf',
        new GlowEffect(wasmContext, { intensity: 0.46, range: 2 })
    );
    profitFactorLineSeries.isVisible = false;
    const velocityLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.capitalVelocityPerHourSeries,
        'Velocity (closed / hour, bucket)',
        '#38bdf8',
        'yVel',
        new GlowEffect(wasmContext, { intensity: 0.46, range: 2 })
    );
    velocityLineSeries.isVisible = false;

    const movingAveragePnlLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAveragePnlSeries,
        'SMA average PnL %',
        '#f472b6',
        'yPct'
    );
    movingAveragePnlLineSeries.isVisible = false;
    const movingAverageWinRateLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageWinRateSeries,
        'SMA win rate %',
        '#a78bfa',
        'yPct'
    );
    movingAverageWinRateLineSeries.isVisible = false;
    const movingAverageExpectedValueLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageExpectedValueSeries,
        'SMA EV per trade',
        '#A7F3D0',
        'yUsd'
    );
    movingAverageExpectedValueLineSeries.opacity = 1;
    const movingAverageProfitFactorLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageProfitFactorSeries,
        'SMA profit factor',
        '#FDE68A',
        'yPf'
    );
    movingAverageProfitFactorLineSeries.opacity = 1;
    const movingAverageVelocityLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageVelocitySeries,
        'SMA velocity',
        '#38bdf8',
        'yVel'
    );
    movingAverageVelocityLineSeries.isVisible = false;

    const goldenZoneExpectedValueSmaPaletteController = createSmaThresholdPaletteController(sci, '#A7F3D0', '#3F8F75');
    const goldenZoneProfitFactorSmaPaletteController = createSmaThresholdPaletteController(sci, '#FDE68A', '#9B7A22');
    goldenZoneExpectedValueSmaPaletteController.setThreshold(expectedValueThreshold);
    goldenZoneProfitFactorSmaPaletteController.setThreshold(profitFactorThreshold);
    movingAverageExpectedValueLineSeries.paletteProvider = goldenZoneExpectedValueSmaPaletteController.paletteProvider as never;
    movingAverageProfitFactorLineSeries.paletteProvider = goldenZoneProfitFactorSmaPaletteController.paletteProvider as never;

    const profitableVerdictXyzDataSeries = new XyzDataSeries(wasmContext, {
        dataSeriesName: 'Non-staled verdict · win (PnL %)'
    });
    const lossVerdictXyzDataSeries = new XyzDataSeries(wasmContext, {
        dataSeriesName: 'Non-staled verdict · loss (PnL %)'
    });
    for (const row of chronicleArrays.verdictCloudProfitablePoints) {
        profitableVerdictXyzDataSeries.append(row.x, row.y, row.z);
    }
    for (const row of chronicleArrays.verdictCloudLossPoints) {
        lossVerdictXyzDataSeries.append(row.x, row.y, row.z);
    }

    const profitableVerdictBubbleSeries = new FastBubbleRenderableSeries(wasmContext, {
        yAxisId: 'yPct',
        xAxisId: 'xTime',
        dataSeries: profitableVerdictXyzDataSeries,
        seriesName: 'Non-staled verdict · win (PnL %)',
        pointMarker: new EllipsePointMarker(wasmContext, {
            width: 64,
            height: 64,
            stroke: 'rgba(16, 185, 129, 0.75)',
            fill: 'rgba(16, 185, 129, 0.46)',
            strokeThickness: 1.2
        }),
        stroke: 'rgba(16, 185, 129, 0.75)',
        strokeThickness: 1.2,
        zMultiplier: 0.48,
        opacity: 0.82,
        effect: new GlowEffect(wasmContext, { intensity: 1.1, range: 3 })
    });

    const lossVerdictBubbleSeries = new FastBubbleRenderableSeries(wasmContext, {
        yAxisId: 'yPct',
        xAxisId: 'xTime',
        dataSeries: lossVerdictXyzDataSeries,
        seriesName: 'Non-staled verdict · loss (PnL %)',
        pointMarker: new EllipsePointMarker(wasmContext, {
            width: 64,
            height: 64,
            stroke: 'rgba(239, 68, 68, 0.78)',
            fill: 'rgba(239, 68, 68, 0.48)',
            strokeThickness: 1.2
        }),
        stroke: 'rgba(239, 68, 68, 0.78)',
        strokeThickness: 1.2,
        zMultiplier: 0.48,
        opacity: 0.78,
        effect: new GlowEffect(wasmContext, { intensity: 0.95, range: 2 })
    });

    sciChartSurface.renderableSeries.add(
        volumeMountainSeries,
        volumeColumnRenderableSeries,
        averagePnlLineSeries,
        averageWinRateLineSeries,
        expectedValueLineSeries,
        profitFactorLineSeries,
        velocityLineSeries,
        movingAveragePnlLineSeries,
        movingAverageWinRateLineSeries,
        movingAverageExpectedValueLineSeries,
        goldenZoneExpectedValueBandSeries,
        movingAverageProfitFactorLineSeries,
        goldenZoneProfitFactorBandSeries,
        movingAverageVelocityLineSeries,
        lossVerdictBubbleSeries,
        profitableVerdictBubbleSeries
    );

    const sweep = { duration: 2200, ease: easing.outExpo };
    volumeMountainSeries.runAnimation(new MountainAnimation({ ...sweep, dataSeries: volumeMountainDataSeries }));
    volumeColumnRenderableSeries.runAnimation(new ColumnAnimation({ ...sweep, dataSeries: volumeColumnDataSeries }));
    for (const series of [
        averagePnlLineSeries,
        averageWinRateLineSeries,
        expectedValueLineSeries,
        profitFactorLineSeries,
        velocityLineSeries,
        movingAveragePnlLineSeries,
        movingAverageWinRateLineSeries,
        movingAverageExpectedValueLineSeries,
        movingAverageProfitFactorLineSeries,
        movingAverageVelocityLineSeries
    ]) {
        series.runAnimation(new SweepAnimation(sweep));
    }
    profitableVerdictBubbleSeries.runAnimation(new BubbleAnimation({ ...sweep, dataSeries: profitableVerdictXyzDataSeries }));
    lossVerdictBubbleSeries.runAnimation(new BubbleAnimation({ ...sweep, dataSeries: lossVerdictXyzDataSeries }));

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
            tooltipSvgTemplate: (seriesInfos, svgAnnotation) =>
                buildChronicleCursorTooltipSvg(sci as unknown as ChronicleAdjustTooltipPositionHost, seriesInfos as never, svgAnnotation)
        }),
        new LegendModifier({
            showCheckboxes: true,
            showSeriesMarkers: true,
            showLegend: false,
            placement: ELegendPlacement.TopRight,
            margin: 10,
            backgroundColor: '#110b2478',
            textColor: '#f5f3ff'
        })
    );

    return {
        volumeMountainDataSeries,
        volumeColumnDataSeries,
        volumeColumnRenderableSeries,
        goldenZoneExpectedValueBandDataSeries,
        goldenZoneProfitFactorBandDataSeries,
        goldenZoneExpectedValueBandSeries,
        goldenZoneProfitFactorBandSeries,
        goldenZoneExpectedValueSmaPaletteController,
        goldenZoneProfitFactorSmaPaletteController,
        metricLineRenderableSeries: [averagePnlLineSeries, averageWinRateLineSeries, expectedValueLineSeries, profitFactorLineSeries, velocityLineSeries],
        movingAverageLineRenderableSeries: [
            movingAveragePnlLineSeries,
            movingAverageWinRateLineSeries,
            movingAverageExpectedValueLineSeries,
            movingAverageProfitFactorLineSeries,
            movingAverageVelocityLineSeries
        ],
        profitableVerdictXyzDataSeries,
        lossVerdictXyzDataSeries,
        goldenZoneExpectedValueAnnotation,
        goldenZoneProfitFactorAnnotation
    };
}
