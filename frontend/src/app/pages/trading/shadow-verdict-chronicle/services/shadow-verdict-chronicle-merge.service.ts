import { Injectable } from '@angular/core';
import type {
    ShadowVerdictChronicleBucketPayload,
    ShadowVerdictChronicleDeltaPayload,
    ShadowVerdictChronicleResponse,
    ShadowVerdictChronicleVerdictPointPayload
} from '../../../../core/models';
import {
    type ChronicleBucketLabel,
    computeChronicleRetentionFloorServerEpochMilliseconds,
    parseIsoTimestampToEpochMilliseconds
} from '../data/shadow-verdict-chronicle-arrays.utils';

@Injectable({ providedIn: 'root' })
export class ShadowVerdictChronicleMergeService {
    mergeShadowVerdictChronicleDelta(
        baseSnapshot: ShadowVerdictChronicleResponse,
        incrementalPatch: ShadowVerdictChronicleDeltaPayload
    ): ShadowVerdictChronicleResponse {
        const deltaByLabel: Map<ChronicleBucketLabel, ShadowVerdictChronicleDeltaPayload['buckets'][number]> = new Map(
            incrementalPatch.buckets.map((bucketDelta) => [bucketDelta.bucket_label, bucketDelta])
        );
        const referenceWallClockMilliseconds: number =
            parseIsoTimestampToEpochMilliseconds(incrementalPatch.as_of_iso) ??
            parseIsoTimestampToEpochMilliseconds(incrementalPatch.generated_at_iso) ??
            Date.now();
        const buckets: ShadowVerdictChronicleBucketPayload[] = baseSnapshot.buckets.map((bucket) => {
            const bucketDelta: ShadowVerdictChronicleDeltaPayload['buckets'][number] | undefined = deltaByLabel.get(
                bucket.bucket_label as ChronicleBucketLabel
            );
            const next: ShadowVerdictChronicleBucketPayload = {
                ...bucket,
                metrics: bucket.metrics.map((metric) => ({ ...metric })),
                volumes: bucket.volumes.map((volume) => ({ ...volume })),
                verdict_cloud: bucket.verdict_cloud.map((point) => ({ ...point })),
                regime_gate: (bucket.regime_gate ?? []).map((gatePoint) => ({ ...gatePoint }))
            };
            if (bucketDelta) {
                this.applyBucketDelta(next, bucketDelta, bucket, referenceWallClockMilliseconds);
            }
            return next;
        });

        return {
            ...baseSnapshot,
            generated_at_iso: incrementalPatch.generated_at_iso,
            as_of_iso: incrementalPatch.as_of_iso,
            from_iso: incrementalPatch.from_iso,
            to_iso: incrementalPatch.to_iso,
            total_verdicts_considered: incrementalPatch.total_verdicts_considered,
            source: incrementalPatch.source,
            series_end_lag_seconds: incrementalPatch.series_end_lag_seconds,
            cortex_model_rollouts: baseSnapshot.cortex_model_rollouts,
            buckets
        };
    }

    private applyBucketDelta(
        bucket: ShadowVerdictChronicleBucketPayload,
        delta: ShadowVerdictChronicleDeltaPayload['buckets'][0],
        priorSnapshotBucket: ShadowVerdictChronicleBucketPayload,
        referenceWallClockMilliseconds: number
    ): void {
        const bucketLabel = bucket.bucket_label as ChronicleBucketLabel;
        const retentionFloorServerEpochMilliseconds = computeChronicleRetentionFloorServerEpochMilliseconds(
            bucketLabel,
            bucket.granularity_seconds,
            referenceWallClockMilliseconds
        );

        if (delta.drop_metrics_before_ms != null) {
            const cutoffServerEpochMilliseconds = Math.min(delta.drop_metrics_before_ms, retentionFloorServerEpochMilliseconds);
            bucket.metrics = bucket.metrics.filter((metric) => metric.timestamp_milliseconds >= cutoffServerEpochMilliseconds);
        }
        if (delta.metrics_remove_timestamps_ms?.length) {
            const drop: Set<number> = new Set(
                delta.metrics_remove_timestamps_ms.filter((timestampMilliseconds) => timestampMilliseconds < retentionFloorServerEpochMilliseconds)
            );
            bucket.metrics = bucket.metrics.filter((metric) => !drop.has(metric.timestamp_milliseconds));
        }
        const metricsUpsert = delta.metrics_upsert ?? [];
        if (metricsUpsert.length > 0) {
            const byTimestamp: Map<number, ShadowVerdictChronicleBucketPayload['metrics'][number]> = new Map(
                bucket.metrics.map((metric) => [metric.timestamp_milliseconds, metric])
            );
            for (const point of metricsUpsert) {
                byTimestamp.set(point.timestamp_milliseconds, point);
            }
            bucket.metrics = [...byTimestamp.values()].sort((left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds);
        }

        if (delta.drop_volumes_before_ms != null) {
            const cutoffServerEpochMilliseconds = Math.min(delta.drop_volumes_before_ms, retentionFloorServerEpochMilliseconds);
            bucket.volumes = bucket.volumes.filter((volume) => volume.timestamp_milliseconds >= cutoffServerEpochMilliseconds);
        }
        if (delta.volumes_remove_timestamps_ms?.length) {
            const drop: Set<number> = new Set(
                delta.volumes_remove_timestamps_ms.filter((timestampMilliseconds) => timestampMilliseconds < retentionFloorServerEpochMilliseconds)
            );
            bucket.volumes = bucket.volumes.filter((volume) => !drop.has(volume.timestamp_milliseconds));
        }
        const volumesUpsert = delta.volumes_upsert ?? [];
        if (volumesUpsert.length > 0) {
            const byTimestamp: Map<number, ShadowVerdictChronicleBucketPayload['volumes'][number]> = new Map(
                bucket.volumes.map((volume) => [volume.timestamp_milliseconds, volume])
            );
            for (const point of volumesUpsert) {
                byTimestamp.set(point.timestamp_milliseconds, point);
            }
            bucket.volumes = [...byTimestamp.values()].sort((left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds);
        }

        if (delta.verdict_cloud_replace != null) {
            const mergedByVerdictId = new Map<number, ShadowVerdictChronicleVerdictPointPayload>();
            for (const point of priorSnapshotBucket.verdict_cloud) {
                if (point.timestamp_milliseconds >= retentionFloorServerEpochMilliseconds) {
                    mergedByVerdictId.set(point.verdict_id, { ...point });
                }
            }
            for (const point of delta.verdict_cloud_replace) {
                mergedByVerdictId.set(point.verdict_id, { ...point });
            }
            bucket.verdict_cloud = [...mergedByVerdictId.values()].sort(
                (left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds || left.verdict_id - right.verdict_id
            );
        }

        const regimeGateUpsert = delta.regime_gate_upsert ?? [];
        if (regimeGateUpsert.length > 0) {
            const byTimestamp = new Map((bucket.regime_gate ?? []).map((gatePoint) => [gatePoint.timestamp_milliseconds, gatePoint]));
            for (const gatePoint of regimeGateUpsert) {
                byTimestamp.set(gatePoint.timestamp_milliseconds, gatePoint);
            }
            bucket.regime_gate = [...byTimestamp.values()].sort((left, right) => left.timestamp_milliseconds - right.timestamp_milliseconds);
        }
    }
}
