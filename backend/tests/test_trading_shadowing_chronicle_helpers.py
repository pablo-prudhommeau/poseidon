from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import (
    iter_chronicle_display_bucket_epoch_milliseconds,
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
