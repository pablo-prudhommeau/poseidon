from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Iterable

from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingVerdictChronicleBucketConfiguration,
    TradingShadowingVerdictChronicleVerdict,
    TradingShadowingVerdictChronicleMetricPoint,
    TradingShadowingVerdictChronicleVolumePoint,
    TradingShadowingVerdictChronicleVerdictPoint,
    TradingShadowingVerdictChronicleBucket,
    TradingShadowingVerdictChronicle,
    TradingShadowingVerdictChronicleComputationResult,
)
from src.core.utils.date_utils import (
    ensure_timezone_aware,
    get_current_local_datetime,
)
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.db import get_database_session
from src.persistence.models import TradingShadowingVerdict

logger = get_application_logger(__name__)


def compute_shadow_verdict_chronicle() -> TradingShadowingVerdictChronicleComputationResult:
    now_local = get_current_local_datetime()
    bucket_configurations = _shadow_verdict_chronicle_bucket_configurations()
    series_end_datetime = _series_end_datetime(now_local)
    fetch_end_datetime = _verdict_fetch_end_datetime(series_end_datetime, bucket_configurations)
    global_from_datetime = series_end_datetime - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)

    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        resolved_verdicts = verdict_dao.retrieve_resolved_in_window(
            start_datetime=global_from_datetime,
            end_datetime=fetch_end_datetime,
            limit_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
        )
        verdicts = _convert_verdicts(resolved_verdicts)

    logger.info(
        "[TRADING][SHADOW][HISTORY] Full chronicle built — verdict_count=%d bucket_layer_count=%d",
        len(verdicts),
        len(bucket_configurations),
    )
    return TradingShadowingVerdictChronicleComputationResult(
        chronicle=_build_shadow_verdict_chronicle(verdicts, now_local, bucket_configurations, series_end_datetime, fetch_end_datetime, global_from_datetime),
        verdicts=verdicts,
    )


def compute_shadow_verdict_chronicle_incremental(
        previous_verdicts: list[TradingShadowingVerdictChronicleVerdict],
) -> TradingShadowingVerdictChronicleComputationResult:
    now_local = get_current_local_datetime()
    bucket_configurations = _shadow_verdict_chronicle_bucket_configurations()
    series_end_datetime = _series_end_datetime(now_local)
    fetch_end_datetime = _verdict_fetch_end_datetime(series_end_datetime, bucket_configurations)
    global_from_datetime = series_end_datetime - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)

    working_verdicts = _trim_verdicts_for_window(
        previous_verdicts,
        global_from_datetime=global_from_datetime,
        fetch_end_datetime=fetch_end_datetime,
        max_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
    )
    if not working_verdicts:
        return compute_shadow_verdict_chronicle()

    max_id = max(chronicle_verdict.id for chronicle_verdict in working_verdicts)
    new_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []
    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        new_orms = verdict_dao.retrieve_resolved_in_window_after_id(
            after_id_exclusive=max_id,
            start_datetime=global_from_datetime,
            end_datetime=fetch_end_datetime,
            limit_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
        )
        new_verdicts = _convert_verdicts(new_orms)

    if new_verdicts:
        merged_by_id = {chronicle_verdict.id: chronicle_verdict for chronicle_verdict in working_verdicts}
        for chronicle_verdict in new_verdicts:
            merged_by_id[chronicle_verdict.id] = chronicle_verdict
        working_verdicts = sorted(merged_by_id.values(), key=lambda chronicle_verdict: chronicle_verdict.resolved_at)
        working_verdicts = _trim_verdicts_for_window(
            working_verdicts,
            global_from_datetime=global_from_datetime,
            fetch_end_datetime=fetch_end_datetime,
            max_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
        )

    new_chronicle = _build_shadow_verdict_chronicle(working_verdicts, now_local, bucket_configurations, series_end_datetime, fetch_end_datetime, global_from_datetime)
    logger.debug(
        "[TRADING][SHADOW][HISTORY] Incremental chronicle — verdict_count=%d new_verdict_count_from_database=%d",
        len(working_verdicts),
        len(new_verdicts),
    )
    return TradingShadowingVerdictChronicleComputationResult(
        chronicle=new_chronicle,
        verdicts=working_verdicts,
    )


def _build_shadow_verdict_chronicle(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        now_local: datetime,
        bucket_configurations: list[TradingShadowingVerdictChronicleBucketConfiguration],
        series_end_datetime: datetime,
        fetch_end_datetime: datetime,
        global_from_datetime: datetime,
) -> TradingShadowingVerdictChronicle:
    buckets: list[TradingShadowingVerdictChronicleBucket] = []
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS
    chronicle_lag_td = _chronicle_display_lag_timedelta()
    for bucket_configuration in bucket_configurations:
        bucket_from_datetime = max(
            global_from_datetime,
            series_end_datetime - bucket_configuration.lookback - chronicle_lag_td,
        )
        bucket_to_datetime = series_end_datetime + timedelta(
            seconds=bucket_configuration.granularity_seconds * max(0, trailing),
        )
        buckets.append(_build_bucket(
            verdicts=verdicts,
            bucket_configuration=bucket_configuration,
            from_datetime=bucket_from_datetime,
            to_datetime=bucket_to_datetime,
        ))

    return TradingShadowingVerdictChronicle(
        generated_at=now_local,
        as_of=series_end_datetime,
        from_datetime=global_from_datetime,
        to_datetime=fetch_end_datetime,
        total_verdicts_considered=len(verdicts),
        source="computed",
        buckets=buckets,
    )


def _build_bucket(
        verdicts: Iterable[TradingShadowingVerdictChronicleVerdict],
        bucket_configuration: TradingShadowingVerdictChronicleBucketConfiguration,
        from_datetime: datetime,
        to_datetime: datetime,
) -> TradingShadowingVerdictChronicleBucket:
    window_from = ensure_timezone_aware(from_datetime)
    window_to = ensure_timezone_aware(to_datetime)
    assert window_from is not None and window_to is not None

    grouped_verdicts: dict[int, list[TradingShadowingVerdictChronicleVerdict]] = defaultdict(list)
    bounded_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []

    for verdict in verdicts:
        resolved_at = ensure_timezone_aware(verdict.resolved_at)
        if resolved_at is None:
            continue
        if resolved_at < window_from or resolved_at > window_to:
            continue
        bounded_verdicts.append(verdict)
        bucket_start = _floor_datetime_to_granularity(resolved_at, bucket_configuration.granularity_seconds)
        grouped_verdicts[_to_epoch_milliseconds(bucket_start)].append(verdict)

    metric_points: list[TradingShadowingVerdictChronicleMetricPoint] = []
    volume_points: list[TradingShadowingVerdictChronicleVolumePoint] = []

    for bucket_timestamp in sorted(grouped_verdicts.keys()):
        items = grouped_verdicts[bucket_timestamp]
        verdict_count = len(items)
        if verdict_count == 0:
            continue

        pnl_usd_values = [item.realized_pnl_usd for item in items]
        pnl_percentage_values = [item.realized_pnl_percentage for item in items]
        win_count = sum(1 for item in items if item.is_profitable)
        gross_profit_usd = sum(value for value in pnl_usd_values if value > 0.0)
        gross_loss_usd = abs(sum(value for value in pnl_usd_values if value < 0.0))

        metric_points.append(TradingShadowingVerdictChronicleMetricPoint(
            timestamp_milliseconds=bucket_timestamp,
            average_pnl_percentage=sum(pnl_percentage_values) / verdict_count,
            average_win_rate_percentage=(win_count / verdict_count) * 100.0,
            expected_value_per_trade_usd=sum(pnl_usd_values) / verdict_count,
            capital_velocity_per_hour=_compute_velocity_per_hour(verdict_count, bucket_configuration.granularity_seconds),
            profit_factor=_compute_profit_factor(gross_profit_usd, gross_loss_usd),
        ))
        volume_points.append(TradingShadowingVerdictChronicleVolumePoint(
            timestamp_milliseconds=bucket_timestamp,
            verdict_count=verdict_count,
        ))

    cloud_source = _sample_cloud_points(
        sorted(bounded_verdicts, key=lambda verdict: verdict.resolved_at),
        settings.TRADING_SHADOWING_HISTORY_MAX_CLOUD_POINTS_PER_BUCKET,
    )
    verdict_cloud = sorted(
        (
            TradingShadowingVerdictChronicleVerdictPoint(
                verdict_id=chronicle_verdict.id,
                timestamp_milliseconds=_to_epoch_milliseconds(chronicle_verdict.resolved_at),
                pnl_percentage=chronicle_verdict.realized_pnl_percentage,
                pnl_usd=chronicle_verdict.realized_pnl_usd,
                exit_reason=chronicle_verdict.exit_reason,
                order_notional_usd=chronicle_verdict.order_notional_value_usd,
                point_size=_clamp_point_size(chronicle_verdict.order_notional_value_usd),
                is_profitable=chronicle_verdict.is_profitable,
            )
            for chronicle_verdict in cloud_source
        ),
        key=lambda payload: (payload.timestamp_milliseconds, payload.verdict_id),
    )

    return TradingShadowingVerdictChronicleBucket(
        bucket_label=bucket_configuration.label,
        granularity_seconds=bucket_configuration.granularity_seconds,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        metrics=metric_points,
        volumes=volume_points,
        verdict_cloud=verdict_cloud,
    )


def _convert_shadow_verdict_to_chronicle_verdict(
        verdict: TradingShadowingVerdict,
) -> Optional[TradingShadowingVerdictChronicleVerdict]:
    resolved_at = ensure_timezone_aware(verdict.resolved_at)
    if resolved_at is None:
        return None
    if verdict.realized_pnl_percentage is None or verdict.realized_pnl_usd is None:
        return None
    if verdict.is_profitable is None:
        return None
    if verdict.probe is None:
        return None
    return TradingShadowingVerdictChronicleVerdict(
        id=verdict.id,
        resolved_at=resolved_at,
        realized_pnl_percentage=verdict.realized_pnl_percentage,
        realized_pnl_usd=verdict.realized_pnl_usd,
        is_profitable=bool(verdict.is_profitable),
        exit_reason=verdict.exit_reason or "UNRESOLVED",
        order_notional_value_usd=verdict.probe.order_notional_value_usd,
    )


def _shadow_verdict_chronicle_bucket_configurations() -> list[TradingShadowingVerdictChronicleBucketConfiguration]:
    return [
        TradingShadowingVerdictChronicleBucketConfiguration(label="last_30m_1m", lookback=timedelta(minutes=30), granularity_seconds=60),
        TradingShadowingVerdictChronicleBucketConfiguration(label="last_24h_1h", lookback=timedelta(hours=24), granularity_seconds=3600),
        TradingShadowingVerdictChronicleBucketConfiguration(label="last_7d_5m", lookback=timedelta(days=7), granularity_seconds=300),
        TradingShadowingVerdictChronicleBucketConfiguration(label="last_30d_30m", lookback=timedelta(days=30), granularity_seconds=1800),
    ]


def _series_end_datetime(now_local: datetime) -> datetime:
    delay_cutoff = now_local - timedelta(minutes=settings.TRADING_SHADOWING_HISTORY_DELAY_MINUTES)
    lag_cutoff = now_local - timedelta(seconds=settings.TRADING_SHADOWING_HISTORY_SERIES_END_LAG_SECONDS)
    return max(delay_cutoff, lag_cutoff)


def _chronicle_display_lag_timedelta() -> timedelta:
    return timedelta(seconds=settings.TRADING_SHADOWING_HISTORY_SERIES_END_LAG_SECONDS)


def _verdict_fetch_end_datetime(
        series_end_datetime: datetime,
        bucket_configurations: list[TradingShadowingVerdictChronicleBucketConfiguration],
) -> datetime:
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS
    if trailing <= 0 or not bucket_configurations:
        return series_end_datetime
    max_granularity_seconds = max(configuration.granularity_seconds for configuration in bucket_configurations)
    return series_end_datetime + timedelta(seconds=max_granularity_seconds * trailing)


def _convert_verdicts(verdicts: list[TradingShadowingVerdict]) -> list[TradingShadowingVerdictChronicleVerdict]:
    chronicle_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []
    for verdict in verdicts:
        chronicle_verdict = _convert_shadow_verdict_to_chronicle_verdict(verdict)
        if chronicle_verdict is not None:
            chronicle_verdicts.append(chronicle_verdict)
    return chronicle_verdicts


def _trim_verdicts_for_window(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        global_from_datetime: datetime,
        fetch_end_datetime: datetime,
        max_count: int,
) -> list[TradingShadowingVerdictChronicleVerdict]:
    window_from = ensure_timezone_aware(global_from_datetime)
    window_to = ensure_timezone_aware(fetch_end_datetime)
    assert window_from is not None and window_to is not None

    filtered: list[TradingShadowingVerdictChronicleVerdict] = []
    for chronicle_verdict in verdicts:
        resolved_at = ensure_timezone_aware(chronicle_verdict.resolved_at)
        if resolved_at is None:
            continue
        if resolved_at < window_from or resolved_at > window_to:
            continue
        filtered.append(chronicle_verdict)
    filtered.sort(key=lambda chronicle_verdict: chronicle_verdict.resolved_at)
    if len(filtered) <= max_count:
        return filtered
    return filtered[-max_count:]


def _to_epoch_milliseconds(target_datetime: datetime) -> int:
    return int(target_datetime.timestamp() * 1000)


def _floor_datetime_to_granularity(target_datetime: datetime, granularity_seconds: int) -> datetime:
    epoch_seconds = int(target_datetime.timestamp())
    floored_epoch_seconds = (epoch_seconds // granularity_seconds) * granularity_seconds
    return datetime.fromtimestamp(floored_epoch_seconds, tz=target_datetime.tzinfo)


def _compute_profit_factor(gross_profit_usd: float, gross_loss_usd: float) -> float:
    if gross_loss_usd <= 0.0:
        return 999.0 if gross_profit_usd > 0.0 else 0.0
    return gross_profit_usd / gross_loss_usd


def _compute_velocity_per_hour(verdict_count: int, granularity_seconds: int) -> float:
    if granularity_seconds <= 0:
        return 0.0
    return verdict_count * 3600.0 / float(granularity_seconds)


def _sample_cloud_points(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        limit_count: int,
) -> list[TradingShadowingVerdictChronicleVerdict]:
    if len(verdicts) <= limit_count:
        return verdicts

    step = len(verdicts) / float(limit_count)
    return [verdicts[int(index * step)] for index in range(limit_count)]


def _clamp_point_size(order_notional_usd: float) -> float:
    if order_notional_usd <= 0:
        return 3.0
    return max(3.0, min(18.0, (order_notional_usd ** 0.5) / 2.0))
