from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Literal, Optional

from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import (
    compute_profit_factor,
    floor_datetime_to_granularity,
    simple_moving_average_like_trading_shadowing_verdict_chronicle_chart,
    to_epoch_milliseconds,
    winsorize_series_like_trading_shadowing_verdict_chronicle_chart,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingVerdictChronicleRegimeGatePoint,
    TradingShadowingVerdictChronicleVerdict,
)
from src.core.utils.date_utils import ensure_timezone_aware

SparseBucketValueSelector = Literal["profit_factor", "mean_pnl_usd"]


def build_regime_gate_timeline_for_metric_timestamps(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        as_of_datetime: datetime,
        metric_timestamps_milliseconds: list[int],
) -> list[TradingShadowingVerdictChronicleRegimeGatePoint]:
    if not metric_timestamps_milliseconds:
        return []

    current_time = ensure_timezone_aware(as_of_datetime)
    assert current_time is not None

    series_end_milliseconds = to_epoch_milliseconds(current_time)
    retention_start_milliseconds = to_epoch_milliseconds(
        current_time - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)
    )
    sample_timestamps_milliseconds: list[int] = [
        min(metric_timestamp_milliseconds, series_end_milliseconds)
        for metric_timestamp_milliseconds in metric_timestamps_milliseconds
    ]
    earliest_sample_milliseconds = min(sample_timestamps_milliseconds)
    latest_sample_milliseconds = max(sample_timestamps_milliseconds)

    profit_factor_lookback = timedelta(
        days=settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_LOOKBACK_DAYS
    )
    profit_factor_granularity_seconds = settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_BUCKET_WIDTH_SECONDS
    profit_factor_moving_average_period = (
        settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_PERIOD
    )
    profit_factor_sparse_bucket_values = _build_timestamped_sparse_bucket_values(
        verdicts=verdicts,
        bucket_from_datetime=_bucket_from_datetime_for_sparse_series(
            earliest_sample_milliseconds=earliest_sample_milliseconds,
            lookback=profit_factor_lookback,
            retention_start_milliseconds=retention_start_milliseconds,
        ),
        bucket_to_datetime=_bucket_to_datetime_for_sparse_series(
            latest_sample_milliseconds=latest_sample_milliseconds,
            series_end_milliseconds=series_end_milliseconds,
            granularity_seconds=profit_factor_granularity_seconds,
        ),
        granularity_seconds=profit_factor_granularity_seconds,
        value_selector="profit_factor",
    )

    sparse_expected_value_lookback = timedelta(
        days=settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_LOOKBACK_DAYS
    )
    sparse_expected_value_granularity_seconds = (
        settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_BUCKET_WIDTH_SECONDS
    )
    sparse_expected_value_moving_average_period = (
        settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_PERIOD
    )
    sparse_expected_value_bucket_values = _build_timestamped_sparse_bucket_values(
        verdicts=verdicts,
        bucket_from_datetime=_bucket_from_datetime_for_sparse_series(
            earliest_sample_milliseconds=earliest_sample_milliseconds,
            lookback=sparse_expected_value_lookback,
            retention_start_milliseconds=retention_start_milliseconds,
        ),
        bucket_to_datetime=_bucket_to_datetime_for_sparse_series(
            latest_sample_milliseconds=latest_sample_milliseconds,
            series_end_milliseconds=series_end_milliseconds,
            granularity_seconds=sparse_expected_value_granularity_seconds,
        ),
        granularity_seconds=sparse_expected_value_granularity_seconds,
        value_selector="mean_pnl_usd",
    )

    profit_factor_threshold = settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_THRESHOLD
    sparse_expected_value_threshold = settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_USD_THRESHOLD

    regime_gate_points: list[TradingShadowingVerdictChronicleRegimeGatePoint] = []
    for metric_timestamp_milliseconds, sample_timestamp_milliseconds in zip(
            metric_timestamps_milliseconds,
            sample_timestamps_milliseconds,
            strict=True,
    ):
        regime_profit_factor_sma = _compute_rolling_regime_sma_at_timestamp(
            timestamped_sparse_values=profit_factor_sparse_bucket_values,
            sample_timestamp_milliseconds=sample_timestamp_milliseconds,
            lookback=profit_factor_lookback,
            retention_start_milliseconds=retention_start_milliseconds,
            moving_average_period=profit_factor_moving_average_period,
        )
        regime_sparse_expected_value_usd_sma = _compute_rolling_regime_sma_at_timestamp(
            timestamped_sparse_values=sparse_expected_value_bucket_values,
            sample_timestamp_milliseconds=sample_timestamp_milliseconds,
            lookback=sparse_expected_value_lookback,
            retention_start_milliseconds=retention_start_milliseconds,
            moving_average_period=sparse_expected_value_moving_average_period,
        )
        profit_factor_gate_open = (
                regime_profit_factor_sma is not None
                and regime_profit_factor_sma >= profit_factor_threshold
        )
        sparse_expected_value_gate_open = (
                regime_sparse_expected_value_usd_sma is not None
                and regime_sparse_expected_value_usd_sma >= sparse_expected_value_threshold
        )
        regime_gate_points.append(TradingShadowingVerdictChronicleRegimeGatePoint(
            timestamp_milliseconds=metric_timestamp_milliseconds,
            regime_profit_factor_sma=regime_profit_factor_sma,
            regime_sparse_expected_value_usd_sma=regime_sparse_expected_value_usd_sma,
            profit_factor_gate_open=profit_factor_gate_open,
            sparse_expected_value_gate_open=sparse_expected_value_gate_open,
            hard_gate_open=profit_factor_gate_open and sparse_expected_value_gate_open,
        ))

    return regime_gate_points


def _bucket_from_datetime_for_sparse_series(
        earliest_sample_milliseconds: int,
        lookback: timedelta,
        retention_start_milliseconds: int,
) -> datetime:
    lookback_start_milliseconds = earliest_sample_milliseconds - int(lookback.total_seconds() * 1000)
    bucket_from_milliseconds = max(lookback_start_milliseconds, retention_start_milliseconds)
    bucket_from_datetime = ensure_timezone_aware(datetime.fromtimestamp(bucket_from_milliseconds / 1000.0))
    assert bucket_from_datetime is not None
    return bucket_from_datetime


def _bucket_to_datetime_for_sparse_series(
        latest_sample_milliseconds: int,
        series_end_milliseconds: int,
        granularity_seconds: int,
) -> datetime:
    trailing_bucket_count = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS
    bucket_to_milliseconds = max(latest_sample_milliseconds, series_end_milliseconds) + (
            granularity_seconds * max(0, trailing_bucket_count) * 1000
    )
    bucket_to_datetime = ensure_timezone_aware(datetime.fromtimestamp(bucket_to_milliseconds / 1000.0))
    assert bucket_to_datetime is not None
    return bucket_to_datetime


def _compute_rolling_regime_sma_at_timestamp(
        timestamped_sparse_values: list[tuple[int, float]],
        sample_timestamp_milliseconds: int,
        lookback: timedelta,
        retention_start_milliseconds: int,
        moving_average_period: int,
) -> Optional[float]:
    if not timestamped_sparse_values:
        return None

    lookback_start_milliseconds = sample_timestamp_milliseconds - int(lookback.total_seconds() * 1000)
    window_start_milliseconds = max(lookback_start_milliseconds, retention_start_milliseconds)
    sparse_timestamps = [timestamp for timestamp, _ in timestamped_sparse_values]
    window_end_index = bisect.bisect_right(sparse_timestamps, sample_timestamp_milliseconds)
    window_start_index = bisect.bisect_left(sparse_timestamps, window_start_milliseconds)
    window_values: list[float] = [
        value for _, value in timestamped_sparse_values[window_start_index:window_end_index]
    ]
    if not window_values:
        return None

    winsorized_values = winsorize_series_like_trading_shadowing_verdict_chronicle_chart(window_values)
    moving_average_values = simple_moving_average_like_trading_shadowing_verdict_chronicle_chart(
        winsorized_values,
        moving_average_period,
    )
    if not moving_average_values:
        return None
    return moving_average_values[-1]


def _build_timestamped_sparse_bucket_values(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        bucket_from_datetime: datetime,
        bucket_to_datetime: datetime,
        granularity_seconds: int,
        value_selector: SparseBucketValueSelector,
) -> list[tuple[int, float]]:
    grouped_verdicts: defaultdict[datetime, list[TradingShadowingVerdictChronicleVerdict]] = defaultdict(list)
    for verdict in verdicts:
        verdict_resolved_at = ensure_timezone_aware(verdict.resolved_at)
        if verdict_resolved_at is None:
            continue
        if verdict_resolved_at < bucket_from_datetime or verdict_resolved_at > bucket_to_datetime:
            continue
        if verdict.realized_pnl_usd is None:
            continue
        bucket_start = floor_datetime_to_granularity(verdict_resolved_at, granularity_seconds)
        grouped_verdicts[bucket_start].append(verdict)

    timestamped_values: list[tuple[int, float]] = []
    for bucket_timestamp in sorted(grouped_verdicts.keys()):
        items = grouped_verdicts[bucket_timestamp]
        realized_pnl_usd_values = [
            item.realized_pnl_usd for item in items if item.realized_pnl_usd is not None
        ]
        if not realized_pnl_usd_values:
            continue
        if value_selector == "profit_factor":
            gross_profit_usd = sum(value for value in realized_pnl_usd_values if value > 0.0)
            gross_loss_usd = abs(sum(value for value in realized_pnl_usd_values if value < 0.0))
            sparse_value = compute_profit_factor(gross_profit_usd, gross_loss_usd)
        else:
            sparse_value = sum(realized_pnl_usd_values) / len(realized_pnl_usd_values)
        timestamped_values.append((to_epoch_milliseconds(bucket_timestamp), sparse_value))

    return timestamped_values
