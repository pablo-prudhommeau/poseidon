import { easeOutCubic, linearInterpolate } from '../../../../core/math.utils';
import type { ShadowVerdictChronicleBucketPayload, ShadowVerdictChronicleResponse, ShadowVerdictChronicleVerdictPointPayload } from '../../../../core/models';
import type { ChronicleArrays, ChronicleBucketMeta, ChronicleCartesianPoint, SciChartModule } from './shadow-verdict-chronicle.models';

export type { SciChartModule };

export const CHRONICLE_STREAM_LAG_MS_FALLBACK = 240_000;
export const CHRONICLE_SNAPSHOT_BLEND_MS = 1400;

const CHRONICLE_MAX_METRIC_POINTS = 500;
const CHRONICLE_MAX_VOLUME_POINTS = 900;

export type ChronicleBucketLabel = ShadowVerdictChronicleBucketPayload['bucket_label'];
export type ShadowVerdictChronicleBucketLabel = ChronicleBucketLabel;

function buildDownsampledIndices(length: number, maxPoints: number): number[] {
    if (length <= maxPoints) {
        return Array.from({ length }, (_unused, index) => index);
    }
    const stride = Math.max(1, Math.ceil(length / maxPoints));
    const indices: number[] = [];
    for (let index = 0; index < length; index += stride) {
        indices.push(index);
    }
    const lastIndex = length - 1;
    if (indices[indices.length - 1] !== lastIndex) {
        indices.push(lastIndex);
    }
    return indices;
}

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

export function shadowHistoryBucketLookbackMilliseconds(bucketLabel: ChronicleBucketLabel): number {
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

export function computeChronicleRetentionFloorServerEpochMilliseconds(
    bucketLabel: ChronicleBucketLabel,
    granularitySeconds: number,
    referenceWallClockMilliseconds: number = Date.now()
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
        timeStyle: 'medium'
    });
}

export function formatChronicleAxisTickLabelMilliseconds(epochMilliseconds: number): string {
    return new Date(epochMilliseconds).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

export function floorEpochMillisecondsToBucketStart(epochMilliseconds: number, granularitySeconds: number): number {
    const granularityMilliseconds = Math.max(1000, granularitySeconds * 1000);
    return Math.floor(epochMilliseconds / granularityMilliseconds) * granularityMilliseconds;
}

export function chronicleMinimumDisplayXMilliseconds(arrays: ChronicleArrays): number {
    const candidates: number[] = [...arrays.metricTimestampsMilliseconds, ...arrays.volumeBucketTimestampsMilliseconds];
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

export function winsorizeSeries(values: number[], lowerQuantile = 0.02, upperQuantile = 0.98): number[] {
    if (values.length < 4) {
        return [...values];
    }
    const sorted = [...values].sort((left, right) => left - right);
    const lowerIndex = Math.max(0, Math.floor((sorted.length - 1) * lowerQuantile));
    const upperIndex = Math.min(sorted.length - 1, Math.ceil((sorted.length - 1) * upperQuantile));
    const lowerBound = sorted[lowerIndex];
    const upperBound = sorted[upperIndex];
    return values.map((value: number) => Math.min(upperBound, Math.max(lowerBound, value)));
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
        const middle = (lower + upper) >> 1;
        if (sortedXValues[middle] <= xQuery) {
            lower = middle;
        } else {
            upper = middle;
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
        verdictCloudProfitablePoints: source.verdictCloudProfitablePoints.map((point) => ({ ...point })),
        verdictCloudLossPoints: source.verdictCloudLossPoints.map((point) => ({ ...point }))
    };
}

export function blendChronicleArrays(fromArrays: ChronicleArrays, toArrays: ChronicleArrays, rawAlpha: number): ChronicleArrays {
    const alpha = easeOutCubic(rawAlpha);
    const cloudBlendCutoff = 0.88;
    const takeCloudFromSource = alpha < cloudBlendCutoff;

    const metricTimestampsMilliseconds = toArrays.metricTimestampsMilliseconds;
    const averagePnlPercentageSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(fromArrays.metricTimestampsMilliseconds, fromArrays.averagePnlPercentageSeries, x),
            toArrays.averagePnlPercentageSeries[index] ?? 0,
            alpha
        )
    );
    const averageWinRatePercentageSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(fromArrays.metricTimestampsMilliseconds, fromArrays.averageWinRatePercentageSeries, x),
            toArrays.averageWinRatePercentageSeries[index] ?? 0,
            alpha
        )
    );
    const expectedValuePerTradeUsdSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(fromArrays.metricTimestampsMilliseconds, fromArrays.expectedValuePerTradeUsdSeries, x),
            toArrays.expectedValuePerTradeUsdSeries[index] ?? 0,
            alpha
        )
    );
    const profitFactorSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(fromArrays.metricTimestampsMilliseconds, fromArrays.profitFactorSeries, x),
            toArrays.profitFactorSeries[index] ?? 0,
            alpha
        )
    );
    const capitalVelocityPerHourSeries = metricTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(fromArrays.metricTimestampsMilliseconds, fromArrays.capitalVelocityPerHourSeries, x),
            toArrays.capitalVelocityPerHourSeries[index] ?? 0,
            alpha
        )
    );

    const volumeBucketTimestampsMilliseconds = toArrays.volumeBucketTimestampsMilliseconds;
    const volumeBucketVerdictCounts = volumeBucketTimestampsMilliseconds.map((x, index) =>
        linearInterpolate(
            sampleSortedXySeriesAtX(fromArrays.volumeBucketTimestampsMilliseconds, fromArrays.volumeBucketVerdictCounts, x),
            toArrays.volumeBucketVerdictCounts[index] ?? 0,
            alpha
        )
    );

    const blendMovingAverageSeries = (fieldName: keyof ChronicleArrays): number[] =>
        metricTimestampsMilliseconds.map((x, index) =>
            linearInterpolate(
                sampleSortedXySeriesAtX(fromArrays.metricTimestampsMilliseconds, fromArrays[fieldName] as number[], x),
                (toArrays[fieldName] as number[])[index] ?? 0,
                alpha
            )
        );

    return {
        metricTimestampsMilliseconds,
        averagePnlPercentageSeries,
        averageWinRatePercentageSeries,
        expectedValuePerTradeUsdSeries,
        profitFactorSeries,
        capitalVelocityPerHourSeries,
        movingAveragePnlSeries: blendMovingAverageSeries('movingAveragePnlSeries'),
        movingAverageWinRateSeries: blendMovingAverageSeries('movingAverageWinRateSeries'),
        movingAverageExpectedValueSeries: blendMovingAverageSeries('movingAverageExpectedValueSeries'),
        movingAverageProfitFactorSeries: blendMovingAverageSeries('movingAverageProfitFactorSeries'),
        movingAverageVelocitySeries: blendMovingAverageSeries('movingAverageVelocitySeries'),
        volumeBucketTimestampsMilliseconds,
        volumeBucketVerdictCounts,
        verdictCloudProfitablePoints: takeCloudFromSource
            ? fromArrays.verdictCloudProfitablePoints.map((point) => ({ ...point }))
            : toArrays.verdictCloudProfitablePoints.map((point) => ({ ...point })),
        verdictCloudLossPoints: takeCloudFromSource
            ? fromArrays.verdictCloudLossPoints.map((point) => ({ ...point }))
            : toArrays.verdictCloudLossPoints.map((point) => ({ ...point }))
    };
}

export function buildChronicleSnapshotFingerprint(historySnapshot: ShadowVerdictChronicleResponse): string {
    const bucketParts = historySnapshot.buckets.map((bucket) => {
        const lastMetricTimestamp = bucket.metrics[bucket.metrics.length - 1]?.timestamp_milliseconds ?? 0;
        const lastVolumeTimestamp = bucket.volumes[bucket.volumes.length - 1]?.timestamp_milliseconds ?? 0;
        const lastCloudTimestamp = bucket.verdict_cloud[bucket.verdict_cloud.length - 1]?.timestamp_milliseconds ?? 0;
        return `${bucket.bucket_label}:${bucket.metrics.length}:${bucket.volumes.length}:${bucket.verdict_cloud.length}:${lastMetricTimestamp}:${lastVolumeTimestamp}:${lastCloudTimestamp}`;
    });
    return [
        historySnapshot.generated_at_iso,
        historySnapshot.as_of_iso,
        String(historySnapshot.total_verdicts_considered),
        historySnapshot.source,
        ...bucketParts
    ].join('|');
}

export function buildChronicleArraysFromBucket(
    meta: ChronicleBucketMeta,
    streamLagMilliseconds: number = CHRONICLE_STREAM_LAG_MS_FALLBACK,
    smaWindowBuckets: number = 0
): ChronicleArrays {
    const displayTimeMilliseconds = (timestampMilliseconds: number): number => timestampMilliseconds - streamLagMilliseconds;

    const metrics = (() => {
        const metricByTimestamp = new Map<number, ShadowVerdictChronicleBucketPayload['metrics'][number]>();
        for (const metric of meta.bucket.metrics) {
            metricByTimestamp.set(metric.timestamp_milliseconds, metric);
        }
        return [...metricByTimestamp.values()].sort((left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds);
    })();
    const volumes = (() => {
        const volumeByTimestamp = new Map<number, ShadowVerdictChronicleBucketPayload['volumes'][number]>();
        for (const volume of meta.bucket.volumes) {
            volumeByTimestamp.set(volume.timestamp_milliseconds, volume);
        }
        return [...volumeByTimestamp.values()].sort((left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds);
    })();
    const metricTimestampsMilliseconds = metrics.map((metric) => displayTimeMilliseconds(metric.timestamp_milliseconds));
    let averagePnlPercentageSeries = winsorizeSeries(metrics.map((metric) => metric.average_pnl_percentage));
    let averageWinRatePercentageSeries = winsorizeSeries(metrics.map((metric) => metric.average_win_rate_percentage));
    let expectedValuePerTradeUsdSeries = winsorizeSeries(metrics.map((metric) => metric.expected_value_per_trade_usd));
    let profitFactorSeries = winsorizeSeries(metrics.map((metric) => metric.profit_factor));
    let capitalVelocityPerHourSeries = winsorizeSeries(metrics.map((metric) => metric.capital_velocity_per_hour));

    const effectiveSmaWindow = smaWindowBuckets > 0 ? smaWindowBuckets : metrics.length;
    let movingAveragePnlSeries = computeSimpleMovingAverage(averagePnlPercentageSeries, effectiveSmaWindow);
    let movingAverageWinRateSeries = computeSimpleMovingAverage(averageWinRatePercentageSeries, effectiveSmaWindow);
    let movingAverageExpectedValueSeries = computeSimpleMovingAverage(expectedValuePerTradeUsdSeries, effectiveSmaWindow);
    let movingAverageProfitFactorSeries = computeSimpleMovingAverage(profitFactorSeries, effectiveSmaWindow);
    let movingAverageVelocitySeries = computeSimpleMovingAverage(capitalVelocityPerHourSeries, effectiveSmaWindow);

    const metricDownsampledIndices = buildDownsampledIndices(metricTimestampsMilliseconds.length, CHRONICLE_MAX_METRIC_POINTS);
    const downsampleSeriesByMetricIndices = (values: number[]): number[] => metricDownsampledIndices.map((index) => values[index] ?? 0);
    const downsampledMetricTimestampsMilliseconds = metricDownsampledIndices.map((index) => metricTimestampsMilliseconds[index] ?? 0);
    averagePnlPercentageSeries = downsampleSeriesByMetricIndices(averagePnlPercentageSeries);
    averageWinRatePercentageSeries = downsampleSeriesByMetricIndices(averageWinRatePercentageSeries);
    expectedValuePerTradeUsdSeries = downsampleSeriesByMetricIndices(expectedValuePerTradeUsdSeries);
    profitFactorSeries = downsampleSeriesByMetricIndices(profitFactorSeries);
    capitalVelocityPerHourSeries = downsampleSeriesByMetricIndices(capitalVelocityPerHourSeries);
    movingAveragePnlSeries = downsampleSeriesByMetricIndices(movingAveragePnlSeries);
    movingAverageWinRateSeries = downsampleSeriesByMetricIndices(movingAverageWinRateSeries);
    movingAverageExpectedValueSeries = downsampleSeriesByMetricIndices(movingAverageExpectedValueSeries);
    movingAverageProfitFactorSeries = downsampleSeriesByMetricIndices(movingAverageProfitFactorSeries);
    movingAverageVelocitySeries = downsampleSeriesByMetricIndices(movingAverageVelocitySeries);

    const volumeBucketTimestampsMilliseconds = volumes.map((volume) => displayTimeMilliseconds(volume.timestamp_milliseconds));
    const volumeBucketVerdictCounts = winsorizeSeries(
        volumes.map((volume) => volume.verdict_count),
        0,
        0.99
    );
    const volumeDownsampledIndices = buildDownsampledIndices(volumeBucketTimestampsMilliseconds.length, CHRONICLE_MAX_VOLUME_POINTS);
    const downsampledVolumeBucketTimestampsMilliseconds = volumeDownsampledIndices.map((index) => volumeBucketTimestampsMilliseconds[index] ?? 0);
    const downsampledVolumeBucketVerdictCounts = volumeDownsampledIndices.map((index) => volumeBucketVerdictCounts[index] ?? 0);

    const granularitySeconds = meta.bucket.granularity_seconds;
    const bucketSpanMilliseconds = Math.max(1000, granularitySeconds * 1000);
    const organicVerdictCloud = meta.bucket.verdict_cloud.filter((point) => point.exit_reason !== 'LETHARGIC');

    const cohortByBucketStartServerMilliseconds = new Map<number, ShadowVerdictChronicleVerdictPointPayload[]>();
    for (const point of organicVerdictCloud) {
        const bucketStartServerMilliseconds = floorEpochMillisecondsToBucketStart(point.timestamp_milliseconds, granularitySeconds);
        const cohort = cohortByBucketStartServerMilliseconds.get(bucketStartServerMilliseconds);
        if (cohort) {
            cohort.push(point);
        } else {
            cohortByBucketStartServerMilliseconds.set(bucketStartServerMilliseconds, [point]);
        }
    }
    for (const cohort of cohortByBucketStartServerMilliseconds.values()) {
        cohort.sort((left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds || left.verdict_id - right.verdict_id);
    }
    const verdictIndexWithinBucket = new Map<number, number>();
    for (const cohort of cohortByBucketStartServerMilliseconds.values()) {
        cohort.forEach((payload, indexWithinCohort) => {
            verdictIndexWithinBucket.set(payload.verdict_id, indexWithinCohort);
        });
    }

    const cloudPnls = organicVerdictCloud.map((point) => point.pnl_percentage).sort((left, right) => left - right);
    const cloudLowerBound = cloudPnls[Math.floor(cloudPnls.length * 0.005)] ?? -100;
    const cloudUpperBound = cloudPnls[Math.floor(cloudPnls.length * 0.995)] ?? 100;

    const verdictCloudProfitablePoints: ChronicleCartesianPoint[] = [];
    const verdictCloudLossPoints: ChronicleCartesianPoint[] = [];
    for (const point of organicVerdictCloud) {
        if (point.pnl_percentage < cloudLowerBound || point.pnl_percentage > cloudUpperBound) {
            continue;
        }

        const bucketStartServerMilliseconds = floorEpochMillisecondsToBucketStart(point.timestamp_milliseconds, granularitySeconds);
        const cohort = cohortByBucketStartServerMilliseconds.get(bucketStartServerMilliseconds) ?? [point];
        const indexWithinBucket = verdictIndexWithinBucket.get(point.verdict_id) ?? 0;
        const cohortSize = cohort.length;
        const columnHalfWidthMilliseconds = (bucketSpanMilliseconds * 0.88) / 2;
        let xServerMilliseconds = bucketStartServerMilliseconds;
        if (cohortSize > 1) {
            const usableHalfMilliseconds = columnHalfWidthMilliseconds * 0.9;
            const stepMilliseconds = (2 * usableHalfMilliseconds) / (cohortSize - 1);
            xServerMilliseconds = bucketStartServerMilliseconds - usableHalfMilliseconds + indexWithinBucket * stepMilliseconds;
        }
        const row: ChronicleCartesianPoint = {
            x: displayTimeMilliseconds(xServerMilliseconds),
            y: point.pnl_percentage,
            z: Math.max(6.5, point.point_size * 1.15)
        };
        if (point.is_profitable) {
            verdictCloudProfitablePoints.push(row);
        } else {
            verdictCloudLossPoints.push(row);
        }
    }

    return {
        metricTimestampsMilliseconds: downsampledMetricTimestampsMilliseconds,
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
        volumeBucketTimestampsMilliseconds: downsampledVolumeBucketTimestampsMilliseconds,
        volumeBucketVerdictCounts: downsampledVolumeBucketVerdictCounts,
        verdictCloudProfitablePoints,
        verdictCloudLossPoints
    };
}

export function extendChronicleArraysToTapeRight(source: ChronicleArrays, tapeRightEdgeMilliseconds: number): ChronicleArrays {
    const epsilonMilliseconds = 1;
    const baseMetricX = source.metricTimestampsMilliseconds;
    const extendMetric = baseMetricX.length > 0 && tapeRightEdgeMilliseconds > baseMetricX[baseMetricX.length - 1] + epsilonMilliseconds;
    const metricTimestampsMilliseconds = extendMetric ? [...baseMetricX, tapeRightEdgeMilliseconds] : baseMetricX.slice();
    const appendMetricTail = (values: number[]): number[] => {
        const copy = values.slice();
        if (extendMetric) {
            copy.push(values[values.length - 1] ?? 0);
        }
        return copy;
    };

    const baseVolumeX = source.volumeBucketTimestampsMilliseconds;
    const extendVolume = baseVolumeX.length > 0 && tapeRightEdgeMilliseconds > baseVolumeX[baseVolumeX.length - 1] + epsilonMilliseconds;
    const volumeBucketTimestampsMilliseconds = extendVolume ? [...baseVolumeX, tapeRightEdgeMilliseconds] : baseVolumeX.slice();
    const volumeBucketVerdictCounts = (() => {
        const copy = source.volumeBucketVerdictCounts.slice();
        if (extendVolume) {
            copy.push(source.volumeBucketVerdictCounts[source.volumeBucketVerdictCounts.length - 1] ?? 0);
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
        verdictCloudLossPoints: source.verdictCloudLossPoints
    };
}

export function computeChronicleViewportWidthMilliseconds(arrays: ChronicleArrays): number {
    const allXValues: number[] = [...arrays.volumeBucketTimestampsMilliseconds, ...arrays.metricTimestampsMilliseconds];
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

export {
    buildChronicleSnapshotFingerprint as buildShadowVerdictChronicleFingerprint,
    computeChronicleRetentionFloorServerEpochMilliseconds as computeShadowVerdictChronicleVisibilityRetentionFloorServerEpochMilliseconds
};
