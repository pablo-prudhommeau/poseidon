import type { TSciChart } from 'scichart';
import type {
    ChronicleAdjustTooltipPositionHost,
    ChronicleArrays,
    ChronicleBucketMeta,
    ChronicleCartesianPoint,
    ChronicleChartModel,
    ChronicleVerdictBubblePointMetadata,
    SciChartModule
} from '../data/shadow-verdict-chronicle.models';
import { CHRONICLE_METRIC_COLORS } from '../data/shadow-verdict-chronicle-metrics.catalog';
import { CHRONICLE_SERIES } from '../data/shadow-verdict-chronicle-series-names';
import { buildChronicleCursorTooltipSvg } from '../data/shadow-verdict-chronicle-tooltip.formatter';
import { buildCortexCalibrationBandSegmentBundles, buildCortexCalibrationBandSegments } from './shadow-verdict-chronicle-cortex-calibration-band.utils';
import { buildChronicleGoldenZoneExpectedValueBandValues, buildChronicleGoldenZoneProfitFactorBandValues } from './shadow-verdict-chronicle-golden-zone.utils';
import {
    buildRegimeEvGateSubmergedBandSegmentBundles,
    buildRegimeEvGateSubmergedBandSegmentsFromArrays,
    buildRegimePfGateSubmergedBandSegmentBundles,
    buildRegimePfGateSubmergedBandSegmentsFromArrays
} from './shadow-verdict-chronicle-gate-submerged-band.utils';

export interface ChronicleSeriesBundle {
    volumeColumnDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    volumeColumnRenderableSeries: InstanceType<SciChartModule['FastColumnRenderableSeries']>;
    goldenZoneExpectedValueBandDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneProfitFactorBandDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneExpectedValueBandSeries: InstanceType<SciChartModule['SplineMountainRenderableSeries']>;
    goldenZoneProfitFactorBandSeries: InstanceType<SciChartModule['SplineMountainRenderableSeries']>;
    regimeEvGateSubmergedBandSegmentBundles: ChronicleChartModel['regimeEvGateSubmergedBandSegmentBundles'];
    regimePfGateSubmergedBandSegmentBundles: ChronicleChartModel['regimePfGateSubmergedBandSegmentBundles'];
    metricLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    movingAverageLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    profitableVerdictXyDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    lossVerdictXyDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    goldenZoneExpectedValueAnnotation: InstanceType<SciChartModule['HorizontalLineAnnotation']>;
    goldenZoneProfitFactorAnnotation: InstanceType<SciChartModule['HorizontalLineAnnotation']>;
    cortexCalibrationBandSegmentBundles: ChronicleChartModel['cortexCalibrationBandSegmentBundles'];
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

function createCortexHaloPaletteProvider(sci: SciChartModule, _baseStrokeColor: string, _baseFillColor: string): unknown {
    const defaultPaletteProviderConstructor = sci.DefaultPaletteProvider as unknown as new () => Record<string, unknown>;

    const winPredictedHaloArgb = sci.parseColorToUIntArgb(CHRONICLE_METRIC_COLORS.cortexHaloWin);
    const lossPredictedHaloArgb = sci.parseColorToUIntArgb(CHRONICLE_METRIC_COLORS.cortexHaloLoss);

    class CortexHaloPaletteProvider extends defaultPaletteProviderConstructor {
        strokePaletteMode: unknown;

        constructor() {
            super();
            this.strokePaletteMode = sci.EStrokePaletteMode.SOLID;
        }

        overrideStrokeArgb(_xValue: number, _yValue: number, _index: number, _opacity?: number, metadata?: any): number | undefined {
            if (metadata && typeof metadata.cortexProbability === 'number' && !Number.isNaN(metadata.cortexProbability)) {
                return metadata.cortexProbability >= 0.5 ? winPredictedHaloArgb : lossPredictedHaloArgb;
            }
            return undefined;
        }
    }
    return new CortexHaloPaletteProvider();
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

function buildVerdictCloudPointMetadata(point: ChronicleCartesianPoint): ChronicleVerdictBubblePointMetadata {
    return {
        cortexProbability: point.cortexProbability,
        orderNotionalUsd: point.orderNotionalUsd,
        isSelected: false
    };
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
        containsNaN: true
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
        containsNaN: true
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
        ColumnAnimation,
        CursorModifier,
        ELegendPlacement,
        EllipsePointMarker,
        FastColumnRenderableSeries,
        GlowEffect,
        GradientParams,
        LegendModifier,
        MouseWheelZoomModifier,
        Point,
        SplineMountainRenderableSeries,
        SweepAnimation,
        XyDataSeries,
        XyScatterRenderableSeries,
        ZoomExtentsModifier,
        ZoomPanModifier,
        easing
    } = sci;

    const goldenZoneExpectedValueAnnotation = createGoldenZoneAnnotation(
        sci,
        'yRegimeEv',
        meta.sparseExpectedValueUsdThreshold,
        CHRONICLE_METRIC_COLORS.expectedValueThreshold
    );
    const goldenZoneProfitFactorAnnotation = createGoldenZoneAnnotation(
        sci,
        'yRegimePf',
        meta.chronicleProfitFactorThreshold,
        CHRONICLE_METRIC_COLORS.profitFactorThreshold
    );

    const expectedValueThreshold = resolveFiniteThreshold(meta.sparseExpectedValueUsdThreshold);
    const profitFactorThreshold = resolveFiniteThreshold(meta.chronicleProfitFactorThreshold);

    const regimeEvGateSubmergedBandSegments = buildRegimeEvGateSubmergedBandSegmentsFromArrays(
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays,
        expectedValueThreshold
    );
    const regimeEvGateSubmergedBandSegmentBundles = buildRegimeEvGateSubmergedBandSegmentBundles(sci, wasmContext, regimeEvGateSubmergedBandSegments, true);

    const goldenZoneExpectedValueBandDataSeries = new XyDataSeries(wasmContext, {
        xValues: chronicleArrays.metricTimestampsMilliseconds,
        yValues: buildChronicleGoldenZoneExpectedValueBandValues(chronicleArrays, expectedValueThreshold),
        dataSeriesName: CHRONICLE_SERIES.evGateThreshold,
        isSorted: true,
        containsNaN: true
    });

    const goldenZoneExpectedValueBandSeries = new SplineMountainRenderableSeries(wasmContext, {
        yAxisId: 'yRegimeEv',
        xAxisId: 'xTime',
        dataSeries: goldenZoneExpectedValueBandDataSeries,
        seriesName: CHRONICLE_SERIES.evGateThreshold,
        stroke: CHRONICLE_METRIC_COLORS.expectedValue,
        strokeThickness: 1,
        fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
            { offset: 0, color: CHRONICLE_METRIC_COLORS.expectedValueBandFillHigh },
            { offset: 0.55, color: CHRONICLE_METRIC_COLORS.expectedValueBandFillMid },
            { offset: 1, color: CHRONICLE_METRIC_COLORS.expectedValueBandFillLow }
        ]),
        zeroLineY: expectedValueThreshold ?? 0,
        opacity: 0.95,
        effect: new GlowEffect(wasmContext, { intensity: 0.52, range: 2 })
    });

    const regimePfGateSubmergedBandSegments = buildRegimePfGateSubmergedBandSegmentsFromArrays(
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays,
        profitFactorThreshold
    );
    const regimePfGateSubmergedBandSegmentBundles = buildRegimePfGateSubmergedBandSegmentBundles(sci, wasmContext, regimePfGateSubmergedBandSegments, true);

    const goldenZoneProfitFactorBandDataSeries = new XyDataSeries(wasmContext, {
        xValues: chronicleArrays.metricTimestampsMilliseconds,
        yValues: buildChronicleGoldenZoneProfitFactorBandValues(chronicleArrays, profitFactorThreshold),
        dataSeriesName: CHRONICLE_SERIES.pfGateThreshold,
        isSorted: true,
        containsNaN: true
    });
    const goldenZoneProfitFactorBandSeries = new SplineMountainRenderableSeries(wasmContext, {
        yAxisId: 'yRegimePf',
        xAxisId: 'xTime',
        dataSeries: goldenZoneProfitFactorBandDataSeries,
        seriesName: CHRONICLE_SERIES.pfGateThreshold,
        stroke: CHRONICLE_METRIC_COLORS.profitFactor,
        strokeThickness: 1,
        fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
            { offset: 0, color: CHRONICLE_METRIC_COLORS.profitFactorBandFillHigh },
            { offset: 0.55, color: CHRONICLE_METRIC_COLORS.profitFactorBandFillMid },
            { offset: 1, color: CHRONICLE_METRIC_COLORS.profitFactorBandFillLow }
        ]),
        zeroLineY: profitFactorThreshold ?? 0,
        opacity: 0.95,
        effect: new GlowEffect(wasmContext, { intensity: 0.5, range: 2 })
    });

    const volumeColumnDataSeries = new XyDataSeries(wasmContext, {
        xValues: chronicleArrays.volumeBucketTimestampsMilliseconds,
        yValues: chronicleArrays.volumeBucketVerdictCounts,
        dataSeriesName: CHRONICLE_SERIES.volumeColumns,
        isSorted: true,
        containsNaN: true
    });

    const volumeColumnRenderableSeries = new FastColumnRenderableSeries(wasmContext, {
        yAxisId: 'yVol',
        xAxisId: 'xTime',
        dataSeries: volumeColumnDataSeries,
        seriesName: CHRONICLE_SERIES.volumeColumns,
        fillLinearGradient: new GradientParams(new Point(0, 0), new Point(0, 1), [
            { offset: 0, color: CHRONICLE_METRIC_COLORS.volumeColumnFillHigh },
            { offset: 1, color: CHRONICLE_METRIC_COLORS.volumeColumnFillLow }
        ]),
        stroke: CHRONICLE_METRIC_COLORS.volumeColumnStroke,
        strokeThickness: 1,
        cornerRadius: 4,
        opacity: 0.88
    });
    applyUniformColumnWidthForTimeBuckets(volumeColumnRenderableSeries, meta.bucket.granularity_seconds, sci);

    const averagePnlLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.averagePnlPercentageSeries,
        CHRONICLE_SERIES.averagePnlLine,
        CHRONICLE_METRIC_COLORS.pnl,
        'yPct',
        new GlowEffect(wasmContext, { intensity: 0.52, range: 2.5 })
    );
    averagePnlLineSeries.isVisible = false;

    const averageWinRateLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.averageWinRatePercentageSeries,
        CHRONICLE_SERIES.averageWinRateLine,
        CHRONICLE_METRIC_COLORS.winRate,
        'yPct',
        new GlowEffect(wasmContext, { intensity: 0.45, range: 2 })
    );

    const averageCortexPredictionWinRateLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.averageCortexPredictionWinRatePercentageSeries,
        CHRONICLE_SERIES.averageCortexPredictionWinRateLine,
        CHRONICLE_METRIC_COLORS.cortexPrediction,
        'yPct',
        new GlowEffect(wasmContext, { intensity: 0.42, range: 2 })
    );

    const expectedValueLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.expectedValuePerTradeUsdSeries,
        CHRONICLE_SERIES.expectedValueLine,
        CHRONICLE_METRIC_COLORS.expectedValue,
        'yUsd',
        new GlowEffect(wasmContext, { intensity: 0.48, range: 2 })
    );
    expectedValueLineSeries.isVisible = false;

    const profitFactorLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.profitFactorSeries,
        CHRONICLE_SERIES.profitFactorLine,
        CHRONICLE_METRIC_COLORS.profitFactor,
        'yPf',
        new GlowEffect(wasmContext, { intensity: 0.46, range: 2 })
    );
    profitFactorLineSeries.isVisible = false;

    const tradesPerHourLineSeries = createSplineMetricLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.closedVerdictsPerHourSeries,
        CHRONICLE_SERIES.tradesPerHourLine,
        CHRONICLE_METRIC_COLORS.tradesPerHour,
        'yVel',
        new GlowEffect(wasmContext, { intensity: 0.46, range: 2 })
    );
    tradesPerHourLineSeries.isVisible = false;

    const movingAveragePnlLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAveragePnlSeries,
        CHRONICLE_SERIES.smaPnlLine,
        CHRONICLE_METRIC_COLORS.pnl,
        'yPct'
    );
    movingAveragePnlLineSeries.isVisible = false;
    const movingAverageWinRateLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageWinRateSeries,
        CHRONICLE_SERIES.smaWinRateLine,
        CHRONICLE_METRIC_COLORS.winRate,
        'yPct'
    );
    movingAverageWinRateLineSeries.isVisible = false;
    const movingAverageCortexPredictionWinRateLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageCortexPredictionWinRatePercentageSeries,
        CHRONICLE_SERIES.smaCortexPredictionWinRateLine,
        CHRONICLE_METRIC_COLORS.cortexPrediction,
        'yPct'
    );
    movingAverageCortexPredictionWinRateLineSeries.isVisible = false;
    const movingAverageExpectedValueLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageExpectedValueSeries,
        CHRONICLE_SERIES.smaExpectedValueLine,
        CHRONICLE_METRIC_COLORS.smaExpectedValue,
        'yUsd'
    );
    movingAverageExpectedValueLineSeries.opacity = 1;
    const movingAverageProfitFactorLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageProfitFactorSeries,
        CHRONICLE_SERIES.smaProfitFactorLine,
        CHRONICLE_METRIC_COLORS.smaProfitFactor,
        'yPf'
    );
    movingAverageProfitFactorLineSeries.opacity = 1;
    const movingAverageTradesPerHourLineSeries = createSplineMovingAverageLine(
        sci,
        wasmContext,
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.movingAverageTradesPerHourSeries,
        CHRONICLE_SERIES.smaTradesPerHourLine,
        CHRONICLE_METRIC_COLORS.tradesPerHour,
        'yVel'
    );
    movingAverageTradesPerHourLineSeries.isVisible = false;

    const cortexCalibrationBandSegments = buildCortexCalibrationBandSegments(
        chronicleArrays.metricTimestampsMilliseconds,
        chronicleArrays.averageWinRatePercentageSeries,
        chronicleArrays.averageCortexPredictionWinRatePercentageSeries
    );
    const cortexCalibrationBandSegmentBundles = buildCortexCalibrationBandSegmentBundles(sci, wasmContext, cortexCalibrationBandSegments);

    const verdictCloudMarkerSize = 7;
    const profitableVerdictXyDataSeries = new XyDataSeries(wasmContext, {
        dataSeriesName: CHRONICLE_SERIES.winnerVerdictBubble,
        containsNaN: true
    });
    const lossVerdictXyDataSeries = new XyDataSeries(wasmContext, {
        dataSeriesName: CHRONICLE_SERIES.loserVerdictBubble,
        containsNaN: true
    });
    for (const row of chronicleArrays.verdictCloudProfitablePoints) {
        profitableVerdictXyDataSeries.append(row.x, row.y, buildVerdictCloudPointMetadata(row));
    }
    for (const row of chronicleArrays.verdictCloudLossPoints) {
        lossVerdictXyDataSeries.append(row.x, row.y, buildVerdictCloudPointMetadata(row));
    }

    const profitableVerdictBubbleSeries = new XyScatterRenderableSeries(wasmContext, {
        yAxisId: 'yPct',
        xAxisId: 'xTime',
        dataSeries: profitableVerdictXyDataSeries,
        seriesName: CHRONICLE_SERIES.winnerVerdictBubble,
        pointMarker: new EllipsePointMarker(wasmContext, {
            width: verdictCloudMarkerSize,
            height: verdictCloudMarkerSize,
            stroke: CHRONICLE_METRIC_COLORS.winnerVerdictStroke,
            fill: CHRONICLE_METRIC_COLORS.winnerVerdictFill,
            strokeThickness: 1
        }),
        stroke: CHRONICLE_METRIC_COLORS.winnerVerdictStroke,
        strokeThickness: 0,
        opacity: 0.88,
        effect: new GlowEffect(wasmContext, { intensity: 0.65, range: 2 })
    });

    const lossVerdictBubbleSeries = new XyScatterRenderableSeries(wasmContext, {
        yAxisId: 'yPct',
        xAxisId: 'xTime',
        dataSeries: lossVerdictXyDataSeries,
        seriesName: CHRONICLE_SERIES.loserVerdictBubble,
        pointMarker: new EllipsePointMarker(wasmContext, {
            width: verdictCloudMarkerSize,
            height: verdictCloudMarkerSize,
            stroke: CHRONICLE_METRIC_COLORS.loserVerdictStroke,
            fill: CHRONICLE_METRIC_COLORS.loserVerdictFill,
            strokeThickness: 1
        }),
        stroke: CHRONICLE_METRIC_COLORS.loserVerdictStroke,
        strokeThickness: 0,
        opacity: 0.84,
        effect: new GlowEffect(wasmContext, { intensity: 0.55, range: 2 })
    });

    sciChartSurface.renderableSeries.add(
        volumeColumnRenderableSeries,
        averagePnlLineSeries,
        averageWinRateLineSeries,
        averageCortexPredictionWinRateLineSeries,
        expectedValueLineSeries,
        profitFactorLineSeries,
        tradesPerHourLineSeries,
        movingAveragePnlLineSeries,
        movingAverageWinRateLineSeries,
        movingAverageCortexPredictionWinRateLineSeries,
        movingAverageExpectedValueLineSeries,
        ...regimeEvGateSubmergedBandSegmentBundles.map((bundle) => bundle.series),
        goldenZoneExpectedValueBandSeries,
        movingAverageProfitFactorLineSeries,
        ...regimePfGateSubmergedBandSegmentBundles.map((bundle) => bundle.series),
        goldenZoneProfitFactorBandSeries,
        movingAverageTradesPerHourLineSeries,
        ...cortexCalibrationBandSegmentBundles.map((bundle) => bundle.series),
        lossVerdictBubbleSeries,
        profitableVerdictBubbleSeries
    );
    sciChartSurface.annotations.add(goldenZoneExpectedValueAnnotation, goldenZoneProfitFactorAnnotation);

    const sweep = { duration: 2200, ease: easing.outExpo };
    volumeColumnRenderableSeries.runAnimation(new ColumnAnimation({ ...sweep, dataSeries: volumeColumnDataSeries }));
    for (const series of [
        averagePnlLineSeries,
        averageWinRateLineSeries,
        averageCortexPredictionWinRateLineSeries,
        expectedValueLineSeries,
        profitFactorLineSeries,
        tradesPerHourLineSeries,
        movingAveragePnlLineSeries,
        movingAverageWinRateLineSeries,
        movingAverageCortexPredictionWinRateLineSeries,
        movingAverageExpectedValueLineSeries,
        movingAverageProfitFactorLineSeries,
        movingAverageTradesPerHourLineSeries
    ]) {
        series.runAnimation(new SweepAnimation(sweep));
    }
    profitableVerdictBubbleSeries.runAnimation(new SweepAnimation(sweep));
    lossVerdictBubbleSeries.runAnimation(new SweepAnimation(sweep));

    sciChartSurface.chartModifiers.add(
        new ZoomPanModifier(),
        new MouseWheelZoomModifier(),
        new ZoomExtentsModifier(),
        new CursorModifier({
            crosshairStroke: CHRONICLE_METRIC_COLORS.crosshair,
            crosshairStrokeThickness: 1,
            showTooltip: true,
            tooltipContainerBackground: CHRONICLE_METRIC_COLORS.tooltipContainerBackground,
            tooltipTextStroke: CHRONICLE_METRIC_COLORS.tooltipText,
            axisLabelFill: CHRONICLE_METRIC_COLORS.tooltipAxisLabelFill,
            tooltipSvgTemplate: (seriesInfos, svgAnnotation) =>
                buildChronicleCursorTooltipSvg(sci as unknown as ChronicleAdjustTooltipPositionHost, seriesInfos as never, svgAnnotation)
        }),
        new LegendModifier({
            showCheckboxes: true,
            showSeriesMarkers: true,
            showLegend: false,
            placement: ELegendPlacement.TopRight,
            margin: 10,
            backgroundColor: CHRONICLE_METRIC_COLORS.legendBackground,
            textColor: CHRONICLE_METRIC_COLORS.legendText
        })
    );

    return {
        volumeColumnDataSeries,
        volumeColumnRenderableSeries,
        goldenZoneExpectedValueBandDataSeries,
        goldenZoneProfitFactorBandDataSeries,
        goldenZoneExpectedValueBandSeries,
        goldenZoneProfitFactorBandSeries,
        regimeEvGateSubmergedBandSegmentBundles,
        regimePfGateSubmergedBandSegmentBundles,
        metricLineRenderableSeries: [
            averagePnlLineSeries,
            averageWinRateLineSeries,
            averageCortexPredictionWinRateLineSeries,
            expectedValueLineSeries,
            profitFactorLineSeries,
            tradesPerHourLineSeries
        ],
        movingAverageLineRenderableSeries: [
            movingAveragePnlLineSeries,
            movingAverageWinRateLineSeries,
            movingAverageCortexPredictionWinRateLineSeries,
            movingAverageExpectedValueLineSeries,
            movingAverageProfitFactorLineSeries,
            movingAverageTradesPerHourLineSeries
        ],
        profitableVerdictXyDataSeries,
        lossVerdictXyDataSeries,
        goldenZoneExpectedValueAnnotation,
        goldenZoneProfitFactorAnnotation,
        cortexCalibrationBandSegmentBundles
    };
}
