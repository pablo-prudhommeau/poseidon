import type { TSciChart } from 'scichart';
import type {
    ChronicleCartesianPoint,
    ChronicleChartModel,
    ChronicleSellPathSegmentBundle,
    ChronicleVerdictBubblePointMetadata,
    SciChartModule
} from '../data/trading-shadowing-verdict-chronicle.models';
import { CHRONICLE_DEFAULT_VISIBLE_SERIES } from '../data/trading-shadowing-verdict-chronicle-metrics.catalog';

export function excludeChronicleSeriesFromCursorHitTest(
    cursorModifier: ChronicleChartModel['cursorModifier'] | undefined,
    series: InstanceType<SciChartModule['FastLineRenderableSeries']> | InstanceType<SciChartModule['XyScatterRenderableSeries']>
): void {
    if (!cursorModifier) {
        return;
    }
    cursorModifier.includeSeries(series, false);
}

function buildSellPathPointMetadata(point: ChronicleCartesianPoint): ChronicleVerdictBubblePointMetadata {
    return {
        cortexProbability: point.cortexProbability,
        orderNotionalUsd: point.orderNotionalUsd,
        tokenSymbol: point.tokenSymbol,
        executionStatus: point.executionStatus,
        pnlUsd: point.pnlUsd,
        pathFade: point.pathFade,
        realizedPnlPercentage: point.realizedPnlPercentage,
        blockchainNetwork: point.blockchainNetwork,
        tokenAddress: point.tokenAddress,
        isSelected: false
    };
}

function createSellPathFadePaletteProvider(sci: SciChartModule, stroke: string): InstanceType<SciChartModule['DefaultPaletteProvider']> {
    const defaultPaletteProviderConstructor = sci.DefaultPaletteProvider as unknown as new () => Record<string, unknown>;

    class SellPathFadePaletteProvider extends defaultPaletteProviderConstructor {
        strokePaletteMode: unknown;

        constructor() {
            super();
            this.strokePaletteMode = sci.EStrokePaletteMode.GRADIENT;
        }

        overrideStrokeArgb(
            _xValue: number,
            _yValue: number,
            _index: number,
            _opacity?: number,
            metadata?: ChronicleVerdictBubblePointMetadata
        ): number | undefined {
            const pathFade = metadata?.pathFade;
            const fadeAlpha = typeof pathFade === 'number' && Number.isFinite(pathFade) ? pathFade : 0.85;
            const opacityByte = Math.round(Math.max(0, Math.min(1, fadeAlpha)) * 255);
            return sci.parseColorToUIntArgb(stroke, opacityByte);
        }
    }

    return new SellPathFadePaletteProvider() as unknown as InstanceType<SciChartModule['DefaultPaletteProvider']>;
}

function appendSellPathPoints(dataSeries: InstanceType<SciChartModule['XyDataSeries']>, path: ChronicleCartesianPoint[]): void {
    for (const point of path) {
        if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) {
            continue;
        }
        dataSeries.append(point.x, point.y, buildSellPathPointMetadata(point));
    }
}

function createSellPathSegmentBundle(
    sci: SciChartModule,
    wasmContext: TSciChart,
    path: ChronicleCartesianPoint[],
    seriesName: string,
    stroke: string,
    isVisible: boolean
): ChronicleSellPathSegmentBundle {
    const { FastLineRenderableSeries, GlowEffect, XyDataSeries } = sci;
    const dataSeries = new XyDataSeries(wasmContext, {
        dataSeriesName: seriesName,
        containsNaN: false,
        isSorted: true,
        dataEvenlySpacedInX: false
    });
    appendSellPathPoints(dataSeries, path);
    const series = new FastLineRenderableSeries(wasmContext, {
        yAxisId: 'yPct',
        xAxisId: 'xTime',
        dataSeries,
        seriesName,
        stroke,
        strokeThickness: 2.2,
        strokeDashArray: [4, 5],
        opacity: 0.95,
        resamplingMode: sci.EResamplingMode.None,
        paletteProvider: createSellPathFadePaletteProvider(sci, stroke),
        effect: new GlowEffect(wasmContext, { intensity: 0.7, range: 3 })
    });
    series.isVisible = isVisible;
    return { dataSeries, series };
}

function synchronizeSellPathSegmentBundle(bundle: ChronicleSellPathSegmentBundle, path: ChronicleCartesianPoint[]): void {
    bundle.dataSeries.clear();
    appendSellPathPoints(bundle.dataSeries, path);
}

export function buildChronicleSellPathSegmentBundles(
    sci: SciChartModule,
    wasmContext: TSciChart,
    paths: ChronicleCartesianPoint[][],
    seriesName: string,
    stroke: string,
    isVisible: boolean = true
): ChronicleSellPathSegmentBundle[] {
    return paths.filter((path) => path.length >= 2).map((path) => createSellPathSegmentBundle(sci, wasmContext, path, seriesName, stroke, isVisible));
}

export function synchronizeChronicleSellPathSegmentBundles(
    model: ChronicleChartModel,
    bundles: ChronicleSellPathSegmentBundle[],
    paths: ChronicleCartesianPoint[][],
    seriesName: string,
    stroke: string
): void {
    const drawablePaths = paths.filter((path) => path.length >= 2);
    const targetCount = drawablePaths.length;
    let isVisible = CHRONICLE_DEFAULT_VISIBLE_SERIES.includes(seriesName);
    if (bundles.length > 0) {
        isVisible = bundles[0].series.isVisible === true;
    }

    for (let index = 0; index < targetCount; index++) {
        const path = drawablePaths[index];
        if (index < bundles.length) {
            synchronizeSellPathSegmentBundle(bundles[index], path);
            bundles[index].series.isVisible = isVisible;
            continue;
        }
        const bundle = createSellPathSegmentBundle(model.sci, model.wasmContext, path, seriesName, stroke, isVisible);
        excludeChronicleSeriesFromCursorHitTest(model.cursorModifier, bundle.series);
        model.sciChartSurface.renderableSeries.add(bundle.series);
        bundles.push(bundle);
    }

    for (let index = targetCount; index < bundles.length; index++) {
        bundles[index].dataSeries.clear();
        bundles[index].series.isVisible = false;
    }
}
