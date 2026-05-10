import type {SciChartSurface, SeriesInfo, TSciChart, XyzDataSeries} from 'scichart';
import type {ShadowVerdictChronicleBucketPayload, ShadowVerdictChronicleResponse, ShadowVerdictChronicleVerdictPointPayload,} from '../../../../core/models';

export const CHRONICLE_STREAM_LAG_MS_FALLBACK = 240_000;
export const CHRONICLE_SNAPSHOT_BLEND_MS = 1400;

export function resolveChronicleStreamLagMilliseconds(seriesEndLagSeconds: number | undefined): number {
    if (seriesEndLagSeconds != null && seriesEndLagSeconds > 0) {
        return seriesEndLagSeconds * 1000;
    }
    return CHRONICLE_STREAM_LAG_MS_FALLBACK;
}

export function computeSimpleMovingAverage(values: number[], windowSize: number): number[] {
    if (values.length === 0 || windowSize <= 1) {
        return [...values];
    }
    const effectiveWindow = Math.min(windowSize, values.length);
    const result: number[] = new Array(values.length);
    let runningSum = 0;
    for (let index = 0; index < values.length; index++) {
        runningSum += values[index];
        if (index >= effectiveWindow) {
            runningSum -= values[index - effectiveWindow];
        }
        const currentWindow = Math.min(index + 1, effectiveWindow);
        result[index] = runningSum / currentWindow;
    }
    return result;
}

export type SciChartModule = typeof import('scichart');
export type ShadowVerdictChronicleBucketLabel = ShadowVerdictChronicleBucketPayload['bucket_label'];

export function shadowHistoryBucketLookbackMilliseconds(bucketLabel: ShadowVerdictChronicleBucketLabel): number {
    switch (bucketLabel) {
        case 'last_30m_1m':
            return 30 * 60 * 1000;
        case 'last_24h_1h':
            return 24 * 60 * 60 * 1000;
        case 'last_7d_5m':
            return 7 * 24 * 60 * 60 * 1000;
        case 'last_30d_30m':
            return 30 * 24 * 60 * 60 * 1000;
        default:
            return 24 * 60 * 60 * 1000;
    }
}

export function computeShadowVerdictChronicleVisibilityRetentionFloorServerEpochMilliseconds(
    bucketLabel: ShadowVerdictChronicleBucketLabel,
    granularitySeconds: number,
    referenceWallClockMilliseconds: number = Date.now(),
): number {
    const lookbackMilliseconds = shadowHistoryBucketLookbackMilliseconds(bucketLabel);
    const viewportSpanMilliseconds = lookbackMilliseconds * 1.18;
    const trailingSafetyMilliseconds = 10 * Math.max(1, granularitySeconds) * 1000;
    return referenceWallClockMilliseconds - viewportSpanMilliseconds - trailingSafetyMilliseconds;
}

export function parseIsoTimestampToEpochMilliseconds(rawIso: string | undefined): number | undefined {
    if (!rawIso?.trim()) {
        return undefined;
    }
    const trimmed = rawIso.trim();
    const normalized = trimmed.includes('T') ? trimmed : trimmed.replace(' ', 'T');
    let timestampMilliseconds = Date.parse(normalized);
    if (Number.isNaN(timestampMilliseconds) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized)) {
        timestampMilliseconds = Date.parse(`${normalized}Z`);
    }
    return Number.isNaN(timestampMilliseconds) ? undefined : timestampMilliseconds;
}

export function formatChronicleAxisLocalDateTimeMilliseconds(epochMilliseconds: number): string {
    return new Date(epochMilliseconds).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'medium',
    });
}

export function formatChronicleAxisTickLabelMilliseconds(epochMilliseconds: number): string {
    return new Date(epochMilliseconds).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    });
}

export interface ChronicleChartModel {
    sciChartSurface: SciChartSurface;
    wasmContext: TSciChart;
    sci: SciChartModule;
    xAxis: InstanceType<SciChartModule['DateTimeNumericAxis']>;
    viewportWidthMilliseconds: number;
    volumeMountainDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    volumeColumnDataSeries: InstanceType<SciChartModule['XyDataSeries']>;
    volumeColumnRenderableSeries: InstanceType<SciChartModule['FastColumnRenderableSeries']>;
    metricLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    movingAverageLineRenderableSeries: InstanceType<SciChartModule['SplineLineRenderableSeries']>[];
    profitableVerdictXyzDataSeries: XyzDataSeries;
    lossVerdictXyzDataSeries: XyzDataSeries;
}

export interface ChronicleBucketMeta {
    bucket: ShadowVerdictChronicleBucketPayload;
    response: ShadowVerdictChronicleResponse;
}

export interface ChronicleArrays {
    metricTimestampsMilliseconds: number[];
    averagePnlPercentageSeries: number[];
    averageWinRatePercentageSeries: number[];
    expectedValuePerTradeUsdSeries: number[];
    profitFactorSeries: number[];
    capitalVelocityPerHourSeries: number[];
    movingAveragePnlSeries: number[];
    movingAverageWinRateSeries: number[];
    movingAverageExpectedValueSeries: number[];
    movingAverageProfitFactorSeries: number[];
    movingAverageVelocitySeries: number[];
    volumeBucketTimestampsMilliseconds: number[];
    volumeBucketVerdictCounts: number[];
    verdictCloudProfitablePoints: Array<{ x: number; y: number; z: number }>;
    verdictCloudLossPoints: Array<{ x: number; y: number; z: number }>;
}

export function floorEpochMillisecondsToBucketStart(epochMilliseconds: number, granularitySeconds: number): number {
    const granularityMilliseconds = Math.max(1000, granularitySeconds * 1000);
    return Math.floor(epochMilliseconds / granularityMilliseconds) * granularityMilliseconds;
}

export function chronicleMinimumDisplayXMilliseconds(arrays: ChronicleArrays): number {
    const candidates: number[] = [
        ...arrays.metricTimestampsMilliseconds,
        ...arrays.volumeBucketTimestampsMilliseconds,
    ];
    for (const point of arrays.verdictCloudProfitablePoints) {
        candidates.push(point.x);
    }
    for (const point of arrays.verdictCloudLossPoints) {
        candidates.push(point.x);
    }
    if (candidates.length === 0) {
        return Number.MAX_SAFE_INTEGER;
    }
    return Math.min(...candidates);
}

export function winsorizeSeries(
    values: number[],
    lowerQuantile = 0.02,
    upperQuantile = 0.98,
): number[] {
    if (values.length < 4) {
        return [...values];
    }
    const sorted = [...values].sort((a, b) => a - b);
    const lowerIndex = Math.max(0, Math.floor((sorted.length - 1) * lowerQuantile));
    const upperIndex = Math.min(sorted.length - 1, Math.ceil((sorted.length - 1) * upperQuantile));
    const lowerBound = sorted[lowerIndex];
    const upperBound = sorted[upperIndex];
    return values.map(value => Math.min(upperBound, Math.max(lowerBound, value)));
}

function linearInterpolate(start: number, end: number, weight: number): number {
    return start + (end - start) * weight;
}

function easeOutCubic(weight: number): number {
    const clamped = Math.min(1, Math.max(0, weight));
    return 1 - (1 - clamped) ** 3;
}

export function chronicleShouldShowTargetVerdictCloud(rawAlpha: number): boolean {
    return easeOutCubic(rawAlpha) >= 0.88;
}

function sampleSortedXySeriesAtX(sortedXValues: number[], yValues: number[], xQuery: number): number {
    if (sortedXValues.length === 0 || yValues.length === 0) {
        return 0;
    }
    if (xQuery <= sortedXValues[0]) {
        return yValues[0];
    }
    const lastIndex = sortedXValues.length - 1;
    if (xQuery >= sortedXValues[lastIndex]) {
        return yValues[lastIndex];
    }
    let lower = 0;
    let upper = lastIndex;
    while (lower < upper - 1) {
        const mid = (lower + upper) >> 1;
        if (sortedXValues[mid] <= xQuery) {
            lower = mid;
        } else {
            upper = mid;
        }
    }
    const span = sortedXValues[upper] - sortedXValues[lower];
    if (span <= 0) {
        return yValues[lower];
    }
    const interpolationWeight = (xQuery - sortedXValues[lower]) / span;
    return linearInterpolate(yValues[lower], yValues[upper], interpolationWeight);
}

export function cloneChronicleArrays(source: ChronicleArrays): ChronicleArrays {
    return {
        metricTimestampsMilliseconds: [...source.metricTimestampsMilliseconds],
        averagePnlPercentageSeries: [...source.averagePnlPercentageSeries],
        averageWinRatePercentageSeries: [...source.averageWinRatePercentageSeries],
        expectedValuePerTradeUsdSeries: [...source.expectedValuePerTradeUsdSeries],
        profitFactorSeries: [...source.profitFactorSeries],
        capitalVelocityPerHourSeries: [...source.capitalVelocityPerHourSeries],
        movingAveragePnlSeries: [...source.movingAveragePnlSeries],
        movingAverageWinRateSeries: [...source.movingAverageWinRateSeries],
        movingAverageExpectedValueSeries: [...source.movingAverageExpectedValueSeries],
        movingAverageProfitFactorSeries: [...source.movingAverageProfitFactorSeries],
        movingAverageVelocitySeries: [...source.movingAverageVelocitySeries],
        volumeBucketTimestampsMilliseconds: [...source.volumeBucketTimestampsMilliseconds],
        volumeBucketVerdictCounts: [...source.volumeBucketVerdictCounts],
        verdictCloudProfitablePoints: source.verdictCloudProfitablePoints.map(point => ({...point})),
        verdictCloudLossPoints: source.verdictCloudLossPoints.map(point => ({...point})),
    };
}

export function blendChronicleArrays(
    fromArrays: ChronicleArrays,
    toArrays: ChronicleArrays,
    rawAlpha: number,
): ChronicleArrays {
    const alpha = easeOutCubic(rawAlpha);
    const cloudBlendCutoff = 0.88;
    const takeCloudFromSource = alpha < cloudBlendCutoff;

    const metricTimestampsMilliseconds = toArrays.metricTimestampsMilliseconds;
    const averagePnlPercentageSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(
                fromArrays.metricTimestampsMilliseconds,
                fromArrays.averagePnlPercentageSeries,
                x,
            ),
            toArrays.averagePnlPercentageSeries[index] ?? 0,
            alpha,
        ),
    );
    const averageWinRatePercentageSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(
                fromArrays.metricTimestampsMilliseconds,
                fromArrays.averageWinRatePercentageSeries,
                x,
            ),
            toArrays.averageWinRatePercentageSeries[index] ?? 0,
            alpha,
        ),
    );
    const expectedValuePerTradeUsdSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(
                fromArrays.metricTimestampsMilliseconds,
                fromArrays.expectedValuePerTradeUsdSeries,
                x,
            ),
            toArrays.expectedValuePerTradeUsdSeries[index] ?? 0,
            alpha,
        ),
    );
    const profitFactorSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(
                fromArrays.metricTimestampsMilliseconds,
                fromArrays.profitFactorSeries,
                x,
            ),
            toArrays.profitFactorSeries[index] ?? 0,
            alpha,
        ),
    );
    const capitalVelocityPerHourSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(
                fromArrays.metricTimestampsMilliseconds,
                fromArrays.capitalVelocityPerHourSeries,
                x,
            ),
            toArrays.capitalVelocityPerHourSeries[index] ?? 0,
            alpha,
        ),
    );

    const volumeBucketTimestampsMilliseconds = toArrays.volumeBucketTimestampsMilliseconds;
    const volumeBucketVerdictCounts = volumeBucketTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(
                fromArrays.volumeBucketTimestampsMilliseconds,
                fromArrays.volumeBucketVerdictCounts,
                x,
            ),
            toArrays.volumeBucketVerdictCounts[index] ?? 0,
            alpha,
        ),
    );

    const blendMetricSma = (fromField: keyof ChronicleArrays, toField: keyof ChronicleArrays): number[] =>
        metricTimestampsMilliseconds.map((x, index) =>
            linearInterpolate(
                sampleSortedXySeriesAtX(
                    fromArrays.metricTimestampsMilliseconds,
                    fromArrays[fromField] as number[],
                    x,
                ),
                (toArrays[toField] as number[])[index] ?? 0,
                alpha,
            ),
        );

    return {
        metricTimestampsMilliseconds,
        averagePnlPercentageSeries,
        averageWinRatePercentageSeries,
        expectedValuePerTradeUsdSeries,
        profitFactorSeries,
        capitalVelocityPerHourSeries,
        movingAveragePnlSeries: blendMetricSma('movingAveragePnlSeries', 'movingAveragePnlSeries'),
        movingAverageWinRateSeries: blendMetricSma('movingAverageWinRateSeries', 'movingAverageWinRateSeries'),
        movingAverageExpectedValueSeries: blendMetricSma('movingAverageExpectedValueSeries', 'movingAverageExpectedValueSeries'),
        movingAverageProfitFactorSeries: blendMetricSma('movingAverageProfitFactorSeries', 'movingAverageProfitFactorSeries'),
        movingAverageVelocitySeries: blendMetricSma('movingAverageVelocitySeries', 'movingAverageVelocitySeries'),
        volumeBucketTimestampsMilliseconds,
        volumeBucketVerdictCounts,
        verdictCloudProfitablePoints: takeCloudFromSource
            ? fromArrays.verdictCloudProfitablePoints.map(point => ({...point}))
            : toArrays.verdictCloudProfitablePoints.map(point => ({...point})),
        verdictCloudLossPoints: takeCloudFromSource
            ? fromArrays.verdictCloudLossPoints.map(point => ({...point}))
            : toArrays.verdictCloudLossPoints.map(point => ({...point})),
    };
}

export function buildShadowVerdictChronicleFingerprint(hist: ShadowVerdictChronicleResponse): string {
    const bucketParts = hist.buckets.map(bucket => {
        const lastMetricTimestamp =
            bucket.metrics[bucket.metrics.length - 1]?.timestamp_milliseconds ?? 0;
        const lastVolumeTimestamp =
            bucket.volumes[bucket.volumes.length - 1]?.timestamp_milliseconds ?? 0;
        const lastCloudTimestamp =
            bucket.verdict_cloud[bucket.verdict_cloud.length - 1]?.timestamp_milliseconds ?? 0;
        return `${bucket.bucket_label}:${bucket.metrics.length}:${bucket.volumes.length}:${bucket.verdict_cloud.length}:${lastMetricTimestamp}:${lastVolumeTimestamp}:${lastCloudTimestamp}`;
    });
    return [
        hist.generated_at_iso,
        hist.as_of_iso,
        String(hist.total_verdicts_considered),
        hist.source,
        ...bucketParts,
    ].join('|');
}

export function buildChronicleArraysFromBucket(
    meta: ChronicleBucketMeta,
    streamLagMilliseconds: number = CHRONICLE_STREAM_LAG_MS_FALLBACK,
    smaWindowBuckets: number = 0,
): ChronicleArrays {
    const displayTimeMilliseconds = (timestampMilliseconds: number) =>
        timestampMilliseconds - streamLagMilliseconds;

    const metrics = meta.bucket.metrics;
    const volumes = meta.bucket.volumes;
    const metricTimestampsMilliseconds = metrics.map(metric =>
        displayTimeMilliseconds(metric.timestamp_milliseconds),
    );
    const averagePnlPercentageSeries = winsorizeSeries(
        metrics.map(metric => metric.average_pnl_percentage),
    );
    const averageWinRatePercentageSeries = winsorizeSeries(
        metrics.map(metric => metric.average_win_rate_percentage),
    );
    const expectedValuePerTradeUsdSeries = winsorizeSeries(
        metrics.map(metric => metric.expected_value_per_trade_usd),
    );
    const profitFactorSeries = winsorizeSeries(metrics.map(metric => metric.profit_factor));
    const capitalVelocityPerHourSeries = winsorizeSeries(
        metrics.map(metric => metric.capital_velocity_per_hour),
    );

    const effectiveSmaWindow = smaWindowBuckets > 0 ? smaWindowBuckets : metrics.length;
    const movingAveragePnlSeries = computeSimpleMovingAverage(averagePnlPercentageSeries, effectiveSmaWindow);
    const movingAverageWinRateSeries = computeSimpleMovingAverage(averageWinRatePercentageSeries, effectiveSmaWindow);
    const movingAverageExpectedValueSeries = computeSimpleMovingAverage(expectedValuePerTradeUsdSeries, effectiveSmaWindow);
    const movingAverageProfitFactorSeries = computeSimpleMovingAverage(profitFactorSeries, effectiveSmaWindow);
    const movingAverageVelocitySeries = computeSimpleMovingAverage(capitalVelocityPerHourSeries, effectiveSmaWindow);

    const volumeBucketTimestampsMilliseconds = volumes.map(volume =>
        displayTimeMilliseconds(volume.timestamp_milliseconds),
    );
    const volumeBucketVerdictCounts = winsorizeSeries(
        volumes.map(volume => volume.verdict_count),
        0,
        0.99,
    );

    const granularitySeconds = meta.bucket.granularity_seconds;
    const bucketSpanMilliseconds = Math.max(1000, granularitySeconds * 1000);
    const organicVerdictCloud = meta.bucket.verdict_cloud.filter(point => point.exit_reason !== 'LETHARGIC');

    const cohortByBucketStartServerMs = new Map<number, ShadowVerdictChronicleVerdictPointPayload[]>();
    for (const point of organicVerdictCloud) {
        const bucketStartServerMs = floorEpochMillisecondsToBucketStart(
            point.timestamp_milliseconds,
            granularitySeconds,
        );
        const cohort = cohortByBucketStartServerMs.get(bucketStartServerMs);
        if (cohort) {
            cohort.push(point);
        } else {
            cohortByBucketStartServerMs.set(bucketStartServerMs, [point]);
        }
    }
    for (const cohort of cohortByBucketStartServerMs.values()) {
        cohort.sort(
            (left, right) =>
                left.timestamp_milliseconds - right.timestamp_milliseconds ||
                left.verdict_id - right.verdict_id,
        );
    }
    const verdictIndexWithinBucket = new Map<number, number>();
    for (const cohort of cohortByBucketStartServerMs.values()) {
        cohort.forEach((payload, indexWithinCohort) => {
            verdictIndexWithinBucket.set(payload.verdict_id, indexWithinCohort);
        });
    }

    const cloudPnls = organicVerdictCloud.map(point => point.pnl_percentage).sort((a, b) => a - b);
    const cloudLowerBound = cloudPnls[Math.floor(cloudPnls.length * 0.005)] ?? -100;
    const cloudUpperBound = cloudPnls[Math.floor(cloudPnls.length * 0.995)] ?? 100;

    const verdictCloudProfitablePoints: Array<{ x: number; y: number; z: number }> = [];
    const verdictCloudLossPoints: Array<{ x: number; y: number; z: number }> = [];
    for (const point of organicVerdictCloud) {
        if (point.pnl_percentage < cloudLowerBound || point.pnl_percentage > cloudUpperBound) {
            continue;
        }

        const bucketStartServerMs = floorEpochMillisecondsToBucketStart(
            point.timestamp_milliseconds,
            granularitySeconds,
        );
        const cohort = cohortByBucketStartServerMs.get(bucketStartServerMs) ?? [point];
        const indexWithinBucket = verdictIndexWithinBucket.get(point.verdict_id) ?? 0;
        const cohortSize = cohort.length;
        const columnHalfWidthMs = (bucketSpanMilliseconds * 0.88) / 2;
        let xServerMs = bucketStartServerMs;
        if (cohortSize > 1) {
            const usableHalfMs = columnHalfWidthMs * 0.9;
            const stepMs = (2 * usableHalfMs) / (cohortSize - 1);
            xServerMs = bucketStartServerMs - usableHalfMs + indexWithinBucket * stepMs;
        }
        const row = {
            x: displayTimeMilliseconds(xServerMs),
            y: point.pnl_percentage,
            z: Math.max(6.5, point.point_size * 1.15),
        };
        if (point.is_profitable) {
            verdictCloudProfitablePoints.push(row);
        } else {
            verdictCloudLossPoints.push(row);
        }
    }

    return {
        metricTimestampsMilliseconds,
        averagePnlPercentageSeries,
        averageWinRatePercentageSeries,
        expectedValuePerTradeUsdSeries,
        profitFactorSeries,
        capitalVelocityPerHourSeries,
        movingAveragePnlSeries,
        movingAverageWinRateSeries,
        movingAverageExpectedValueSeries,
        movingAverageProfitFactorSeries,
        movingAverageVelocitySeries,
        volumeBucketTimestampsMilliseconds,
        volumeBucketVerdictCounts,
        verdictCloudProfitablePoints,
        verdictCloudLossPoints,
    };
}

export function extendChronicleArraysToTapeRight(
    source: ChronicleArrays,
    tapeRightEdgeMs: number,
): ChronicleArrays {
    const epsilonMilliseconds = 1;
    const baseMetricX = source.metricTimestampsMilliseconds;
    const extendMetric =
        baseMetricX.length > 0 &&
        tapeRightEdgeMs > baseMetricX[baseMetricX.length - 1] + epsilonMilliseconds;
    const metricTimestampsMilliseconds = extendMetric
        ? [...baseMetricX, tapeRightEdgeMs]
        : baseMetricX.slice();
    const appendMetricTail = (values: number[]): number[] => {
        const copy = values.slice();
        if (extendMetric) {
            copy.push(values[values.length - 1] ?? 0);
        }
        return copy;
    };

    const baseVolX = source.volumeBucketTimestampsMilliseconds;
    const extendVol =
        baseVolX.length > 0 && tapeRightEdgeMs > baseVolX[baseVolX.length - 1] + epsilonMilliseconds;
    const volumeBucketTimestampsMilliseconds = extendVol
        ? [...baseVolX, tapeRightEdgeMs]
        : baseVolX.slice();
    const volumeBucketVerdictCounts = (() => {
        const copy = source.volumeBucketVerdictCounts.slice();
        if (extendVol) {
            copy.push(
                source.volumeBucketVerdictCounts[source.volumeBucketVerdictCounts.length - 1] ?? 0,
            );
        }
        return copy;
    })();

    return {
        metricTimestampsMilliseconds,
        averagePnlPercentageSeries: appendMetricTail(source.averagePnlPercentageSeries),
        averageWinRatePercentageSeries: appendMetricTail(source.averageWinRatePercentageSeries),
        expectedValuePerTradeUsdSeries: appendMetricTail(source.expectedValuePerTradeUsdSeries),
        profitFactorSeries: appendMetricTail(source.profitFactorSeries),
        capitalVelocityPerHourSeries: appendMetricTail(source.capitalVelocityPerHourSeries),
        movingAveragePnlSeries: appendMetricTail(source.movingAveragePnlSeries),
        movingAverageWinRateSeries: appendMetricTail(source.movingAverageWinRateSeries),
        movingAverageExpectedValueSeries: appendMetricTail(source.movingAverageExpectedValueSeries),
        movingAverageProfitFactorSeries: appendMetricTail(source.movingAverageProfitFactorSeries),
        movingAverageVelocitySeries: appendMetricTail(source.movingAverageVelocitySeries),
        volumeBucketTimestampsMilliseconds,
        volumeBucketVerdictCounts,
        verdictCloudProfitablePoints: source.verdictCloudProfitablePoints,
        verdictCloudLossPoints: source.verdictCloudLossPoints,
    };
}

export function computeChronicleViewportWidthMilliseconds(arrays: ChronicleArrays): number {
    const allXValues: number[] = [
        ...arrays.volumeBucketTimestampsMilliseconds,
        ...arrays.metricTimestampsMilliseconds,
    ];
    for (const point of arrays.verdictCloudProfitablePoints) {
        allXValues.push(point.x);
    }
    for (const point of arrays.verdictCloudLossPoints) {
        allXValues.push(point.x);
    }
    if (allXValues.length === 0) {
        return 86_400_000;
    }
    const minimumX = Math.min(...allXValues);
    const maximumX = Math.max(...allXValues);
    const spanMilliseconds = Math.max(maximumX - minimumX, 60_000);
    return spanMilliseconds * 1.08;
}

const CHRONICLE_TOOLTIP_AXIS_ORDER = ['yPct', 'yVol', 'yUsd', 'yPf', 'yVel'] as const;

const CHRONICLE_TOOLTIP_AXIS_ORDER_SET = new Set<string>(CHRONICLE_TOOLTIP_AXIS_ORDER);

const CHRONICLE_TOOLTIP_SECTION_TITLE: Record<string, string> = {
    yPct: 'PnL % · win rate · verdict cloud',
    yVol: 'verdict count per bucket',
    yUsd: 'expected value ($ / trade)',
    yPf: 'profit factor',
    yVel: 'velocity (closed / hour)',
};

function formatChronicleTooltipHitLine(seriesInfo: SeriesInfo): string {
    const rawName = seriesInfo.seriesName;
    const label = rawName !== undefined && rawName.trim().length > 0 ? rawName.trim() : 'series';
    const withZ = seriesInfo as SeriesInfo & { zValue?: number };
    if (typeof withZ.zValue === 'number' && Number.isFinite(withZ.zValue)) {
        return `${label} · ${seriesInfo.formattedYValue} · bubble ${withZ.zValue.toFixed(1)}`;
    }
    return `${label} · ${seriesInfo.formattedYValue}`;
}

export function formatChronicleCrosshairTooltip(seriesInfos: SeriesInfo[]): string[] {
    const anchor = seriesInfos.find(entry => entry.isHit) ?? seriesInfos[0];
    const lines: string[] = [];
    if (anchor?.xValue != null && Number.isFinite(anchor.xValue)) {
        lines.push(formatChronicleAxisLocalDateTimeMilliseconds(anchor.xValue));
        lines.push('');
    }
    const hits = seriesInfos.filter(entry => entry.isHit);
    const hitsByAxisId = new Map<string, SeriesInfo[]>();
    for (const hit of hits) {
        const axisId = hit.renderableSeries.yAxisId ?? '';
        const bucket = hitsByAxisId.get(axisId);
        if (bucket) {
            bucket.push(hit);
        } else {
            hitsByAxisId.set(axisId, [hit]);
        }
    }
    const orderedAxisIds: string[] = [];
    for (const axisId of CHRONICLE_TOOLTIP_AXIS_ORDER) {
        if (hitsByAxisId.has(axisId)) {
            orderedAxisIds.push(axisId);
        }
    }
    for (const axisId of hitsByAxisId.keys()) {
        if (!CHRONICLE_TOOLTIP_AXIS_ORDER_SET.has(axisId)) {
            orderedAxisIds.push(axisId);
        }
    }
    let isFirstSection = true;
    for (const axisId of orderedAxisIds) {
        const group = hitsByAxisId.get(axisId);
        if (!group?.length) {
            continue;
        }
        if (!isFirstSection) {
            lines.push('');
        }
        isFirstSection = false;
        const sectionHeading = CHRONICLE_TOOLTIP_SECTION_TITLE[axisId] ?? axisId;
        lines.push(sectionHeading);
        const sortedGroup = [...group].sort((left, right) =>
            (left.seriesName ?? '').localeCompare(right.seriesName ?? '', undefined, {sensitivity: 'base'}),
        );
        for (const hit of sortedGroup) {
            lines.push(`  ${formatChronicleTooltipHitLine(hit)}`);
        }
    }
    while (lines.length > 0 && lines[lines.length - 1] === '') {
        lines.pop();
    }
    return lines;
}
