import type { TradingShadowingVerdictChronicleSellPointPayload } from '../../../../core/models';
import type { ChronicleCartesianPoint } from './trading-shadowing-verdict-chronicle.models';

export const CHRONICLE_EQUILATERAL_TRIANGLE_HEIGHT_OVER_WIDTH = Math.sqrt(3) / 2;
export const CHRONICLE_SELL_PATH_TOKEN_ICON_SIZE_PIXELS = 12;

const SELL_PATH_SAMPLE_COUNT = 24;
const SELL_PATH_FADE_FLOOR = 0.55;
const SELL_PATH_FADE_PEAK = 1;

function buildSellPointSharedFields(
    point: TradingShadowingVerdictChronicleSellPointPayload
): Pick<ChronicleCartesianPoint, 'tokenSymbol' | 'executionStatus' | 'pnlUsd' | 'realizedPnlPercentage' | 'blockchainNetwork' | 'tokenAddress'> {
    return {
        tokenSymbol: point.token_symbol,
        executionStatus: point.execution_status,
        pnlUsd: point.pnl_usd,
        realizedPnlPercentage: point.pnl_percentage,
        blockchainNetwork: point.blockchain_network,
        tokenAddress: point.token_address
    };
}

function buildSellPathFade(interpolationWeight: number): number {
    return SELL_PATH_FADE_FLOOR + (SELL_PATH_FADE_PEAK - SELL_PATH_FADE_FLOOR) * Math.sin(Math.PI * interpolationWeight);
}

function interpolateQuadraticSegment(startY: number, endY: number, localWeight: number): number {
    return startY + (endY - startY) * localWeight * localWeight;
}

export function isChronicleSellPathPayloadComplete(point: TradingShadowingVerdictChronicleSellPointPayload): boolean {
    return (
        Number.isFinite(point.opened_at_milliseconds) &&
        Number.isFinite(point.timestamp_milliseconds) &&
        point.opened_at_milliseconds < point.timestamp_milliseconds &&
        Number.isFinite(point.pnl_percentage)
    );
}

export function isChronicleSellClosePayloadComplete(point: TradingShadowingVerdictChronicleSellPointPayload): boolean {
    return Number.isFinite(point.timestamp_milliseconds) && Number.isFinite(point.pnl_percentage);
}

export function isChronicleSellBreakevenWaypointValid(point: TradingShadowingVerdictChronicleSellPointPayload): boolean {
    const armedAtMilliseconds = point.breakeven_stop_armed_at_milliseconds;
    const armPnlPercentage = point.breakeven_arm_pnl_percentage;
    if (armedAtMilliseconds == null || armPnlPercentage == null) {
        return false;
    }
    return (
        Number.isFinite(armedAtMilliseconds) &&
        Number.isFinite(armPnlPercentage) &&
        point.opened_at_milliseconds < armedAtMilliseconds &&
        armedAtMilliseconds < point.timestamp_milliseconds
    );
}

export function buildChronicleSellClosePoint(point: TradingShadowingVerdictChronicleSellPointPayload): ChronicleCartesianPoint {
    return {
        x: point.timestamp_milliseconds,
        y: point.pnl_percentage,
        ...buildSellPointSharedFields(point)
    };
}

export function buildChronicleSellEndpointPoints(point: TradingShadowingVerdictChronicleSellPointPayload): ChronicleCartesianPoint[] {
    const sharedFields = buildSellPointSharedFields(point);
    return [
        {
            x: point.opened_at_milliseconds,
            y: 0,
            ...sharedFields
        },
        buildChronicleSellClosePoint(point)
    ];
}

function pushSellPathSample(
    pathPoints: ChronicleCartesianPoint[],
    x: number,
    y: number,
    openedAtMilliseconds: number,
    closedAtMilliseconds: number,
    sharedFields: ReturnType<typeof buildSellPointSharedFields>
): void {
    const spanMilliseconds = closedAtMilliseconds - openedAtMilliseconds;
    const interpolationWeight: number = spanMilliseconds > 0 ? (x - openedAtMilliseconds) / spanMilliseconds : 0;
    pathPoints.push({
        x,
        y,
        pathFade: buildSellPathFade(interpolationWeight),
        ...sharedFields
    });
}

function buildChronicleSellPathPointsThroughBreakeven(
    point: TradingShadowingVerdictChronicleSellPointPayload,
    sharedFields: ReturnType<typeof buildSellPointSharedFields>
): ChronicleCartesianPoint[] {
    const openedAtMilliseconds = point.opened_at_milliseconds;
    const closedAtMilliseconds = point.timestamp_milliseconds;
    const armedAtMilliseconds = point.breakeven_stop_armed_at_milliseconds;
    const armPnlPercentage = point.breakeven_arm_pnl_percentage;
    if (armedAtMilliseconds == null || armPnlPercentage == null) {
        return [];
    }
    const holdSpanMilliseconds = closedAtMilliseconds - openedAtMilliseconds;
    const armWeight = (armedAtMilliseconds - openedAtMilliseconds) / holdSpanMilliseconds;
    const firstSegmentSampleCount = Math.max(2, Math.min(SELL_PATH_SAMPLE_COUNT - 2, Math.round(armWeight * (SELL_PATH_SAMPLE_COUNT - 1)) + 1));
    const secondSegmentSampleCount = SELL_PATH_SAMPLE_COUNT - firstSegmentSampleCount;
    const pathPoints: ChronicleCartesianPoint[] = [];
    const firstSegmentSpan = firstSegmentSampleCount - 1;
    for (let sampleIndex = 0; sampleIndex <= firstSegmentSpan; sampleIndex++) {
        const localWeight: number = sampleIndex / firstSegmentSpan;
        const x: number = openedAtMilliseconds + (armedAtMilliseconds - openedAtMilliseconds) * localWeight;
        const y: number = interpolateQuadraticSegment(0, armPnlPercentage, localWeight);
        pushSellPathSample(pathPoints, x, y, openedAtMilliseconds, closedAtMilliseconds, sharedFields);
    }
    for (let sampleIndex = 1; sampleIndex <= secondSegmentSampleCount; sampleIndex++) {
        const localWeight: number = sampleIndex / secondSegmentSampleCount;
        const x: number = armedAtMilliseconds + (closedAtMilliseconds - armedAtMilliseconds) * localWeight;
        const y: number = interpolateQuadraticSegment(armPnlPercentage, point.pnl_percentage, localWeight);
        pushSellPathSample(pathPoints, x, y, openedAtMilliseconds, closedAtMilliseconds, sharedFields);
    }
    return pathPoints;
}

export function buildChronicleSellPathPoints(point: TradingShadowingVerdictChronicleSellPointPayload): ChronicleCartesianPoint[] {
    const sharedFields = buildSellPointSharedFields(point);
    if (isChronicleSellBreakevenWaypointValid(point)) {
        return buildChronicleSellPathPointsThroughBreakeven(point, sharedFields);
    }
    const openedAtMilliseconds = point.opened_at_milliseconds;
    const closedAtMilliseconds = point.timestamp_milliseconds;
    const sampleSpan = SELL_PATH_SAMPLE_COUNT - 1;
    const pathPoints: ChronicleCartesianPoint[] = [];
    for (let sampleIndex = 0; sampleIndex <= sampleSpan; sampleIndex++) {
        const interpolationWeight: number = sampleIndex / sampleSpan;
        const x: number = openedAtMilliseconds + (closedAtMilliseconds - openedAtMilliseconds) * interpolationWeight;
        const y: number = interpolateQuadraticSegment(0, point.pnl_percentage, interpolationWeight);
        pushSellPathSample(pathPoints, x, y, openedAtMilliseconds, closedAtMilliseconds, sharedFields);
    }
    return pathPoints;
}

export function buildChronicleSellPaths(points: TradingShadowingVerdictChronicleSellPointPayload[]): ChronicleCartesianPoint[][] {
    const paths: ChronicleCartesianPoint[][] = [];
    for (const point of points) {
        if (!isChronicleSellPathPayloadComplete(point)) {
            continue;
        }
        paths.push(buildChronicleSellPathPoints(point));
    }
    return paths;
}

export function sortChronicleSellEndpointPoints(points: ChronicleCartesianPoint[]): ChronicleCartesianPoint[] {
    return points.slice().sort((left, right) => left.x - right.x);
}

export function pickChronicleSellPathTokenIconAnchor(path: ChronicleCartesianPoint[]): ChronicleCartesianPoint | undefined {
    if (path.length === 0) {
        return undefined;
    }
    let bestPoint = path[0];
    for (const point of path) {
        if ((point.pathFade ?? 0) > (bestPoint.pathFade ?? 0)) {
            bestPoint = point;
        }
    }
    const blockchainNetwork = bestPoint.blockchainNetwork?.trim() ?? '';
    const tokenAddress = bestPoint.tokenAddress?.trim() ?? '';
    if (blockchainNetwork.length === 0 || tokenAddress.length === 0) {
        return undefined;
    }
    return bestPoint;
}
