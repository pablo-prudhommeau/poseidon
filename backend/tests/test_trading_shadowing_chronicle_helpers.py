from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import (
    CHRONICLE_MAX_METRIC_POINTS,
    CHRONICLE_MAX_SELL_CLOUD_POINTS,
    downsample_series_indices,
    format_chronicle_granularity_label,
    iter_chronicle_display_bucket_epoch_milliseconds,
    resolve_all_chronicle_granularity_seconds,
    sample_evenly_spaced_items,
    to_epoch_milliseconds,
)


def test_iter_chronicle_display_bucket_epoch_milliseconds_covers_full_30m_window() -> None:
    timezone_info = timezone(timedelta(hours=2))
    window_from = datetime(2026, 6, 6, 0, 0, 0, tzinfo=timezone_info)
    as_of = datetime(2026, 6, 6, 0, 30, 0, tzinfo=timezone_info)

    timestamps = iter_chronicle_display_bucket_epoch_milliseconds(
        from_datetime=window_from,
        as_of_datetime=as_of,
        granularity_seconds=60,
    )

    assert len(timestamps) == 31
    assert timestamps[0] == to_epoch_milliseconds(window_from)
    assert timestamps[-1] == to_epoch_milliseconds(as_of)


def test_iter_chronicle_display_bucket_epoch_milliseconds_floors_partial_bucket() -> None:
    timezone_info = timezone(timedelta(hours=2))
    window_from = datetime(2026, 6, 6, 0, 0, 30, tzinfo=timezone_info)
    as_of = datetime(2026, 6, 6, 0, 30, 45, tzinfo=timezone_info)
    floored_from = datetime(2026, 6, 6, 0, 0, 0, tzinfo=timezone_info)
    floored_as_of = datetime(2026, 6, 6, 0, 30, 0, tzinfo=timezone_info)

    timestamps = iter_chronicle_display_bucket_epoch_milliseconds(
        from_datetime=window_from,
        as_of_datetime=as_of,
        granularity_seconds=60,
    )

    assert timestamps[0] == to_epoch_milliseconds(floored_from)
    assert timestamps[-1] == to_epoch_milliseconds(floored_as_of)


def test_resolve_all_chronicle_granularity_seconds_tracks_target_bucket_count() -> None:
    assert resolve_all_chronicle_granularity_seconds(0.0) == 3600
    forty_three_days_seconds = 43.0 * 86400.0
    assert resolve_all_chronicle_granularity_seconds(forty_three_days_seconds) == 3600
    one_hundred_eighty_days_seconds = 180.0 * 86400.0
    assert resolve_all_chronicle_granularity_seconds(one_hundred_eighty_days_seconds) == 14400
    five_hundred_days_seconds = 500.0 * 86400.0
    assert resolve_all_chronicle_granularity_seconds(five_hundred_days_seconds) == 43200


def test_format_chronicle_granularity_label() -> None:
    assert format_chronicle_granularity_label(3600) == "1h"
    assert format_chronicle_granularity_label(14400) == "4h"
    assert format_chronicle_granularity_label(86400) == "1d"
    assert format_chronicle_granularity_label(1800) == "30m"


def test_sample_evenly_spaced_items_keeps_short_lists_and_caps_long_lists() -> None:
    short_items = [1, 2, 3]
    assert sample_evenly_spaced_items(short_items, 10) == [1, 2, 3]
    long_items = list(range(1000))
    sampled_items = sample_evenly_spaced_items(long_items, 10)
    assert len(sampled_items) == 10
    assert sampled_items[0] == 0
    assert sampled_items[-1] == 900


def test_downsample_series_indices_keeps_last_index() -> None:
    indices = downsample_series_indices(1440, CHRONICLE_MAX_METRIC_POINTS)
    assert indices[0] == 0
    assert indices[-1] == 1439
    assert len(indices) <= CHRONICLE_MAX_METRIC_POINTS + 1
    assert downsample_series_indices(10, 500) == list(range(10))
    assert downsample_series_indices(0, 500) == []
