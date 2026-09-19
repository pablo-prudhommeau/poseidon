from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import TypeVar

CHRONICLE_ALL_BUCKET_LABEL: str = "all"
CHRONICLE_ALL_TARGET_BUCKET_COUNT: int = 1200
CHRONICLE_ALL_GRANULARITY_CANDIDATE_SECONDS: tuple[int, ...] = (3600, 7200, 14400, 21600, 43200, 86400)
CHRONICLE_MAX_METRIC_POINTS: int = 500
CHRONICLE_MAX_VOLUME_POINTS: int = 900
CHRONICLE_MAX_SELL_CLOUD_POINTS: int = 2000
CHRONICLE_ALL_VERDICT_SCAN_BATCH_SIZE: int = 5000

SampledItem = TypeVar("SampledItem")


def to_epoch_milliseconds(target_datetime: datetime) -> int:
    return int(target_datetime.timestamp() * 1000)


def floor_datetime_to_granularity(target_datetime: datetime, granularity_seconds: int) -> datetime:
    epoch_seconds = int(target_datetime.timestamp())
    floored_epoch_seconds = (epoch_seconds // granularity_seconds) * granularity_seconds
    return datetime.fromtimestamp(floored_epoch_seconds, tz=target_datetime.tzinfo)


def iter_chronicle_display_bucket_epoch_milliseconds(
        from_datetime: datetime,
        as_of_datetime: datetime,
        granularity_seconds: int,
) -> list[int]:
    bucket_start = floor_datetime_to_granularity(from_datetime, max(1, granularity_seconds))
    display_end = floor_datetime_to_granularity(as_of_datetime, max(1, granularity_seconds))
    step = timedelta(seconds=max(1, granularity_seconds))

    timestamps: list[int] = []
    cursor = bucket_start
    while cursor <= display_end:
        timestamps.append(to_epoch_milliseconds(cursor))
        cursor += step
    return timestamps


def compute_profit_factor(gross_profit_usd: float, gross_loss_usd: float) -> float:
    if gross_loss_usd <= 0.0:
        return 999.0 if gross_profit_usd > 0.0 else 0.0
    return gross_profit_usd / gross_loss_usd


def winsorize_series_like_trading_shadowing_verdict_chronicle_chart(values: list[float]) -> list[float]:
    if len(values) < 4:
        return list(values)
    sorted_values = sorted(values)
    lower_index = max(0, math.floor((len(sorted_values) - 1) * 0.02))
    upper_index = min(len(sorted_values) - 1, math.ceil((len(sorted_values) - 1) * 0.98))
    lower_bound = sorted_values[lower_index]
    upper_bound = sorted_values[upper_index]
    return [min(upper_bound, max(lower_bound, value)) for value in values]


def simple_moving_average_like_trading_shadowing_verdict_chronicle_chart(values: list[float], window_size: int) -> list[float]:
    if len(values) == 0 or window_size <= 1:
        return list(values)
    effective_window = min(window_size, len(values))
    result: list[float] = [0.0] * len(values)
    running_sum = 0.0
    for index in range(len(values)):
        running_sum += values[index]
        if index >= effective_window:
            running_sum -= values[index - effective_window]
        current_window = min(index + 1, effective_window)
        result[index] = running_sum / current_window
    return result


def resolve_all_chronicle_granularity_seconds(span_seconds: float) -> int:
    if span_seconds <= 0:
        return CHRONICLE_ALL_GRANULARITY_CANDIDATE_SECONDS[0]
    raw_granularity_seconds = span_seconds / float(CHRONICLE_ALL_TARGET_BUCKET_COUNT)
    for candidate_seconds in CHRONICLE_ALL_GRANULARITY_CANDIDATE_SECONDS:
        if raw_granularity_seconds <= candidate_seconds:
            return candidate_seconds
    return CHRONICLE_ALL_GRANULARITY_CANDIDATE_SECONDS[-1]


def format_chronicle_granularity_label(granularity_seconds: int) -> str:
    if granularity_seconds >= 86400 and granularity_seconds % 86400 == 0:
        day_count = granularity_seconds // 86400
        return f"{day_count}d"
    if granularity_seconds >= 3600 and granularity_seconds % 3600 == 0:
        hour_count = granularity_seconds // 3600
        return f"{hour_count}h"
    if granularity_seconds >= 60 and granularity_seconds % 60 == 0:
        minute_count = granularity_seconds // 60
        return f"{minute_count}m"
    return f"{granularity_seconds}s"


def downsample_series_indices(length: int, max_points: int) -> list[int]:
    if length <= 0:
        return []
    if length <= max_points:
        return list(range(length))
    stride = max(1, math.ceil(length / max_points))
    indices: list[int] = list(range(0, length, stride))
    last_index = length - 1
    if indices[-1] != last_index:
        indices.append(last_index)
    return indices


def sample_evenly_spaced_items(items: list[SampledItem], limit_count: int) -> list[SampledItem]:
    if limit_count <= 0:
        return []
    if len(items) <= limit_count:
        return list(items)
    step = len(items) / float(limit_count)
    return [items[int(index * step)] for index in range(limit_count)]
