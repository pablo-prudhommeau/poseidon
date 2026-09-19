import type { AxisBase2D, IDataSeries, IRenderableSeries, LabelProvider, SciChartOverview, SciChartSurface } from 'scichart';
import type { ChronicleChartModel, SciChartModule } from '../data/trading-shadowing-verdict-chronicle.models';
import {
    formatChronicleAxisLocalDateTimeMilliseconds,
    formatChronicleAxisTickLabelMilliseconds
} from '../data/trading-shadowing-verdict-chronicle-arrays.utils';
import { CHRONICLE_METRIC_COLORS } from '../data/trading-shadowing-verdict-chronicle-metrics.catalog';
import { CHRONICLE_SERIES } from '../data/trading-shadowing-verdict-chronicle-series-names';

type ChronicleNamedRenderableSeries = IRenderableSeries & { seriesName?: string };
type ChronicleOverviewTickAxis = {
    maxAutoTicks: number;
    minTicks: number;
};
type ChronicleOverviewMountainSeries = IRenderableSeries & { zeroLineY: number };

const CHRONICLE_CHART_HOST_ELEMENT_ID: string = 'trading-shadowing-verdict-chronicle-chart-host';
const CHRONICLE_OVERVIEW_HOST_ELEMENT_ID: string = 'trading-shadowing-verdict-chronicle-overview-host';
const OVERVIEW_RANGE_HANDLE_WIDTH_PIXELS: number = 16;
const OVERVIEW_RANGE_HANDLE_HALF_WIDTH_PIXELS: number = 8;
const OVERVIEW_RANGE_HANDLE_HEIGHT: string = '46%';
const OVERVIEW_RANGE_HANDLE_Y_COORDINATE: string = '27%';
const OVERVIEW_RANGE_HANDLE_GRIP_TOP: string = '38%';
const OVERVIEW_RANGE_HANDLE_GRIP_BOTTOM: string = '62%';
const OVERVIEW_RANGE_HANDLE_GRIP_INSET_START_PIXELS: number = 5.5;
const OVERVIEW_RANGE_HANDLE_GRIP_INSET_END_PIXELS: number = 10.5;

export function assignChronicleSciChartHostElementIds(chartHost: HTMLDivElement, overviewHost: HTMLDivElement): void {
    chartHost.id = CHRONICLE_CHART_HOST_ELEMENT_ID;
    overviewHost.id = CHRONICLE_OVERVIEW_HOST_ELEMENT_ID;
}

function readChronicleRenderableSeriesName(series: IRenderableSeries): string {
    const namedSeries: ChronicleNamedRenderableSeries = series;
    const seriesName: string = (namedSeries.seriesName ?? '').trim();
    if (seriesName) {
        return seriesName;
    }
    return (series.dataSeries?.dataSeriesName ?? '').trim();
}

function readFirstAxis(axisCollection: { asArray: () => AxisBase2D[] }): AxisBase2D | undefined {
    const axes: AxisBase2D[] = axisCollection.asArray();
    return axes.length > 0 ? axes[0] : undefined;
}

function copyXyDataSeriesValues(source: IDataSeries): { xValues: number[]; yValues: number[] } {
    const pointCount: number = source.count();
    const nativeXValues = source.getNativeXValues();
    const nativeYValues = source.getNativeYValues();
    const xValues: number[] = [];
    const yValues: number[] = [];
    for (let index = 0; index < pointCount; index++) {
        xValues.push(source.getNativeValue(nativeXValues, index));
        yValues.push(source.getNativeValue(nativeYValues, index));
    }
    return { xValues, yValues };
}

function buildChronicleOverviewRangeHandleSvg(handleLeftPixel: number): string {
    const gripStartPixel: number = handleLeftPixel + OVERVIEW_RANGE_HANDLE_GRIP_INSET_START_PIXELS;
    const gripEndPixel: number = handleLeftPixel + OVERVIEW_RANGE_HANDLE_GRIP_INSET_END_PIXELS;
    return `<rect x="${handleLeftPixel}" y="${OVERVIEW_RANGE_HANDLE_Y_COORDINATE}" width="${OVERVIEW_RANGE_HANDLE_WIDTH_PIXELS}" height="${OVERVIEW_RANGE_HANDLE_HEIGHT}" rx="2" fill="${CHRONICLE_METRIC_COLORS.overviewRangeHandleFill}" stroke="${CHRONICLE_METRIC_COLORS.overviewRangeHandleStroke}" stroke-width="1" />
        <line x1="${gripStartPixel}" y1="${OVERVIEW_RANGE_HANDLE_GRIP_TOP}" x2="${gripStartPixel}" y2="${OVERVIEW_RANGE_HANDLE_GRIP_BOTTOM}" stroke="${CHRONICLE_METRIC_COLORS.overviewRangeHandleGrip}" stroke-width="1.25" stroke-linecap="round" />
        <line x1="${gripEndPixel}" y1="${OVERVIEW_RANGE_HANDLE_GRIP_TOP}" x2="${gripEndPixel}" y2="${OVERVIEW_RANGE_HANDLE_GRIP_BOTTOM}" stroke="${CHRONICLE_METRIC_COLORS.overviewRangeHandleGrip}" stroke-width="1.25" stroke-linecap="round" />`;
}

function buildChronicleOverviewRangeSelectionAdornerSvg(x1: number, y1: number, x2: number, y2: number): string {
    const width: number = x2 - x1;
    const height: number = y2 - y1;
    const leftHandleLeftPixel: number = 0 - OVERVIEW_RANGE_HANDLE_HALF_WIDTH_PIXELS;
    const rightHandleLeftPixel: number = width - OVERVIEW_RANGE_HANDLE_HALF_WIDTH_PIXELS;
    return `<svg x="${x1}" y="${y1}" width="${width}px" height="${height}px" viewBox="0 0 ${width} ${height}" overflow="visible" xmlns="http://www.w3.org/2000/svg">
        <rect x="0" y="0" width="${width}" height="${height}" fill="${CHRONICLE_METRIC_COLORS.overviewSelectedFill}" />
        ${buildChronicleOverviewRangeHandleSvg(leftHandleLeftPixel)}
        ${buildChronicleOverviewRangeHandleSvg(rightHandleLeftPixel)}
        </svg>`;
}

function createChronicleOverviewWalletMountainSeries(
    sci: SciChartModule,
    overviewSurface: SciChartSurface,
    dataSeries: InstanceType<SciChartModule['XyDataSeries']>,
    overviewXAxisId: string | undefined,
    overviewYAxisId: string | undefined
): InstanceType<SciChartModule['SplineMountainRenderableSeries']> {
    const { SplineMountainRenderableSeries } = sci;
    return new SplineMountainRenderableSeries(overviewSurface.webAssemblyContext2D, {
        dataSeries,
        seriesName: CHRONICLE_SERIES.portfolioWalletValueLine,
        stroke: CHRONICLE_METRIC_COLORS.transparent,
        strokeThickness: 1,
        fill: CHRONICLE_METRIC_COLORS.overviewMountainFillHigh,
        zeroLineY: 0,
        opacity: 1,
        xAxisId: overviewXAxisId,
        yAxisId: overviewYAxisId,
        isVisible: true
    });
}

function createChronicleOverviewWalletGlowLineSeries(
    sci: SciChartModule,
    overviewSurface: SciChartSurface,
    dataSeries: InstanceType<SciChartModule['XyDataSeries']>,
    overviewXAxisId: string | undefined,
    overviewYAxisId: string | undefined
): InstanceType<SciChartModule['SplineLineRenderableSeries']> {
    const { GlowEffect, SplineLineRenderableSeries } = sci;
    return new SplineLineRenderableSeries(overviewSurface.webAssemblyContext2D, {
        dataSeries,
        seriesName: CHRONICLE_SERIES.portfolioWalletValueLine,
        stroke: CHRONICLE_METRIC_COLORS.portfolioWalletValue,
        strokeThickness: 2.5,
        opacity: 0.95,
        effect: new GlowEffect(overviewSurface.webAssemblyContext2D, { intensity: 0.46, range: 2 }),
        xAxisId: overviewXAxisId,
        yAxisId: overviewYAxisId,
        isVisible: true
    });
}

function isChronicleOverviewMountainSeries(series: IRenderableSeries): series is ChronicleOverviewMountainSeries {
    const mountainSeries: ChronicleOverviewMountainSeries = series as ChronicleOverviewMountainSeries;
    return typeof mountainSeries.zeroLineY === 'number';
}

function alignChronicleOverviewMountainFillToAxisFloor(overview: SciChartOverview): void {
    const axisFloor: number = overview.overviewYAxis.visibleRange.min;
    const overviewSeriesList: IRenderableSeries[] = overview.overviewSciChartSurface.renderableSeries.asArray();
    for (const series of overviewSeriesList) {
        if (isChronicleOverviewMountainSeries(series)) {
            series.zeroLineY = axisFloor;
        }
    }
}

function overviewSurfaceHasSplineLineSeries(sci: SciChartModule, overviewSurface: SciChartSurface): boolean {
    return overviewSurface.renderableSeries.asArray().some((series: IRenderableSeries): boolean => {
        return series instanceof sci.SplineLineRenderableSeries;
    });
}

function ensureChronicleOverviewWalletGlowLine(
    sci: SciChartModule,
    overviewSurface: SciChartSurface,
    dataSeries: InstanceType<SciChartModule['XyDataSeries']>
): void {
    if (overviewSurfaceHasSplineLineSeries(sci, overviewSurface)) {
        return;
    }
    const overviewXAxis: AxisBase2D | undefined = readFirstAxis(overviewSurface.xAxes);
    const overviewYAxis: AxisBase2D | undefined = readFirstAxis(overviewSurface.yAxes);
    overviewSurface.renderableSeries.add(createChronicleOverviewWalletGlowLineSeries(sci, overviewSurface, dataSeries, overviewXAxis?.id, overviewYAxis?.id));
}

export function transformChronicleOverviewRenderableSeries(
    sci: SciChartModule,
    parentSeries: IRenderableSeries,
    overviewSurface: SciChartSurface | undefined
): IRenderableSeries | undefined {
    try {
        if (!overviewSurface || !parentSeries.dataSeries) {
            return undefined;
        }
        if (readChronicleRenderableSeriesName(parentSeries) !== CHRONICLE_SERIES.portfolioWalletValueLine) {
            return undefined;
        }
        const overviewXAxis: AxisBase2D | undefined = readFirstAxis(overviewSurface.xAxes);
        const overviewYAxis: AxisBase2D | undefined = readFirstAxis(overviewSurface.yAxes);
        if (!overviewXAxis || !overviewYAxis) {
            return undefined;
        }
        const copiedValues: { xValues: number[]; yValues: number[] } = copyXyDataSeriesValues(parentSeries.dataSeries);
        const { XyDataSeries } = sci;
        const overviewDataSeries: InstanceType<SciChartModule['XyDataSeries']> = new XyDataSeries(overviewSurface.webAssemblyContext2D, {
            xValues: copiedValues.xValues,
            yValues: copiedValues.yValues,
            dataSeriesName: CHRONICLE_SERIES.portfolioWalletValueLine,
            isSorted: true,
            containsNaN: false
        });
        return createChronicleOverviewWalletMountainSeries(sci, overviewSurface, overviewDataSeries, overviewXAxis.id, overviewYAxis.id);
    } catch {
        return undefined;
    }
}

export function configureChronicleOverviewSurface(overview: SciChartOverview): void {
    const axisLabelProvider: LabelProvider = overview.overviewXAxis.labelProvider as LabelProvider;
    axisLabelProvider.formatLabel = formatChronicleAxisTickLabelMilliseconds;
    axisLabelProvider.formatCursorLabel = formatChronicleAxisLocalDateTimeMilliseconds;
    const overviewYAxis: ChronicleOverviewTickAxis = overview.overviewYAxis as unknown as ChronicleOverviewTickAxis;
    overviewYAxis.minTicks = 4;
    overviewYAxis.maxAutoTicks = 4;
    alignChronicleOverviewMountainFillToAxisFloor(overview);
    overview.overviewYAxis.visibleRangeChanged.subscribe(() => {
        alignChronicleOverviewMountainFillToAxisFloor(overview);
    });
    try {
        overview.rangeSelectionModifier.rangeSelectionAnnotation.adornerSvgStringTemplate = buildChronicleOverviewRangeSelectionAdornerSvg;
        overview.rangeSelectionModifier.rangeSelectionAnnotation.opacity = 1;
    } catch {}
}

export function readChronicleOverviewWalletValueDataSeries(overview: SciChartOverview): InstanceType<SciChartModule['XyDataSeries']> | undefined {
    const overviewSeriesList: IRenderableSeries[] = overview.overviewSciChartSurface.renderableSeries.asArray();
    const walletValueSeries: IRenderableSeries | undefined = overviewSeriesList.find((series: IRenderableSeries): boolean => {
        return readChronicleRenderableSeriesName(series) === CHRONICLE_SERIES.portfolioWalletValueLine;
    });
    if (!walletValueSeries) {
        return undefined;
    }
    return walletValueSeries.dataSeries as InstanceType<SciChartModule['XyDataSeries']>;
}

export function ensureChronicleOverviewWalletValueDataSeries(
    sci: SciChartModule,
    parentSurface: SciChartSurface,
    overview: SciChartOverview
): InstanceType<SciChartModule['XyDataSeries']> {
    const existingDataSeries: InstanceType<SciChartModule['XyDataSeries']> | undefined = readChronicleOverviewWalletValueDataSeries(overview);
    if (existingDataSeries) {
        ensureChronicleOverviewWalletGlowLine(sci, overview.overviewSciChartSurface, existingDataSeries);
        alignChronicleOverviewMountainFillToAxisFloor(overview);
        return existingDataSeries;
    }
    const parentWalletSeries: IRenderableSeries | undefined = parentSurface.renderableSeries.asArray().find((series: IRenderableSeries): boolean => {
        return readChronicleRenderableSeriesName(series) === CHRONICLE_SERIES.portfolioWalletValueLine;
    });
    if (parentWalletSeries) {
        const clonedSeries: IRenderableSeries | undefined = transformChronicleOverviewRenderableSeries(
            sci,
            parentWalletSeries,
            overview.overviewSciChartSurface
        );
        if (clonedSeries) {
            overview.overviewSciChartSurface.renderableSeries.add(clonedSeries);
            const clonedDataSeries: InstanceType<SciChartModule['XyDataSeries']> = clonedSeries.dataSeries as InstanceType<SciChartModule['XyDataSeries']>;
            ensureChronicleOverviewWalletGlowLine(sci, overview.overviewSciChartSurface, clonedDataSeries);
            alignChronicleOverviewMountainFillToAxisFloor(overview);
            return clonedDataSeries;
        }
    }
    const overviewSurface: SciChartSurface = overview.overviewSciChartSurface;
    const overviewXAxis: AxisBase2D | undefined = readFirstAxis(overviewSurface.xAxes);
    const overviewYAxis: AxisBase2D | undefined = readFirstAxis(overviewSurface.yAxes);
    const { XyDataSeries } = sci;
    const emptyDataSeries: InstanceType<SciChartModule['XyDataSeries']> = new XyDataSeries(overviewSurface.webAssemblyContext2D, {
        xValues: [],
        yValues: [],
        dataSeriesName: CHRONICLE_SERIES.portfolioWalletValueLine,
        isSorted: true,
        containsNaN: false
    });
    overviewSurface.renderableSeries.add(
        createChronicleOverviewWalletMountainSeries(sci, overviewSurface, emptyDataSeries, overviewXAxis?.id, overviewYAxis?.id)
    );
    ensureChronicleOverviewWalletGlowLine(sci, overviewSurface, emptyDataSeries);
    alignChronicleOverviewMountainFillToAxisFloor(overview);
    return emptyDataSeries;
}

export function deleteChronicleOverview(model: ChronicleChartModel): void {
    model.sciChartOverview.delete();
}
