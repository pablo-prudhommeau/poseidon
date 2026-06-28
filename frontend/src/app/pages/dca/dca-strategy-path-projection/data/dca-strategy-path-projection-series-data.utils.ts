import { DcaOrderPayload, DcaStrategyPayload } from '../../../../core/models';
import { resolveProjectedLivePriceMultiplier } from '../../dca-price-scaling.utils';
import {
    DcaStrategyPathBandSegment,
    DcaStrategyPathBacktestingSeriesBundle,
    DcaStrategyPathChartPoint,
    DcaStrategyPathChartSeriesBundle,
    DcaStrategyPathProjectedSeriesBundle
} from './dca-strategy-path-projection.models';

const MIN_BAND_SEGMENT_POINTS = 2;
const UNSCALED_BACKTEST_PRICE_MULTIPLIER = 1;

function resolveExecutedOrders(executionOrders: DcaOrderPayload[]): DcaOrderPayload[] {
    return executionOrders
        .filter(
            (executionOrder: DcaOrderPayload) =>
                executionOrder.order_status === 'EXECUTED' &&
                executionOrder.executed_at !== null &&
                executionOrder.executed_at !== undefined &&
                executionOrder.actual_execution_price !== null &&
                executionOrder.actual_execution_price !== undefined
        )
        .sort(
            (orderA: DcaOrderPayload, orderB: DcaOrderPayload) =>
                new Date(orderA.executed_at as string).getTime() - new Date(orderB.executed_at as string).getTime()
        );
}

function mapHistoricalTimestampToLiveWindow(
    historicalTimestampMilliseconds: number,
    historicalStartTimestampMilliseconds: number,
    historicalEndTimestampMilliseconds: number,
    liveStartTimestampMilliseconds: number,
    liveEndTimestampMilliseconds: number
): number {
    const historicalDurationMilliseconds: number = historicalEndTimestampMilliseconds - historicalStartTimestampMilliseconds;
    if (historicalDurationMilliseconds <= 0) {
        return liveStartTimestampMilliseconds;
    }
    const timePercentage: number = (historicalTimestampMilliseconds - historicalStartTimestampMilliseconds) / historicalDurationMilliseconds;
    return liveStartTimestampMilliseconds + timePercentage * (liveEndTimestampMilliseconds - liveStartTimestampMilliseconds);
}

function mapBacktestPointsToSourceCalendar(
    backtestSeries: { timestamp_iso: string; execution_price: number; average_purchase_price: number }[],
    valueSelector: (backtestPoint: { timestamp_iso: string; execution_price: number; average_purchase_price: number }) => number,
    priceMultiplier: number
): DcaStrategyPathChartPoint[] {
    return backtestSeries.map((backtestPoint) => ({
        timestampMilliseconds: new Date(backtestPoint.timestamp_iso).getTime(),
        value: valueSelector(backtestPoint) * priceMultiplier
    }));
}

function mapBacktestPointsToLiveWindow(
    backtestSeries: { timestamp_iso: string; execution_price: number; average_purchase_price: number }[],
    valueSelector: (backtestPoint: { timestamp_iso: string; execution_price: number; average_purchase_price: number }) => number,
    strategy: DcaStrategyPayload,
    priceMultiplier: number
): DcaStrategyPathChartPoint[] {
    if (backtestSeries.length === 0) {
        return [];
    }

    const historicalStartTimestampMilliseconds: number = new Date(backtestSeries[0].timestamp_iso).getTime();
    const historicalEndTimestampMilliseconds: number = new Date(backtestSeries[backtestSeries.length - 1].timestamp_iso).getTime();
    const liveStartTimestampMilliseconds: number = new Date(strategy.strategy_start_date).getTime();
    const liveEndTimestampMilliseconds: number = new Date(strategy.strategy_end_date).getTime();

    return backtestSeries.map((backtestPoint) => ({
        timestampMilliseconds: mapHistoricalTimestampToLiveWindow(
            new Date(backtestPoint.timestamp_iso).getTime(),
            historicalStartTimestampMilliseconds,
            historicalEndTimestampMilliseconds,
            liveStartTimestampMilliseconds,
            liveEndTimestampMilliseconds
        ),
        value: valueSelector(backtestPoint) * priceMultiplier
    }));
}

function interpolateValueAtTimestamp(chartPoints: DcaStrategyPathChartPoint[], timestampMilliseconds: number): number {
    if (chartPoints.length === 0) {
        return Number.NaN;
    }
    if (timestampMilliseconds <= chartPoints[0].timestampMilliseconds) {
        return chartPoints[0].value;
    }
    const lastPoint: DcaStrategyPathChartPoint = chartPoints[chartPoints.length - 1];
    if (timestampMilliseconds >= lastPoint.timestampMilliseconds) {
        return lastPoint.value;
    }

    for (let index = 0; index < chartPoints.length - 1; index++) {
        const leftPoint: DcaStrategyPathChartPoint = chartPoints[index];
        const rightPoint: DcaStrategyPathChartPoint = chartPoints[index + 1];
        if (timestampMilliseconds >= leftPoint.timestampMilliseconds && timestampMilliseconds <= rightPoint.timestampMilliseconds) {
            const span: number = rightPoint.timestampMilliseconds - leftPoint.timestampMilliseconds;
            if (span <= 0) {
                return leftPoint.value;
            }
            const weight: number = (timestampMilliseconds - leftPoint.timestampMilliseconds) / span;
            return leftPoint.value + (rightPoint.value - leftPoint.value) * weight;
        }
    }

    return Number.NaN;
}

function buildBandSegmentsFromRoleSeries(
    timelinePoints: DcaStrategyPathChartPoint[],
    primaryPoints: DcaStrategyPathChartPoint[],
    secondaryPoints: DcaStrategyPathChartPoint[],
    maximumTimestampMilliseconds: number
): DcaStrategyPathBandSegment[] {
    const segments: DcaStrategyPathBandSegment[] = [];
    let currentSegment: DcaStrategyPathBandSegment | null = null;

    const flushCurrentSegment = (): void => {
        if (currentSegment && currentSegment.xValues.length >= MIN_BAND_SEGMENT_POINTS) {
            segments.push(currentSegment);
        }
        currentSegment = null;
    };

    for (const timelinePoint of timelinePoints) {
        if (timelinePoint.timestampMilliseconds > maximumTimestampMilliseconds) {
            break;
        }

        const primaryValue: number = interpolateValueAtTimestamp(primaryPoints, timelinePoint.timestampMilliseconds);
        const secondaryValue: number = interpolateValueAtTimestamp(secondaryPoints, timelinePoint.timestampMilliseconds);
        if (!Number.isFinite(primaryValue) || !Number.isFinite(secondaryValue)) {
            flushCurrentSegment();
            continue;
        }

        if (!currentSegment) {
            currentSegment = { xValues: [], yValues: [], y1Values: [] };
        }
        currentSegment.xValues.push(timelinePoint.timestampMilliseconds);
        currentSegment.yValues.push(primaryValue);
        currentSegment.y1Values.push(secondaryValue);
    }

    flushCurrentSegment();
    return segments;
}

export function buildProjectedStrategyPathSeries(strategy: DcaStrategyPayload): DcaStrategyPathProjectedSeriesBundle | null {
    const backtestPayload = strategy.historical_backtest_payload;
    if (!backtestPayload) {
        return null;
    }

    const baselineSeries = backtestPayload.dumb_dca_series;
    const smartSeries = backtestPayload.smart_dca_series;
    if (!baselineSeries || baselineSeries.length === 0 || !smartSeries || smartSeries.length === 0) {
        return null;
    }

    const priceMultiplier: number = resolveProjectedLivePriceMultiplier(strategy);

    return {
        projectedMarketPrice: mapBacktestPointsToLiveWindow(smartSeries, (backtestPoint) => backtestPoint.execution_price, strategy, priceMultiplier),
        projectedBaselineAverageUnitPrice: mapBacktestPointsToLiveWindow(
            baselineSeries,
            (backtestPoint) => backtestPoint.average_purchase_price,
            strategy,
            priceMultiplier
        ),
        projectedSmartAverageUnitPrice: mapBacktestPointsToLiveWindow(
            smartSeries,
            (backtestPoint) => backtestPoint.average_purchase_price,
            strategy,
            priceMultiplier
        )
    };
}

export function buildBacktestingStrategyPathSeries(strategy: DcaStrategyPayload): DcaStrategyPathBacktestingSeriesBundle | null {
    const backtestPayload = strategy.historical_backtest_payload;
    if (!backtestPayload) {
        return null;
    }

    const baselineSeries = backtestPayload.dumb_dca_series;
    const smartSeries = backtestPayload.smart_dca_series;
    if (!baselineSeries || baselineSeries.length === 0 || !smartSeries || smartSeries.length === 0) {
        return null;
    }

    return {
        backtestingMarketPrice: mapBacktestPointsToSourceCalendar(
            smartSeries,
            (backtestPoint) => backtestPoint.execution_price,
            UNSCALED_BACKTEST_PRICE_MULTIPLIER
        ),
        backtestingBaselineAverageUnitPrice: mapBacktestPointsToSourceCalendar(
            baselineSeries,
            (backtestPoint) => backtestPoint.average_purchase_price,
            UNSCALED_BACKTEST_PRICE_MULTIPLIER
        ),
        backtestingSmartAverageUnitPrice: mapBacktestPointsToSourceCalendar(
            smartSeries,
            (backtestPoint) => backtestPoint.average_purchase_price,
            UNSCALED_BACKTEST_PRICE_MULTIPLIER
        )
    };
}

export function buildEffectiveMarketPriceSeries(executionOrders: DcaOrderPayload[]): DcaStrategyPathChartPoint[] {
    return resolveExecutedOrders(executionOrders).map((executionOrder: DcaOrderPayload) => ({
        timestampMilliseconds: new Date(executionOrder.executed_at as string).getTime(),
        value: executionOrder.actual_execution_price as number
    }));
}

export function buildEffectiveSmartAverageUnitPriceSeries(executionOrders: DcaOrderPayload[]): DcaStrategyPathChartPoint[] {
    let runningDeployedAmount: number = 0;
    let runningTargetAssetQuantity: number = 0;
    const effectivePoints: DcaStrategyPathChartPoint[] = [];

    for (const executionOrder of resolveExecutedOrders(executionOrders)) {
        const deployedAmount: number = executionOrder.executed_source_asset_amount ?? 0;
        const executionPrice: number = executionOrder.actual_execution_price ?? 0;
        const targetAssetQuantity: number = executionOrder.executed_target_asset_amount ?? (executionPrice > 0 ? deployedAmount / executionPrice : 0);

        runningDeployedAmount += deployedAmount;
        runningTargetAssetQuantity += targetAssetQuantity;

        if (runningTargetAssetQuantity > 0) {
            effectivePoints.push({
                timestampMilliseconds: new Date(executionOrder.executed_at as string).getTime(),
                value: runningDeployedAmount / runningTargetAssetQuantity
            });
        }
    }

    return effectivePoints;
}

export function buildEffectiveBaselineAverageUnitPriceSeries(strategy: DcaStrategyPayload): DcaStrategyPathChartPoint[] {
    let runningDeployedAmount: number = 0;
    let runningTargetAssetQuantity: number = 0;
    const effectivePoints: DcaStrategyPathChartPoint[] = [];
    const nominalOrderAmount: number = strategy.amount_per_execution_order;

    for (const executionOrder of resolveExecutedOrders(strategy.execution_orders ?? [])) {
        const executionPrice: number = executionOrder.actual_execution_price ?? 0;
        if (executionPrice <= 0 || nominalOrderAmount <= 0) {
            continue;
        }

        runningDeployedAmount += nominalOrderAmount;
        runningTargetAssetQuantity += nominalOrderAmount / executionPrice;
        effectivePoints.push({
            timestampMilliseconds: new Date(executionOrder.executed_at as string).getTime(),
            value: runningDeployedAmount / runningTargetAssetQuantity
        });
    }

    return effectivePoints;
}

export function buildMarketPriceExecutionBandSegments(
    projectedMarketPrice: DcaStrategyPathChartPoint[],
    effectiveMarketPrice: DcaStrategyPathChartPoint[],
    lastExecutedTimestampMilliseconds: number
): DcaStrategyPathBandSegment[] {
    return buildBandSegmentsFromRoleSeries(projectedMarketPrice, projectedMarketPrice, effectiveMarketPrice, lastExecutedTimestampMilliseconds);
}

export function buildSmartVsProjectedEffectiveBandSegments(
    effectiveSmartAverageUnitPrice: DcaStrategyPathChartPoint[],
    projectedSmartAverageUnitPrice: DcaStrategyPathChartPoint[],
    lastExecutedTimestampMilliseconds: number
): DcaStrategyPathBandSegment[] {
    const timelinePoints: DcaStrategyPathChartPoint[] = effectiveSmartAverageUnitPrice.map((point) => ({
        timestampMilliseconds: point.timestampMilliseconds,
        value: point.value
    }));
    return buildBandSegmentsFromRoleSeries(timelinePoints, effectiveSmartAverageUnitPrice, projectedSmartAverageUnitPrice, lastExecutedTimestampMilliseconds);
}

export function buildStrategyPathChartSeriesBundle(strategy: DcaStrategyPayload): DcaStrategyPathChartSeriesBundle | null {
    const projectedSeries: DcaStrategyPathProjectedSeriesBundle | null = buildProjectedStrategyPathSeries(strategy);
    const backtestingSeries: DcaStrategyPathBacktestingSeriesBundle | null = buildBacktestingStrategyPathSeries(strategy);
    if (!projectedSeries || !backtestingSeries) {
        return null;
    }

    const executionOrders: DcaOrderPayload[] = strategy.execution_orders ?? [];
    const effectiveMarketPrice: DcaStrategyPathChartPoint[] = buildEffectiveMarketPriceSeries(executionOrders);
    const effectiveSmartAverageUnitPrice: DcaStrategyPathChartPoint[] = buildEffectiveSmartAverageUnitPriceSeries(executionOrders);
    const effectiveBaselineAverageUnitPrice: DcaStrategyPathChartPoint[] = buildEffectiveBaselineAverageUnitPriceSeries(strategy);
    const lastExecutedTimestampMilliseconds: number =
        effectiveMarketPrice.length > 0 ? effectiveMarketPrice[effectiveMarketPrice.length - 1].timestampMilliseconds : 0;

    return {
        ...projectedSeries,
        ...backtestingSeries,
        effectiveMarketPrice,
        effectiveSmartAverageUnitPrice,
        effectiveBaselineAverageUnitPrice,
        marketPriceExecutionBandSegments: buildMarketPriceExecutionBandSegments(
            projectedSeries.projectedMarketPrice,
            effectiveMarketPrice,
            lastExecutedTimestampMilliseconds
        ),
        smartVsProjectedEffectiveBandSegments: buildSmartVsProjectedEffectiveBandSegments(
            effectiveSmartAverageUnitPrice,
            projectedSeries.projectedSmartAverageUnitPrice,
            lastExecutedTimestampMilliseconds
        ),
        lastExecutedTimestampMilliseconds
    };
}

export function extractChartPointCoordinates(chartPoints: DcaStrategyPathChartPoint[]): {
    xValues: number[];
    yValues: number[];
} {
    const xValues: number[] = [];
    const yValues: number[] = [];
    for (const chartPoint of chartPoints) {
        xValues.push(chartPoint.timestampMilliseconds);
        yValues.push(chartPoint.value);
    }
    return { xValues, yValues };
}

export function resolveBacktestReferenceVisibleRangeMilliseconds(strategy: DcaStrategyPayload): {
    minimumTimestampMilliseconds: number;
    maximumTimestampMilliseconds: number;
} {
    const smartSeries = strategy.historical_backtest_payload?.smart_dca_series ?? [];
    if (smartSeries.length === 0) {
        return {
            minimumTimestampMilliseconds: 0,
            maximumTimestampMilliseconds: 1
        };
    }

    return {
        minimumTimestampMilliseconds: new Date(smartSeries[0].timestamp_iso).getTime(),
        maximumTimestampMilliseconds: new Date(smartSeries[smartSeries.length - 1].timestamp_iso).getTime()
    };
}

export function resolveStrategyPathVisibleRangeMilliseconds(strategy: DcaStrategyPayload): {
    minimumTimestampMilliseconds: number;
    maximumTimestampMilliseconds: number;
} {
    return {
        minimumTimestampMilliseconds: new Date(strategy.strategy_start_date).getTime(),
        maximumTimestampMilliseconds: new Date(strategy.strategy_end_date).getTime()
    };
}
