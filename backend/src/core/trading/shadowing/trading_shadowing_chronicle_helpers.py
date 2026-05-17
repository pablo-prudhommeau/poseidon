from __future__ import annotations

import math
from datetime import datetime, timedelta

from src.configuration.config import settings


def series_end_datetime(now_local: datetime) -> datetime:
    delay_cutoff = now_local - timedelta(minutes=settings.TRADING_SHADOWING_HISTORY_DELAY_MINUTES)
    lag_cutoff = now_local - timedelta(seconds=settings.TRADING_SHADOWING_HISTORY_SERIES_END_LAG_SECONDS)
    return max(delay_cutoff, lag_cutoff)


def chronicle_display_lag_timedelta() -> timedelta:
    return timedelta(seconds=settings.TRADING_SHADOWING_HISTORY_SERIES_END_LAG_SECONDS)


def to_epoch_milliseconds(target_datetime: datetime) -> int:
    return int(target_datetime.timestamp() * 1000)


def floor_datetime_to_granularity(target_datetime: datetime, granularity_seconds: int) -> datetime:
    epoch_seconds = int(target_datetime.timestamp())
    floored_epoch_seconds = (epoch_seconds // granularity_seconds) * granularity_seconds
    return datetime.fromtimestamp(floored_epoch_seconds, tz=target_datetime.tzinfo)


def compute_profit_factor(gross_profit_usd: float, gross_loss_usd: float) -> float:
    if gross_loss_usd <= 0.0:
        return 999.0 if gross_profit_usd > 0.0 else 0.0
    return gross_profit_usd / gross_loss_usd


def winsorize_series_like_shadow_verdict_chronicle_chart(values: list[float]) -> list[float]:
    if len(values) < 4:
        return list(values)
    sorted_values = sorted(values)
    lower_index = max(0, math.floor((len(sorted_values) - 1) * 0.02))
    upper_index = min(len(sorted_values) - 1, math.ceil((len(sorted_values) - 1) * 0.98))
    lower_bound = sorted_values[lower_index]
    upper_bound = sorted_values[upper_index]
    return [min(upper_bound, max(lower_bound, value)) for value in values]


def simple_moving_average_like_shadow_verdict_chronicle_chart(values: list[float], window_size: int) -> list[float]:
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
