from __future__ import annotations

from src.api.http.api_schemas import (
    ShadowIntelligenceStatusPayload,
    TradingShadowMetaPayload,
    ShadowVerdictChroniclePayload,
    ShadowVerdictChronicleBucketPayload,
    ShadowVerdictChronicleDeltaPayload,
    ShadowVerdictChronicleDeltaBucketPayload,
    ShadowVerdictChronicleMetricPointPayload,
    ShadowVerdictChronicleVolumePointPayload,
    ShadowVerdictChronicleVerdictPointPayload,
    ShadowVerdictChronicleDeltaVerdictPayload,
)
from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_structures import ShadowIntelligenceSnapshot
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingVerdictChronicle,
    TradingShadowingVerdictChronicleBucket,
    TradingShadowingVerdictChronicleVerdict,
)
from src.core.utils.date_utils import format_datetime_to_local_iso
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session


def build_shadow_intelligence_status_payload() -> ShadowIntelligenceStatusPayload:
    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        status_summary = verdict_dao.retrieve_shadow_intelligence_status_summary()

    required_outcomes = settings.TRADING_SHADOWING_MIN_OUTCOMES_FOR_ACTIVATION
    required_hours = settings.TRADING_SHADOWING_MIN_HOURS_FOR_ACTIVATION

    outcome_progress = (status_summary.resolved_outcome_count / required_outcomes * 100.0) if required_outcomes > 0 else 100.0
    hours_progress = (status_summary.elapsed_hours / required_hours * 100.0) if required_hours > 0 else 100.0

    is_activated = status_summary.resolved_outcome_count >= required_outcomes and status_summary.elapsed_hours >= required_hours
    phase = "ACTIVE" if is_activated else "LEARNING"
    if not settings.TRADING_SHADOWING_ENABLED:
        phase = "DISABLED"

    return ShadowIntelligenceStatusPayload(
        is_enabled=settings.TRADING_SHADOWING_ENABLED,
        phase=phase,
        resolved_outcome_count=status_summary.resolved_outcome_count,
        required_outcome_count=required_outcomes,
        elapsed_hours=status_summary.elapsed_hours,
        required_hours=required_hours,
        outcome_progress_percentage=min(100.0, outcome_progress),
        hours_progress_percentage=min(100.0, hours_progress),
    )


def build_trading_shadow_meta_payload(snapshot: ShadowIntelligenceSnapshot) -> TradingShadowMetaPayload:
    phase = "ACTIVE" if snapshot.is_activated else "LEARNING"
    if not settings.TRADING_SHADOWING_ENABLED:
        phase = "DISABLED"

    return TradingShadowMetaPayload(
        is_enabled=settings.TRADING_SHADOWING_ENABLED,
        is_activated=snapshot.is_activated,
        phase=phase,
        total_outcomes_analyzed=snapshot.total_outcomes_analyzed,
        resolved_outcome_count=snapshot.resolved_outcome_count,
        elapsed_hours=snapshot.elapsed_hours,
        win_rate_percentage=snapshot.meta_win_rate * 100.0,
        global_profit_factor=snapshot.meta_profit_factor,
        expected_value_usd=snapshot.meta_expected_value_usd,
        capital_velocity=snapshot.meta_capital_velocity,
        empirical_profit_factor=snapshot.empirical_profit_factor,
        empirical_profit_factor_threshold=settings.TRADING_SHADOWING_REGIME_EMPIRICAL_PROFIT_FACTOR_THRESHOLD,
        empirical_profit_factor_window_verdict_count=settings.TRADING_SHADOWING_REGIME_EMPIRICAL_PROFIT_FACTOR_WINDOW_VERDICT_COUNT,
        chronicle_profit_factor=snapshot.chronicle_profit_factor,
        chronicle_profit_factor_threshold=snapshot.chronicle_profit_factor_threshold,
        chronicle_profit_factor_lookback_days=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_LOOKBACK_DAYS,
        chronicle_profit_factor_bucket_width_seconds=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_BUCKET_WIDTH_SECONDS,
        chronicle_profit_factor_moving_average_period=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_PERIOD,
        sparse_expected_value_usd=snapshot.sparse_expected_value_usd,
        sparse_expected_value_usd_threshold=settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_USD_THRESHOLD,
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
    return ShadowVerdictChronicleBucketPayload(
        bucket_label=bucket.bucket_label,
        granularity_seconds=bucket.granularity_seconds,
        from_iso=format_datetime_to_local_iso(bucket.from_datetime) or "",
        to_iso=format_datetime_to_local_iso(bucket.to_datetime) or "",
        metrics=metrics,
        volumes=volumes,
        verdict_cloud=verdict_cloud,
    )


def build_shadow_verdict_chronicle_payload(chronicle: TradingShadowingVerdictChronicle) -> ShadowVerdictChroniclePayload:
    buckets = [_build_bucket_payload(b) for b in chronicle.buckets]
    return ShadowVerdictChroniclePayload(
        generated_at_iso=format_datetime_to_local_iso(chronicle.generated_at) or "",
        as_of_iso=format_datetime_to_local_iso(chronicle.as_of) or "",
        from_iso=format_datetime_to_local_iso(chronicle.from_datetime) or "",
        to_iso=format_datetime_to_local_iso(chronicle.to_datetime) or "",
        total_verdicts_considered=chronicle.total_verdicts_considered,
        source=chronicle.source,
        series_end_lag_seconds=settings.TRADING_SHADOWING_HISTORY_SERIES_END_LAG_SECONDS,
        buckets=buckets,
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
                    capital_velocity_per_hour=m.capital_velocity_per_hour,
                    profit_factor=m.profit_factor,
                ) for m in new_metrics
            ],
            volumes_upsert=[
                ShadowVerdictChronicleVolumePointPayload(
                    timestamp_milliseconds=v.timestamp_milliseconds,
                    verdict_count=v.verdict_count,
                ) for v in new_volumes
            ],
            verdict_cloud_replace=None,
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
