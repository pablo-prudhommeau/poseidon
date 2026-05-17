from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import (
    chronicle_display_lag_timedelta,
    compute_profit_factor,
    floor_datetime_to_granularity,
    series_end_datetime,
    simple_moving_average_like_shadow_verdict_chronicle_chart,
    to_epoch_milliseconds,
    winsorize_series_like_shadow_verdict_chronicle_chart,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingVerdictChronicleRegimeGatePoint,
    TradingShadowingVerdictChronicleVerdict,
)
from src.core.utils.date_utils import ensure_timezone_aware


def build_regime_gate_timeline_for_metric_timestamps(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        series_end_datetime: datetime,
        metric_timestamps_milliseconds: list[int],
) -> list[TradingShadowingVerdictChronicleRegimeGatePoint]:
    if not metric_timestamps_milliseconds:
        return []

    current_time = ensure_timezone_aware(series_end_datetime)
    assert current_time is not None

    pf_timeline = _build_regime_sma_timeline(
        verdicts=verdicts,
        current_time=current_time,
        lookback=timedelta(days=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_LOOKBACK_DAYS),
        granularity_seconds=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_BUCKET_WIDTH_SECONDS,
        sma_period=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_PERIOD,
        value_selector="profit_factor",
        empty_fallback=1.0,
    )
    ev_timeline = _build_regime_sma_timeline(
        verdicts=verdicts,
        current_time=current_time,
        lookback=timedelta(days=settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_LOOKBACK_DAYS),
        granularity_seconds=settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_BUCKET_WIDTH_SECONDS,
        sma_period=settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_PERIOD,
        value_selector="mean_pnl_usd",
        empty_fallback=0.0,
    )

    pf_threshold = settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_THRESHOLD
    ev_threshold = settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_USD_THRESHOLD
    series_end_milliseconds = to_epoch_milliseconds(current_time)

    regime_gate_points: list[TradingShadowingVerdictChronicleRegimeGatePoint] = []
    for metric_timestamp_milliseconds in metric_timestamps_milliseconds:
        sample_timestamp_milliseconds = min(metric_timestamp_milliseconds, series_end_milliseconds)
        regime_profit_factor_sma = _sample_regime_sma_at_timestamp(pf_timeline, sample_timestamp_milliseconds)
        regime_sparse_expected_value_usd_sma = _sample_regime_sma_at_timestamp(ev_timeline, sample_timestamp_milliseconds)
        profit_factor_gate_open = (
                regime_profit_factor_sma is not None
                and regime_profit_factor_sma >= pf_threshold
        )
        sparse_expected_value_gate_open = (
                regime_sparse_expected_value_usd_sma is not None
                and regime_sparse_expected_value_usd_sma >= ev_threshold
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


def _build_regime_sma_timeline(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        current_time: datetime,
        lookback: timedelta,
        granularity_seconds: int,
        sma_period: int,
        value_selector: str,
        empty_fallback: float,
) -> list[tuple[int, float]]:
    timestamped_sparse_values = _build_timestamped_sparse_bucket_values(
        verdicts=verdicts,
        current_time=current_time,
        lookback=lookback,
        granularity_seconds=granularity_seconds,
        value_selector=value_selector,
    )
    if not timestamped_sparse_values:
        return []

    sparse_values = [value for _, value in timestamped_sparse_values]
    sparse_timestamps = [timestamp for timestamp, _ in timestamped_sparse_values]
    winsorized_values = winsorize_series_like_shadow_verdict_chronicle_chart(sparse_values)
    sma_values = simple_moving_average_like_shadow_verdict_chronicle_chart(winsorized_values, sma_period)
    if not sma_values:
        return []

    return list(zip(sparse_timestamps, sma_values))


def _build_timestamped_sparse_bucket_values(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        current_time: datetime,
        lookback: timedelta,
        granularity_seconds: int,
        value_selector: str,
) -> list[tuple[int, float]]:
    chronicle_lag_td = chronicle_display_lag_timedelta()
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS

    series_end = series_end_datetime(current_time)
    global_from_datetime = series_end - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)
    bucket_from_datetime = max(global_from_datetime, series_end - lookback - chronicle_lag_td)
    bucket_to_datetime = series_end + timedelta(seconds=granularity_seconds * max(0, trailing))

    grouped_verdicts: defaultdict = defaultdict(list)
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
        pnl_usd_values = [item.realized_pnl_usd for item in items if item.realized_pnl_usd is not None]
        if not pnl_usd_values:
            continue
        if value_selector == "profit_factor":
            gross_profit_usd = sum(value for value in pnl_usd_values if value > 0.0)
            gross_loss_usd = abs(sum(value for value in pnl_usd_values if value < 0.0))
            sparse_value = compute_profit_factor(gross_profit_usd, gross_loss_usd)
        else:
            sparse_value = sum(pnl_usd_values) / float(len(pnl_usd_values))
        timestamped_values.append((to_epoch_milliseconds(bucket_timestamp), sparse_value))

    return timestamped_values


def _sample_regime_sma_at_timestamp(
        regime_timeline: list[tuple[int, float]],
        sample_timestamp_milliseconds: int,
) -> Optional[float]:
    if not regime_timeline:
        return None
    timeline_timestamps = [timestamp for timestamp, _ in regime_timeline]
    insertion_index = bisect.bisect_right(timeline_timestamps, sample_timestamp_milliseconds) - 1
    if insertion_index < 0:
        return None
    return regime_timeline[insertion_index][1]
