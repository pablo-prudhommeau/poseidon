import type {
    TradingShadowingVerdictChronicleBucketPayload,
    TradingShadowingVerdictChroniclePayload,
    TradingShadowingVerdictChronicleRegimeGatePointPayload,
    TradingShadowingVerdictChronicleSellPointPayload,
    TradingShadowingVerdictChronicleVerdictPointPayload
} from '../../../../core/models';
import type { ChronicleArrays, ChronicleBucketMeta, ChronicleCartesianPoint, SciChartModule } from './trading-shadowing-verdict-chronicle.models';
import {
    buildChronicleSellClosePoint,
    buildChronicleSellEndpointPoints,
    buildChronicleSellPaths,
    isChronicleSellClosePayloadComplete,
    isChronicleSellPathPayloadComplete,
    sortChronicleSellEndpointPoints
} from './trading-shadowing-verdict-chronicle-sell-path.utils';

export type { SciChartModule };

const CHRONICLE_MAX_METRIC_POINTS = 500;
const CHRONICLE_MAX_VOLUME_POINTS = 900;

export type ChronicleBucketLabel = TradingShadowingVerdictChronicleBucketPayload['bucket_label'];
export type TradingShadowingVerdictChronicleBucketLabel = ChronicleBucketLabel;

export const CHRONICLE_ALL_BUCKET_LABEL = 'all';

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

export function computeSimpleMovingAverage(values: number[], windowSize: number): number[] {
    if (values.length === 0 || windowSize <= 1) {
        return [...values];
    }
    const result: number[] = new Array(values.length);
    for (let index = 0; index < values.length; index++) {
        let sum = 0;
        let count = 0;
        const start = Math.max(0, index - windowSize + 1);
        for (let windowIndex = start; windowIndex <= index; windowIndex++) {
            const value = values[windowIndex];
            if (value != null && !Number.isNaN(value)) {
                sum += value;
                count++;
            }
        }
        result[index] = count > 0 ? sum / count : NaN;
    }
    return result;
}

export function formatChronicleGranularityLabel(granularitySeconds: number): string {
    if (granularitySeconds >= 86400 && granularitySeconds % 86400 === 0) {
        const dayCount = granularitySeconds / 86400;
        return `${dayCount}d`;
    }
    if (granularitySeconds >= 3600 && granularitySeconds % 3600 === 0) {
        const hourCount = granularitySeconds / 3600;
        return `${hourCount}h`;
    }
    if (granularitySeconds >= 60 && granularitySeconds % 60 === 0) {
        const minuteCount = granularitySeconds / 60;
        return `${minuteCount}m`;
    }
    return `${granularitySeconds}s`;
}

export function shadowingVerdictChronicleBucketLookbackMilliseconds(
    bucketLabel: ChronicleBucketLabel,
    bucket?: Pick<TradingShadowingVerdictChronicleBucketPayload, 'from_iso' | 'to_iso'>
): number {
    if (bucketLabel === CHRONICLE_ALL_BUCKET_LABEL) {
        const fromMilliseconds = parseIsoTimestampToEpochMilliseconds(bucket?.from_iso);
        const toMilliseconds = parseIsoTimestampToEpochMilliseconds(bucket?.to_iso);
        if (fromMilliseconds != null && toMilliseconds != null && toMilliseconds > fromMilliseconds) {
            return toMilliseconds - fromMilliseconds;
        }
        return 30 * 24 * 60 * 60 * 1000;
    }
    switch (bucketLabel) {
        case 'last_30m_1m':
            return 30 * 60 * 1000;
        case 'last_24h_1h':
            return 24 * 60 * 60 * 1000;
        case 'last_7d_15m':
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
    referenceWallClockMilliseconds: number = Date.now(),
    bucket?: Pick<TradingShadowingVerdictChronicleBucketPayload, 'from_iso' | 'to_iso'>
): number {
    const lookbackMilliseconds = shadowingVerdictChronicleBucketLookbackMilliseconds(bucketLabel, bucket);
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

function collectFinitePointXValues(points: ChronicleCartesianPoint[], target: number[]): void {
    for (const point of points) {
        if (Number.isFinite(point.x) && Number.isFinite(point.y)) {
            target.push(point.x);
        }
    }
}

export function chronicleMinimumDisplayXMilliseconds(arrays: ChronicleArrays): number {
    const candidates: number[] = [...arrays.metricTimestampsMilliseconds, ...arrays.volumeBucketTimestampsMilliseconds];
    collectFinitePointXValues(arrays.verdictCloudProfitablePoints, candidates);
    collectFinitePointXValues(arrays.verdictCloudLossPoints, candidates);
    collectFinitePointXValues(arrays.sellCloudProfitablePoints, candidates);
    collectFinitePointXValues(arrays.sellCloudLossPoints, candidates);
    for (const path of arrays.sellPathProfitablePaths) {
        collectFinitePointXValues(path, candidates);
    }
    for (const path of arrays.sellPathLossPaths) {
        collectFinitePointXValues(path, candidates);
    }
    if (candidates.length === 0) {
        return Number.MAX_SAFE_INTEGER;
    }
    return Math.min(...candidates);
}

export function winsorizeSeries(values: number[], lowerQuantile = 0.02, upperQuantile = 0.98): number[] {
    const finiteValues = values.filter((value) => Number.isFinite(value));
    if (finiteValues.length < 4) {
        return [...values];
    }
    const sorted = [...finiteValues].sort((left, right) => left - right);
    const lowerIndex = Math.max(0, Math.floor((sorted.length - 1) * lowerQuantile));
    const upperIndex = Math.min(sorted.length - 1, Math.ceil((sorted.length - 1) * upperQuantile));
    const lowerBound = sorted[lowerIndex];
    const upperBound = sorted[upperIndex];
    return values.map((value: number) => {
        if (!Number.isFinite(value)) {
            return NaN;
        }
        return Math.min(upperBound, Math.max(lowerBound, value));
    });
}

function alignRegimeGateSeriesToMetrics(
    metrics: TradingShadowingVerdictChronicleBucketPayload['metrics'],
    regimeGate: TradingShadowingVerdictChronicleRegimeGatePointPayload[] | undefined
): Pick<
    ChronicleArrays,
    | 'regimeProfitFactorSmaSeries'
    | 'regimeSparseExpectedValueUsdSmaSeries'
    | 'profitFactorGateOpenSeries'
    | 'sparseExpectedValueGateOpenSeries'
    | 'hardGateOpenSeries'
> {
    const regimeGateByTimestamp = new Map((regimeGate ?? []).map((gatePoint) => [gatePoint.timestamp_milliseconds, gatePoint]));
    const regimeProfitFactorSmaSeries: number[] = [];
    const regimeSparseExpectedValueUsdSmaSeries: number[] = [];
    const profitFactorGateOpenSeries: boolean[] = [];
    const sparseExpectedValueGateOpenSeries: boolean[] = [];
    const hardGateOpenSeries: boolean[] = [];
    for (const metric of metrics) {
        const gatePoint = regimeGateByTimestamp.get(metric.timestamp_milliseconds);
        regimeProfitFactorSmaSeries.push(gatePoint?.regime_profit_factor_sma ?? NaN);
        regimeSparseExpectedValueUsdSmaSeries.push(gatePoint?.regime_sparse_expected_value_usd_sma ?? NaN);
        profitFactorGateOpenSeries.push(gatePoint?.profit_factor_gate_open ?? false);
        sparseExpectedValueGateOpenSeries.push(gatePoint?.sparse_expected_value_gate_open ?? false);
        hardGateOpenSeries.push(gatePoint?.hard_gate_open ?? false);
    }
    return {
        regimeProfitFactorSmaSeries,
        regimeSparseExpectedValueUsdSmaSeries,
        profitFactorGateOpenSeries,
        sparseExpectedValueGateOpenSeries,
        hardGateOpenSeries
    };
}

export function buildChronicleSnapshotFingerprint(historySnapshot: TradingShadowingVerdictChroniclePayload): string {
    const bucketParts = historySnapshot.buckets.map((bucket) => {
        const lastMetricTimestamp = bucket.metrics[bucket.metrics.length - 1]?.timestamp_milliseconds ?? 0;
        const lastVolumeTimestamp = bucket.volumes[bucket.volumes.length - 1]?.timestamp_milliseconds ?? 0;
        const lastCloudTimestamp = bucket.verdict_cloud[bucket.verdict_cloud.length - 1]?.timestamp_milliseconds ?? 0;
        const sellCloud = bucket.sell_cloud ?? [];
        const lastSellTimestamp = sellCloud[sellCloud.length - 1]?.timestamp_milliseconds ?? 0;
        return `${bucket.bucket_label}:${bucket.metrics.length}:${bucket.volumes.length}:${bucket.verdict_cloud.length}:${sellCloud.length}:${lastMetricTimestamp}:${lastVolumeTimestamp}:${lastCloudTimestamp}:${lastSellTimestamp}`;
    });
    return [
        historySnapshot.generated_at_iso,
        historySnapshot.as_of_iso,
        String(historySnapshot.total_verdicts_considered),
        historySnapshot.source,
        ...bucketParts
    ].join('|');
}

export function buildChronicleArraysFromBucket(meta: ChronicleBucketMeta, smaWindowBuckets: number = 0): ChronicleArrays {
    const metrics = (() => {
        const metricByTimestamp = new Map<number, TradingShadowingVerdictChronicleBucketPayload['metrics'][number]>();
        for (const metric of meta.bucket.metrics) {
            metricByTimestamp.set(metric.timestamp_milliseconds, metric);
        }
        return [...metricByTimestamp.values()].sort((left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds);
    })();
    const volumes = (() => {
        const volumeByTimestamp = new Map<number, TradingShadowingVerdictChronicleBucketPayload['volumes'][number]>();
        for (const volume of meta.bucket.volumes) {
            volumeByTimestamp.set(volume.timestamp_milliseconds, volume);
        }
        return [...volumeByTimestamp.values()].sort((left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds);
    })();
    const metricTimestampsMilliseconds = metrics.map((metric) => metric.timestamp_milliseconds);
    let averagePnlPercentageSeries = winsorizeSeries(metrics.map((metric) => metric.average_pnl_percentage));
    let averageWinRatePercentageSeries = winsorizeSeries(metrics.map((metric) => metric.average_win_rate_percentage));
    let expectedValuePerTradeUsdSeries = winsorizeSeries(metrics.map((metric) => metric.expected_value_per_trade_usd));
    let portfolioWalletValueUsdSeries = metrics.map((metric) => metric.total_wallet_value_usd);
    let profitFactorSeries = winsorizeSeries(metrics.map((metric) => metric.profit_factor));
    let closedVerdictsPerHourSeries = winsorizeSeries(metrics.map((metric) => metric.closed_verdicts_per_hour));
    let averageCortexPredictionWinRatePercentageSeries = metrics.map((metric) => metric.average_cortex_prediction_win_rate_percentage ?? NaN);
    let cortexSkillScorePercentageSeries = metrics.map((metric) => metric.cortex_skill_score_percentage ?? NaN);
    let cortexCalibrationGapPercentagePointsSeries = metrics.map((metric) => metric.cortex_calibration_gap_percentage_points ?? NaN);
    let cortexHighConvictionAccuracyPercentageSeries = metrics.map((metric) => metric.cortex_high_conviction_accuracy_percentage ?? NaN);
    let cortexHighConvictionSharePercentageSeries = metrics.map((metric) => metric.cortex_high_conviction_share_percentage ?? NaN);
    let cortexGatePrecisionPercentageSeries = metrics.map((metric) => metric.cortex_gate_precision_percentage ?? NaN);
    let cortexGatePassRatePercentageSeries = metrics.map((metric) => metric.cortex_gate_pass_rate_percentage ?? NaN);

    const effectiveSmaWindow = smaWindowBuckets > 0 ? smaWindowBuckets : metrics.length;
    let movingAveragePnlSeries = computeSimpleMovingAverage(averagePnlPercentageSeries, effectiveSmaWindow);
    let movingAverageWinRateSeries = computeSimpleMovingAverage(averageWinRatePercentageSeries, effectiveSmaWindow);
    let movingAverageExpectedValueSeries = computeSimpleMovingAverage(expectedValuePerTradeUsdSeries, effectiveSmaWindow);
    let movingAveragePortfolioWalletValueUsdSeries = computeSimpleMovingAverage(portfolioWalletValueUsdSeries, effectiveSmaWindow);
    let movingAverageProfitFactorSeries = computeSimpleMovingAverage(profitFactorSeries, effectiveSmaWindow);
    let movingAverageTradesPerHourSeries = computeSimpleMovingAverage(closedVerdictsPerHourSeries, effectiveSmaWindow);
    let movingAverageCortexPredictionWinRatePercentageSeries = computeSimpleMovingAverage(averageCortexPredictionWinRatePercentageSeries, effectiveSmaWindow);
    let movingAverageCortexSkillScorePercentageSeries = computeSimpleMovingAverage(cortexSkillScorePercentageSeries, effectiveSmaWindow);
    let movingAverageCortexCalibrationGapPercentagePointsSeries = computeSimpleMovingAverage(cortexCalibrationGapPercentagePointsSeries, effectiveSmaWindow);
    let movingAverageCortexHighConvictionAccuracyPercentageSeries = computeSimpleMovingAverage(
        cortexHighConvictionAccuracyPercentageSeries,
        effectiveSmaWindow
    );
    let movingAverageCortexHighConvictionSharePercentageSeries = computeSimpleMovingAverage(cortexHighConvictionSharePercentageSeries, effectiveSmaWindow);
    let movingAverageCortexGatePrecisionPercentageSeries = computeSimpleMovingAverage(cortexGatePrecisionPercentageSeries, effectiveSmaWindow);
    let movingAverageCortexGatePassRatePercentageSeries = computeSimpleMovingAverage(cortexGatePassRatePercentageSeries, effectiveSmaWindow);
    let {
        regimeProfitFactorSmaSeries,
        regimeSparseExpectedValueUsdSmaSeries,
        profitFactorGateOpenSeries,
        sparseExpectedValueGateOpenSeries,
        hardGateOpenSeries
    } = alignRegimeGateSeriesToMetrics(metrics, meta.bucket.regime_gate);

    const metricDownsampledIndices = buildDownsampledIndices(metricTimestampsMilliseconds.length, CHRONICLE_MAX_METRIC_POINTS);
    const downsampleSeriesByMetricIndices = (values: number[]): number[] => metricDownsampledIndices.map((index) => values[index] ?? 0);
    const downsampleBooleanSeriesByMetricIndices = (values: boolean[]): boolean[] => metricDownsampledIndices.map((index) => values[index] ?? false);
    const downsampledMetricTimestampsMilliseconds = metricDownsampledIndices.map((index) => metricTimestampsMilliseconds[index] ?? 0);
    averagePnlPercentageSeries = downsampleSeriesByMetricIndices(averagePnlPercentageSeries);
    averageWinRatePercentageSeries = downsampleSeriesByMetricIndices(averageWinRatePercentageSeries);
    expectedValuePerTradeUsdSeries = downsampleSeriesByMetricIndices(expectedValuePerTradeUsdSeries);
    portfolioWalletValueUsdSeries = downsampleSeriesByMetricIndices(portfolioWalletValueUsdSeries);
    profitFactorSeries = downsampleSeriesByMetricIndices(profitFactorSeries);
    closedVerdictsPerHourSeries = downsampleSeriesByMetricIndices(closedVerdictsPerHourSeries);
    averageCortexPredictionWinRatePercentageSeries = downsampleSeriesByMetricIndices(averageCortexPredictionWinRatePercentageSeries);
    cortexSkillScorePercentageSeries = downsampleSeriesByMetricIndices(cortexSkillScorePercentageSeries);
    cortexCalibrationGapPercentagePointsSeries = downsampleSeriesByMetricIndices(cortexCalibrationGapPercentagePointsSeries);
    cortexHighConvictionAccuracyPercentageSeries = downsampleSeriesByMetricIndices(cortexHighConvictionAccuracyPercentageSeries);
    cortexHighConvictionSharePercentageSeries = downsampleSeriesByMetricIndices(cortexHighConvictionSharePercentageSeries);
    cortexGatePrecisionPercentageSeries = downsampleSeriesByMetricIndices(cortexGatePrecisionPercentageSeries);
    cortexGatePassRatePercentageSeries = downsampleSeriesByMetricIndices(cortexGatePassRatePercentageSeries);
    movingAveragePnlSeries = downsampleSeriesByMetricIndices(movingAveragePnlSeries);
    movingAverageWinRateSeries = downsampleSeriesByMetricIndices(movingAverageWinRateSeries);
    movingAverageExpectedValueSeries = downsampleSeriesByMetricIndices(movingAverageExpectedValueSeries);
    movingAveragePortfolioWalletValueUsdSeries = downsampleSeriesByMetricIndices(movingAveragePortfolioWalletValueUsdSeries);
    movingAverageProfitFactorSeries = downsampleSeriesByMetricIndices(movingAverageProfitFactorSeries);
    movingAverageTradesPerHourSeries = downsampleSeriesByMetricIndices(movingAverageTradesPerHourSeries);
    movingAverageCortexPredictionWinRatePercentageSeries = downsampleSeriesByMetricIndices(movingAverageCortexPredictionWinRatePercentageSeries);
    movingAverageCortexSkillScorePercentageSeries = downsampleSeriesByMetricIndices(movingAverageCortexSkillScorePercentageSeries);
    movingAverageCortexCalibrationGapPercentagePointsSeries = downsampleSeriesByMetricIndices(movingAverageCortexCalibrationGapPercentagePointsSeries);
    movingAverageCortexHighConvictionAccuracyPercentageSeries = downsampleSeriesByMetricIndices(movingAverageCortexHighConvictionAccuracyPercentageSeries);
    movingAverageCortexHighConvictionSharePercentageSeries = downsampleSeriesByMetricIndices(movingAverageCortexHighConvictionSharePercentageSeries);
    movingAverageCortexGatePrecisionPercentageSeries = downsampleSeriesByMetricIndices(movingAverageCortexGatePrecisionPercentageSeries);
    movingAverageCortexGatePassRatePercentageSeries = downsampleSeriesByMetricIndices(movingAverageCortexGatePassRatePercentageSeries);
    regimeProfitFactorSmaSeries = downsampleSeriesByMetricIndices(regimeProfitFactorSmaSeries);
    regimeSparseExpectedValueUsdSmaSeries = downsampleSeriesByMetricIndices(regimeSparseExpectedValueUsdSmaSeries);
    profitFactorGateOpenSeries = downsampleBooleanSeriesByMetricIndices(profitFactorGateOpenSeries);
    sparseExpectedValueGateOpenSeries = downsampleBooleanSeriesByMetricIndices(sparseExpectedValueGateOpenSeries);
    hardGateOpenSeries = downsampleBooleanSeriesByMetricIndices(hardGateOpenSeries);

    const volumeBucketTimestampsMilliseconds = volumes.map((volume) => volume.timestamp_milliseconds);
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

    const cohortByBucketStartServerMilliseconds = new Map<number, TradingShadowingVerdictChronicleVerdictPointPayload[]>();
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
            x: xServerMilliseconds,
            y: point.pnl_percentage,
            cortexProbability: point.cortex_probability,
            orderNotionalUsd: point.order_notional_usd
        };
        if (point.is_profitable) {
            verdictCloudProfitablePoints.push(row);
        } else {
            verdictCloudLossPoints.push(row);
        }
    }

    const sellCloud = meta.bucket.sell_cloud ?? [];
    const sellCloudProfitablePoints: ChronicleCartesianPoint[] = [];
    const sellCloudLossPoints: ChronicleCartesianPoint[] = [];
    const profitableSellPayloads: TradingShadowingVerdictChronicleSellPointPayload[] = [];
    const lossSellPayloads: TradingShadowingVerdictChronicleSellPointPayload[] = [];
    for (const point of sellCloud) {
        const pathComplete = isChronicleSellPathPayloadComplete(point);
        if (!pathComplete && !isChronicleSellClosePayloadComplete(point)) {
            continue;
        }
        const endpointPoints = pathComplete ? buildChronicleSellEndpointPoints(point) : [buildChronicleSellClosePoint(point)];
        if (point.is_profitable) {
            sellCloudProfitablePoints.push(...endpointPoints);
            if (pathComplete) {
                profitableSellPayloads.push(point);
            }
        } else {
            sellCloudLossPoints.push(...endpointPoints);
            if (pathComplete) {
                lossSellPayloads.push(point);
            }
        }
    }
    const sortedSellCloudProfitablePoints = sortChronicleSellEndpointPoints(sellCloudProfitablePoints);
    const sortedSellCloudLossPoints = sortChronicleSellEndpointPoints(sellCloudLossPoints);
    const sellPathProfitablePaths = buildChronicleSellPaths(profitableSellPayloads);
    const sellPathLossPaths = buildChronicleSellPaths(lossSellPayloads);

    return {
        metricTimestampsMilliseconds: downsampledMetricTimestampsMilliseconds,
        averagePnlPercentageSeries,
        averageWinRatePercentageSeries,
        expectedValuePerTradeUsdSeries,
        portfolioWalletValueUsdSeries,
        profitFactorSeries,
        closedVerdictsPerHourSeries,
        averageCortexPredictionWinRatePercentageSeries,
        cortexSkillScorePercentageSeries,
        cortexCalibrationGapPercentagePointsSeries,
        cortexHighConvictionAccuracyPercentageSeries,
        cortexHighConvictionSharePercentageSeries,
        cortexGatePrecisionPercentageSeries,
        cortexGatePassRatePercentageSeries,
        movingAveragePnlSeries,
        movingAverageWinRateSeries,
        movingAverageExpectedValueSeries,
        movingAveragePortfolioWalletValueUsdSeries,
        movingAverageProfitFactorSeries,
        movingAverageTradesPerHourSeries,
        movingAverageCortexPredictionWinRatePercentageSeries,
        movingAverageCortexSkillScorePercentageSeries,
        movingAverageCortexCalibrationGapPercentagePointsSeries,
        movingAverageCortexHighConvictionAccuracyPercentageSeries,
        movingAverageCortexHighConvictionSharePercentageSeries,
        movingAverageCortexGatePrecisionPercentageSeries,
        movingAverageCortexGatePassRatePercentageSeries,
        regimeProfitFactorSmaSeries,
        regimeSparseExpectedValueUsdSmaSeries,
        profitFactorGateOpenSeries,
        sparseExpectedValueGateOpenSeries,
        hardGateOpenSeries,
        volumeBucketTimestampsMilliseconds: downsampledVolumeBucketTimestampsMilliseconds,
        volumeBucketVerdictCounts: downsampledVolumeBucketVerdictCounts,
        verdictCloudProfitablePoints,
        verdictCloudLossPoints,
        sellCloudProfitablePoints: sortedSellCloudProfitablePoints,
        sellCloudLossPoints: sortedSellCloudLossPoints,
        sellPathProfitablePaths,
        sellPathLossPaths
    };
}

export function computeChronicleViewportWidthMilliseconds(
    arrays: ChronicleArrays,
    bucketLabel?: ChronicleBucketLabel,
    bucket?: Pick<TradingShadowingVerdictChronicleBucketPayload, 'from_iso' | 'to_iso'>
): number {
    const configuredLookbackMilliseconds = bucketLabel != null ? shadowingVerdictChronicleBucketLookbackMilliseconds(bucketLabel, bucket) : 0;
    const allXValues: number[] = [...arrays.volumeBucketTimestampsMilliseconds, ...arrays.metricTimestampsMilliseconds];
    collectFinitePointXValues(arrays.verdictCloudProfitablePoints, allXValues);
    collectFinitePointXValues(arrays.verdictCloudLossPoints, allXValues);
    collectFinitePointXValues(arrays.sellCloudProfitablePoints, allXValues);
    collectFinitePointXValues(arrays.sellCloudLossPoints, allXValues);
    for (const path of arrays.sellPathProfitablePaths) {
        collectFinitePointXValues(path, allXValues);
    }
    for (const path of arrays.sellPathLossPaths) {
        collectFinitePointXValues(path, allXValues);
    }

    let dataSpanMilliseconds = 60_000;
    if (allXValues.length > 0) {
        const minimumX = Math.min(...allXValues);
        const maximumX = Math.max(...allXValues);
        dataSpanMilliseconds = Math.max(maximumX - minimumX, 60_000);
    } else if (configuredLookbackMilliseconds <= 0) {
        dataSpanMilliseconds = 86_400_000;
    }

    const spanMilliseconds = Math.max(dataSpanMilliseconds, configuredLookbackMilliseconds);
    return spanMilliseconds * 1.08;
}

export {
    buildChronicleSnapshotFingerprint as buildTradingShadowingVerdictChronicleFingerprint,
    computeChronicleRetentionFloorServerEpochMilliseconds as computeTradingShadowingVerdictChronicleVisibilityRetentionFloorServerEpochMilliseconds
};
