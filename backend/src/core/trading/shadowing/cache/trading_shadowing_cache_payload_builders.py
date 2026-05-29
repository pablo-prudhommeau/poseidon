from __future__ import annotations

from src.api.http.api_schemas import (
    TradingShadowingRegimePayload,
    TradingShadowingVerdictChroniclePayload,
    TradingShadowingVerdictChronicleBucketPayload,
    TradingShadowingVerdictChronicleDeltaPayload,
    TradingShadowingVerdictChronicleDeltaBucketPayload,
    TradingShadowingVerdictChronicleMetricPointPayload,
    TradingShadowingVerdictChronicleVolumePointPayload,
    TradingShadowingVerdictChronicleVerdictPointPayload,
    TradingShadowingVerdictChronicleCortexReliabilityBinPayload,
    TradingShadowingVerdictChronicleRegimeGatePointPayload,
    TradingShadowingVerdictChronicleCortexModelRolloutPayload,
    TradingShadowingVerdictChronicleDeltaVerdictPayload,
)
from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingSnapshot,
    TradingShadowingVerdictChronicle,
    TradingShadowingVerdictChronicleBucket,
    TradingShadowingVerdictChronicleCortexModelRollout,
    TradingShadowingVerdictChronicleCortexReliabilityBin,
    TradingShadowingVerdictChronicleMetricPoint,
    TradingShadowingVerdictChronicleRegimeGatePoint,
    TradingShadowingVerdictChronicleVerdict,
    TradingShadowingVerdictChronicleVerdictPoint,
    TradingShadowingVerdictChronicleVolumePoint,
)
from src.core.utils.date_utils import format_datetime_to_local_iso


def build_shadowing_regime_payload(snapshot: TradingShadowingSnapshot) -> TradingShadowingRegimePayload:
    shadowing_regime = snapshot.regime
    return TradingShadowingRegimePayload(
        phase=shadowing_regime.phase,
        edge_gate_enabled=shadowing_regime.edge_gate_enabled,
        cortex_gate_enabled=shadowing_regime.cortex_gate_enabled,
        fundamentals_gate_enabled=shadowing_regime.fundamentals_gate_enabled,
        toxic_metrics_gate_enabled=shadowing_regime.toxic_metrics_gate_enabled,
        resolved_outcome_count=shadowing_regime.resolved_outcome_count,
        required_outcome_count=shadowing_regime.required_outcome_count,
        elapsed_hours=shadowing_regime.elapsed_hours,
        required_hours=shadowing_regime.required_hours,
        edge_eligible_outcome_count=shadowing_regime.edge_eligible_outcome_count,
        edge_required_outcome_count=shadowing_regime.edge_required_outcome_count,
        edge_chronicle_profit_factor=shadowing_regime.edge_chronicle_profit_factor,
        edge_chronicle_profit_factor_threshold=shadowing_regime.edge_chronicle_profit_factor_threshold,
        edge_chronicle_profit_factor_lookback_days=shadowing_regime.edge_chronicle_profit_factor_lookback_days,
        edge_chronicle_profit_factor_bucket_width_seconds=shadowing_regime.edge_chronicle_profit_factor_bucket_width_seconds,
        edge_chronicle_profit_factor_moving_average_period=shadowing_regime.edge_chronicle_profit_factor_moving_average_period,
        edge_sparse_expected_value_usd=shadowing_regime.edge_sparse_expected_value_usd,
        edge_sparse_expected_value_usd_threshold=shadowing_regime.edge_sparse_expected_value_usd_threshold,
        edge_sparse_expected_value_lookback_days=shadowing_regime.edge_sparse_expected_value_lookback_days,
        edge_sparse_expected_value_bucket_width_seconds=shadowing_regime.edge_sparse_expected_value_bucket_width_seconds,
        edge_sparse_expected_value_moving_average_period=shadowing_regime.edge_sparse_expected_value_moving_average_period,
        metrics_meta_win_rate=shadowing_regime.metrics_meta_win_rate,
        metrics_meta_average_pnl=shadowing_regime.metrics_meta_average_pnl,
        metrics_meta_average_holding_time_hours=shadowing_regime.metrics_meta_average_holding_time_hours,
        metrics_meta_expected_pnl_velocity=shadowing_regime.metrics_meta_expected_pnl_velocity,
        metrics_meta_profit_factor=shadowing_regime.metrics_meta_profit_factor,
        metrics_meta_expected_value_usd=shadowing_regime.metrics_meta_expected_value_usd,
        cortex_training_eligible_outcome_count=shadowing_regime.cortex_training_eligible_outcome_count,
        cortex_training_required_outcome_count=shadowing_regime.cortex_training_required_outcome_count,
    )


def _build_metric_point_payload(metric_point: TradingShadowingVerdictChronicleMetricPoint) -> TradingShadowingVerdictChronicleMetricPointPayload:
    return TradingShadowingVerdictChronicleMetricPointPayload(
        timestamp_milliseconds=metric_point.timestamp_milliseconds,
        average_pnl_percentage=metric_point.average_pnl_percentage,
        average_win_rate_percentage=metric_point.average_win_rate_percentage,
        expected_value_per_trade_usd=metric_point.expected_value_per_trade_usd,
        portfolio_equity_usd=metric_point.portfolio_equity_usd,
        closed_verdicts_per_hour=metric_point.closed_verdicts_per_hour,
        profit_factor=metric_point.profit_factor,
        average_cortex_prediction_win_rate_percentage=metric_point.average_cortex_prediction_win_rate_percentage,
        average_cortex_predicted_holding_time_minutes=metric_point.average_cortex_predicted_holding_time_minutes,
        cortex_skill_score_percentage=metric_point.cortex_skill_score_percentage,
        cortex_calibration_gap_percentage_points=metric_point.cortex_calibration_gap_percentage_points,
        cortex_high_conviction_accuracy_percentage=metric_point.cortex_high_conviction_accuracy_percentage,
        cortex_high_conviction_share_percentage=metric_point.cortex_high_conviction_share_percentage,
        cortex_gate_precision_percentage=metric_point.cortex_gate_precision_percentage,
        cortex_gate_pass_rate_percentage=metric_point.cortex_gate_pass_rate_percentage,
    )


def _build_volume_point_payload(volume_point: TradingShadowingVerdictChronicleVolumePoint) -> TradingShadowingVerdictChronicleVolumePointPayload:
    return TradingShadowingVerdictChronicleVolumePointPayload(
        timestamp_milliseconds=volume_point.timestamp_milliseconds,
        verdict_count=volume_point.verdict_count,
    )


def _build_verdict_point_payload(verdict_point: TradingShadowingVerdictChronicleVerdictPoint) -> TradingShadowingVerdictChronicleVerdictPointPayload:
    return TradingShadowingVerdictChronicleVerdictPointPayload(
        verdict_id=verdict_point.verdict_id,
        timestamp_milliseconds=verdict_point.timestamp_milliseconds,
        pnl_percentage=verdict_point.pnl_percentage,
        pnl_usd=verdict_point.pnl_usd,
        exit_reason=verdict_point.exit_reason,
        order_notional_usd=verdict_point.order_notional_usd,
        point_size=verdict_point.point_size,
        is_profitable=verdict_point.is_profitable,
        cortex_probability=verdict_point.cortex_probability,
    )


def _build_regime_gate_point_payload(regime_gate_point: TradingShadowingVerdictChronicleRegimeGatePoint) -> TradingShadowingVerdictChronicleRegimeGatePointPayload:
    return TradingShadowingVerdictChronicleRegimeGatePointPayload(
        timestamp_milliseconds=regime_gate_point.timestamp_milliseconds,
        regime_profit_factor_sma=regime_gate_point.regime_profit_factor_sma,
        regime_sparse_expected_value_usd_sma=regime_gate_point.regime_sparse_expected_value_usd_sma,
        profit_factor_gate_open=regime_gate_point.profit_factor_gate_open,
        sparse_expected_value_gate_open=regime_gate_point.sparse_expected_value_gate_open,
        hard_gate_open=regime_gate_point.hard_gate_open,
    )


def _build_cortex_reliability_bin_payload(cortex_reliability_bin: TradingShadowingVerdictChronicleCortexReliabilityBin) -> TradingShadowingVerdictChronicleCortexReliabilityBinPayload:
    return TradingShadowingVerdictChronicleCortexReliabilityBinPayload(
        predicted_probability_bin_center=cortex_reliability_bin.predicted_probability_bin_center,
        mean_predicted_probability=cortex_reliability_bin.mean_predicted_probability,
        empirical_win_rate=cortex_reliability_bin.empirical_win_rate,
        verdict_count=cortex_reliability_bin.verdict_count,
    )


def _build_cortex_model_rollout_payload(cortex_model_rollout: TradingShadowingVerdictChronicleCortexModelRollout) -> TradingShadowingVerdictChronicleCortexModelRolloutPayload:
    return TradingShadowingVerdictChronicleCortexModelRolloutPayload(
        activated_at_milliseconds=cortex_model_rollout.activated_at_milliseconds,
        model_version=cortex_model_rollout.model_version,
        feature_set_version=cortex_model_rollout.feature_set_version,
        training_record_count=cortex_model_rollout.training_record_count,
        validation_record_count=cortex_model_rollout.validation_record_count,
        success_probability_accuracy=cortex_model_rollout.success_probability_accuracy,
        is_active=cortex_model_rollout.is_active,
        label=cortex_model_rollout.label,
    )


def _build_bucket_payload(chronicle_bucket: TradingShadowingVerdictChronicleBucket) -> TradingShadowingVerdictChronicleBucketPayload:
    metrics = [
        _build_metric_point_payload(metric_point)
        for metric_point in chronicle_bucket.metrics
    ]
    volumes = [
        _build_volume_point_payload(volume_point)
        for volume_point in chronicle_bucket.volumes
    ]
    verdict_cloud = [
        _build_verdict_point_payload(verdict_point)
        for verdict_point in chronicle_bucket.verdict_cloud
    ]
    regime_gate = [
        _build_regime_gate_point_payload(regime_gate_point)
        for regime_gate_point in chronicle_bucket.regime_gate
    ]
    cortex_reliability_diagram = [
        _build_cortex_reliability_bin_payload(cortex_reliability_bin)
        for cortex_reliability_bin in chronicle_bucket.cortex_reliability_diagram
    ]
    return TradingShadowingVerdictChronicleBucketPayload(
        bucket_label=chronicle_bucket.bucket_label,
        granularity_seconds=chronicle_bucket.granularity_seconds,
        from_iso=format_datetime_to_local_iso(chronicle_bucket.from_datetime) or "",
        to_iso=format_datetime_to_local_iso(chronicle_bucket.to_datetime) or "",
        metrics=metrics,
        volumes=volumes,
        verdict_cloud=verdict_cloud,
        cortex_reliability_diagram=cortex_reliability_diagram,
        regime_gate=regime_gate,
    )


def build_trading_shadowing_verdict_chronicle_payload(chronicle: TradingShadowingVerdictChronicle) -> TradingShadowingVerdictChroniclePayload:
    buckets = [
        _build_bucket_payload(chronicle_bucket)
        for chronicle_bucket in chronicle.buckets
    ]
    cortex_model_rollouts = [
        _build_cortex_model_rollout_payload(cortex_model_rollout)
        for cortex_model_rollout in chronicle.cortex_model_rollouts
    ]
    return TradingShadowingVerdictChroniclePayload(
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


def _build_delta_verdict_payload(verdict: TradingShadowingVerdictChronicleVerdict) -> TradingShadowingVerdictChronicleDeltaVerdictPayload:
    return TradingShadowingVerdictChronicleDeltaVerdictPayload(
        id=verdict.id,
        resolved_at=verdict.resolved_at,
        realized_pnl_percentage=verdict.realized_pnl_percentage,
        realized_pnl_usd=verdict.realized_pnl_usd,
        is_profitable=verdict.is_profitable,
        exit_reason=verdict.exit_reason,
        order_notional_value_usd=verdict.order_notional_value_usd,
        cortex_probability=verdict.cortex_probability,
    )


def build_trading_shadowing_verdict_chronicle_incremental_delta_payload(
        new_chronicle: TradingShadowingVerdictChronicle,
        new_verdicts: list[TradingShadowingVerdictChronicleVerdict],
        previous_as_of_timestamp_milliseconds: int,
        generated_at_iso: str,
        as_of_iso: str,
        from_iso: str,
        to_iso: str,
) -> TradingShadowingVerdictChronicleDeltaPayload:
    buckets_payload: list[TradingShadowingVerdictChronicleDeltaBucketPayload] = []
    global_from_timestamp_milliseconds = int(new_chronicle.from_datetime.timestamp() * 1000)

    for chronicle_bucket in new_chronicle.buckets:
        new_metrics = [
            metric_point
            for metric_point in chronicle_bucket.metrics
            if metric_point.timestamp_milliseconds >= previous_as_of_timestamp_milliseconds
        ]
        new_volumes = [
            volume_point
            for volume_point in chronicle_bucket.volumes
            if volume_point.timestamp_milliseconds >= previous_as_of_timestamp_milliseconds
        ]

        bucket_payload = TradingShadowingVerdictChronicleDeltaBucketPayload(
            bucket_label=chronicle_bucket.bucket_label,
            drop_metrics_before_ms=global_from_timestamp_milliseconds,
            drop_volumes_before_ms=global_from_timestamp_milliseconds,
            metrics_remove_timestamps_ms=[],
            volumes_remove_timestamps_ms=[],
            metrics_upsert=[
                _build_metric_point_payload(metric_point)
                for metric_point in new_metrics
            ],
            volumes_upsert=[
                _build_volume_point_payload(volume_point)
                for volume_point in new_volumes
            ],
            regime_gate_upsert=[
                _build_regime_gate_point_payload(regime_gate_point)
                for regime_gate_point in chronicle_bucket.regime_gate
                if regime_gate_point.timestamp_milliseconds >= previous_as_of_timestamp_milliseconds
            ],
            verdict_cloud_replace=None,
            cortex_reliability_diagram_replace=[
                _build_cortex_reliability_bin_payload(cortex_reliability_bin)
                for cortex_reliability_bin in chronicle_bucket.cortex_reliability_diagram
            ],
        )
        buckets_payload.append(bucket_payload)

    verdicts_payload = [
        _build_delta_verdict_payload(verdict)
        for verdict in new_verdicts
    ]

    return TradingShadowingVerdictChronicleDeltaPayload(
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
