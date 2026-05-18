from __future__ import annotations

from src.api.http.api_schemas import (
    TradingShadowingRegimeStatusPayload,
    ShadowVerdictChroniclePayload,
    ShadowVerdictChronicleBucketPayload,
    ShadowVerdictChronicleDeltaPayload,
    ShadowVerdictChronicleDeltaBucketPayload,
    ShadowVerdictChronicleMetricPointPayload,
    ShadowVerdictChronicleVolumePointPayload,
    ShadowVerdictChronicleVerdictPointPayload,
    ShadowVerdictChronicleCortexReliabilityBinPayload,
    ShadowVerdictChronicleRegimeGatePointPayload,
    ShadowVerdictChronicleCortexModelRolloutPayload,
    ShadowVerdictChronicleDeltaVerdictPayload,
)
from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingIntelligenceSnapshot,
    TradingShadowingPhase,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingVerdictChronicle,
    TradingShadowingVerdictChronicleBucket,
    TradingShadowingVerdictChronicleVerdict,
)
from src.core.utils.date_utils import format_datetime_to_local_iso
from src.persistence.dao.trading_shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session


def build_shadowing_regime_status_payload(
        snapshot: TradingShadowingIntelligenceSnapshot | None = None,
) -> TradingShadowingRegimeStatusPayload:
    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        probe_dao = TradingShadowingProbeDao(database_session)
        resolved_outcome_count = verdict_dao.count_resolved()
        resolved_shadowing_and_cortex_inference_aware_outcome_count = (
            verdict_dao.count_resolved_shadowing_and_cortex_inference_aware_outcomes()
        )
        elapsed_hours = probe_dao.retrieve_oldest_probe_timestamp()

    required_shadowing_outcomes = settings.TRADING_SHADOWING_MIN_ELIGIBLE_OUTCOMES_FOR_SHADOWING
    required_shadow_gate_outcomes = settings.TRADING_GATE_SHADOWING_MIN_ELIGIBLE_OUTCOMES_FOR_ACTIVATION
    required_cortex_training_outcomes = settings.TRADING_CORTEX_MIN_ELIGIBLE_OUTCOMES_FOR_TRAINING
    required_hours = settings.TRADING_SHADOWING_MIN_HOURS_FOR_ACTIVATION

    shadowing_progress = (
        (resolved_outcome_count / required_shadowing_outcomes) * 100.0
        if required_shadowing_outcomes > 0
        else 100.0
    )
    shadowing_gate_progress = (
        (resolved_shadowing_and_cortex_inference_aware_outcome_count / required_shadow_gate_outcomes) * 100.0
        if required_shadow_gate_outcomes > 0
        else 100.0
    )
    hours_progress = (elapsed_hours / required_hours * 100.0) if required_hours > 0 else 100.0

    shadowing_ready = (
        resolved_outcome_count >= required_shadowing_outcomes
        and elapsed_hours >= required_hours
    )
    shadow_gate_ready = resolved_shadowing_and_cortex_inference_aware_outcome_count >= required_shadow_gate_outcomes
    cortex_training_ready = resolved_shadowing_and_cortex_inference_aware_outcome_count >= required_cortex_training_outcomes
    cortex_training_progress = (
        (resolved_shadowing_and_cortex_inference_aware_outcome_count / required_cortex_training_outcomes) * 100.0
        if shadow_gate_ready and required_cortex_training_outcomes > 0
        else 0.0
    )
    is_shadow_gate_enabled = settings.TRADING_GATE_SHADOWING_REGIME_ENABLED
    is_cortex_requirement_enabled = settings.TRADING_GATE_CORTEX_ENABLED or settings.TRADING_CORTEX_ENABLED
    shadow_gate_unlocked = shadowing_ready and (shadow_gate_ready or not is_shadow_gate_enabled)
    is_tradable = shadow_gate_unlocked and (cortex_training_ready or not is_cortex_requirement_enabled)
    if not settings.TRADING_SHADOWING_ENABLED:
        phase = TradingShadowingPhase.DISABLED
    elif is_tradable:
        phase = TradingShadowingPhase.TRADABLE
    elif is_cortex_requirement_enabled and shadow_gate_unlocked:
        phase = TradingShadowingPhase.CORTEXING
    else:
        phase = TradingShadowingPhase.SHADOWING

    return TradingShadowingRegimeStatusPayload(
        is_enabled=settings.TRADING_SHADOWING_ENABLED,
        shadow_regime_gate_enabled=settings.TRADING_GATE_SHADOWING_REGIME_ENABLED,
        phase=phase,
        total_outcomes_analyzed=snapshot.summary.total_outcomes_analyzed if snapshot is not None else resolved_outcome_count,
        resolved_outcome_count=resolved_outcome_count,
        resolved_shadowing_and_cortex_inference_aware_outcome_count=resolved_shadowing_and_cortex_inference_aware_outcome_count,
        required_shadowing_outcome_count=required_shadowing_outcomes,
        required_shadow_gate_outcome_count=required_shadow_gate_outcomes,
        required_cortex_training_outcome_count=required_cortex_training_outcomes,
        elapsed_hours=elapsed_hours,
        required_hours=required_hours,
        shadowing_progress_percentage=min(100.0, shadowing_progress),
        shadowing_gate_progress_percentage=min(100.0, shadowing_gate_progress),
        cortex_training_progress_percentage=min(100.0, cortex_training_progress),
        hours_progress_percentage=min(100.0, hours_progress),
        win_rate_percentage=(snapshot.summary.meta_win_rate * 100.0) if snapshot is not None and snapshot.summary.meta_win_rate is not None else None,
        global_profit_factor=snapshot.summary.meta_profit_factor if snapshot is not None else None,
        expected_value_usd=snapshot.summary.meta_expected_value_usd if snapshot is not None else None,
        expected_pnl_velocity=snapshot.summary.meta_expected_pnl_velocity if snapshot is not None else None,
        chronicle_profit_factor=snapshot.summary.chronicle_profit_factor if snapshot is not None else None,
        chronicle_profit_factor_threshold=snapshot.summary.chronicle_profit_factor_threshold if snapshot is not None else None,
        chronicle_profit_factor_lookback_days=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_LOOKBACK_DAYS,
        chronicle_profit_factor_bucket_width_seconds=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_BUCKET_WIDTH_SECONDS,
        chronicle_profit_factor_moving_average_period=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_PERIOD,
        sparse_expected_value_usd=snapshot.summary.sparse_expected_value_usd if snapshot is not None else None,
        sparse_expected_value_usd_threshold=snapshot.summary.sparse_expected_value_usd_threshold if snapshot is not None else None,
        sparse_expected_value_lookback_days=settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_LOOKBACK_DAYS,
        sparse_expected_value_bucket_width_seconds=settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_BUCKET_WIDTH_SECONDS,
        sparse_expected_value_moving_average_period=settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_PERIOD,
    )


def _build_bucket_payload(bucket: TradingShadowingVerdictChronicleBucket) -> ShadowVerdictChronicleBucketPayload:
    metrics = [
        ShadowVerdictChronicleMetricPointPayload(**m.model_dump())
        for m in bucket.metrics
    ]
    volumes = [
        ShadowVerdictChronicleVolumePointPayload(**v.model_dump())
        for v in bucket.volumes
    ]
    verdict_cloud = [
        ShadowVerdictChronicleVerdictPointPayload(**v.model_dump())
        for v in bucket.verdict_cloud
    ]
    regime_gate = [
        ShadowVerdictChronicleRegimeGatePointPayload(**gate_point.model_dump())
        for gate_point in bucket.regime_gate
    ]
    cortex_reliability_diagram = [
        ShadowVerdictChronicleCortexReliabilityBinPayload(**bin_point.model_dump())
        for bin_point in bucket.cortex_reliability_diagram
    ]
    return ShadowVerdictChronicleBucketPayload(
        bucket_label=bucket.bucket_label,
        granularity_seconds=bucket.granularity_seconds,
        from_iso=format_datetime_to_local_iso(bucket.from_datetime) or "",
        to_iso=format_datetime_to_local_iso(bucket.to_datetime) or "",
        metrics=metrics,
        volumes=volumes,
        verdict_cloud=verdict_cloud,
        cortex_reliability_diagram=cortex_reliability_diagram,
        regime_gate=regime_gate,
    )


def build_shadow_verdict_chronicle_payload(chronicle: TradingShadowingVerdictChronicle) -> ShadowVerdictChroniclePayload:
    buckets = [_build_bucket_payload(b) for b in chronicle.buckets]
    cortex_model_rollouts = [
        ShadowVerdictChronicleCortexModelRolloutPayload(**rollout.model_dump())
        for rollout in chronicle.cortex_model_rollouts
    ]
    return ShadowVerdictChroniclePayload(
        generated_at_iso=format_datetime_to_local_iso(chronicle.generated_at) or "",
        as_of_iso=format_datetime_to_local_iso(chronicle.as_of) or "",
        from_iso=format_datetime_to_local_iso(chronicle.from_datetime) or "",
        to_iso=format_datetime_to_local_iso(chronicle.to_datetime) or "",
        total_verdicts_considered=chronicle.total_verdicts_considered,
        source=chronicle.source,
        series_end_lag_seconds=settings.TRADING_SHADOWING_HISTORY_SERIES_END_LAG_SECONDS,
        buckets=buckets,
        cortex_model_rollouts=cortex_model_rollouts,
    )


def build_shadow_verdict_chronicle_incremental_delta_payload(
        new_chronicle: TradingShadowingVerdictChronicle,
        new_verdicts: list[TradingShadowingVerdictChronicleVerdict],
        previous_as_of_ms: int,
        generated_at_iso: str,
        as_of_iso: str,
        from_iso: str,
        to_iso: str,
) -> ShadowVerdictChronicleDeltaPayload:
    buckets_payload: list[ShadowVerdictChronicleDeltaBucketPayload] = []
    global_from_ms = int(new_chronicle.from_datetime.timestamp() * 1000)

    for new_bucket in new_chronicle.buckets:
        new_metrics = [m for m in new_bucket.metrics if m.timestamp_milliseconds >= previous_as_of_ms]
        new_volumes = [v for v in new_bucket.volumes if v.timestamp_milliseconds >= previous_as_of_ms]

        bucket_payload = ShadowVerdictChronicleDeltaBucketPayload(
            bucket_label=new_bucket.bucket_label,
            drop_metrics_before_ms=global_from_ms,
            drop_volumes_before_ms=global_from_ms,
            metrics_remove_timestamps_ms=[],
            volumes_remove_timestamps_ms=[],
            metrics_upsert=[
                ShadowVerdictChronicleMetricPointPayload(
                    timestamp_milliseconds=m.timestamp_milliseconds,
                    average_pnl_percentage=m.average_pnl_percentage,
                    average_win_rate_percentage=m.average_win_rate_percentage,
                    expected_value_per_trade_usd=m.expected_value_per_trade_usd,
                    closed_verdicts_per_hour=m.closed_verdicts_per_hour,
                    profit_factor=m.profit_factor,
                    average_cortex_prediction_win_rate_percentage=m.average_cortex_prediction_win_rate_percentage,
                    average_cortex_predicted_holding_time_minutes=m.average_cortex_predicted_holding_time_minutes,
                    cortex_skill_score_percentage=m.cortex_skill_score_percentage,
                    cortex_calibration_gap_percentage_points=m.cortex_calibration_gap_percentage_points,
                    cortex_high_conviction_accuracy_percentage=m.cortex_high_conviction_accuracy_percentage,
                    cortex_high_conviction_share_percentage=m.cortex_high_conviction_share_percentage,
                    cortex_gate_precision_percentage=m.cortex_gate_precision_percentage,
                    cortex_gate_pass_rate_percentage=m.cortex_gate_pass_rate_percentage,
                ) for m in new_metrics
            ],
            volumes_upsert=[
                ShadowVerdictChronicleVolumePointPayload(
                    timestamp_milliseconds=v.timestamp_milliseconds,
                    verdict_count=v.verdict_count,
                ) for v in new_volumes
            ],
            regime_gate_upsert=[
                ShadowVerdictChronicleRegimeGatePointPayload(**gate_point.model_dump())
                for gate_point in new_bucket.regime_gate
                if gate_point.timestamp_milliseconds >= previous_as_of_ms
            ],
            verdict_cloud_replace=None,
            cortex_reliability_diagram_replace=[
                ShadowVerdictChronicleCortexReliabilityBinPayload(**bin_point.model_dump())
                for bin_point in new_bucket.cortex_reliability_diagram
            ],
        )
        buckets_payload.append(bucket_payload)

    verdicts_payload = [
        ShadowVerdictChronicleDeltaVerdictPayload(
            id=v.id,
            resolved_at=v.resolved_at,
            realized_pnl_percentage=v.realized_pnl_percentage,
            realized_pnl_usd=v.realized_pnl_usd,
            is_profitable=v.is_profitable,
            exit_reason=v.exit_reason,
            order_notional_value_usd=v.order_notional_value_usd,
            cortex_probability=v.cortex_probability,
        ) for v in new_verdicts
    ]

    return ShadowVerdictChronicleDeltaPayload(
        generated_at_iso=generated_at_iso,
        as_of_iso=as_of_iso,
        from_iso=from_iso,
        to_iso=to_iso,
        total_verdicts_considered=new_chronicle.total_verdicts_considered,
        source="computed_incremental",
        series_end_lag_seconds=settings.TRADING_SHADOWING_HISTORY_SERIES_END_LAG_SECONDS,
        buckets=buckets_payload,
        verdicts=verdicts_payload,
    )
