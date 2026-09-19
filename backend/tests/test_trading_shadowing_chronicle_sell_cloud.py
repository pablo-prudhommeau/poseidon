from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import CHRONICLE_MAX_SELL_CLOUD_POINTS
from src.core.trading.shadowing.trading_shadowing_service import (
    _breakeven_arm_by_evaluation_id,
    _convert_closed_sells_to_chronicle_points,
    _earliest_opened_at_by_evaluation_id,
    _sell_cloud_for_window,
)
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingVerdictChronicleSellPoint


def _sell_point(
        trade_id: int,
        occurred_at: datetime,
        is_profitable: bool,
        opened_at: datetime | None = None,
) -> TradingShadowingVerdictChronicleSellPoint:
    opened_at_datetime = opened_at if opened_at is not None else occurred_at - timedelta(hours=2)
    return TradingShadowingVerdictChronicleSellPoint(
        trade_id=trade_id,
        timestamp_milliseconds=int(occurred_at.timestamp() * 1000),
        opened_at_milliseconds=int(opened_at_datetime.timestamp() * 1000),
        pnl_percentage=12.0 if is_profitable else -8.0,
        pnl_usd=60.0 if is_profitable else -40.0,
        is_profitable=is_profitable,
        token_symbol="PEPE",
        execution_status="PAPER",
        blockchain_network="solana",
        token_address="So11111111111111111111111111111111111111112",
    )


def _fake_trade(trade_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=trade_id,
        token_symbol="PEPE",
        execution_status=SimpleNamespace(value="PAPER"),
        blockchain_network="solana",
        token_address="So11111111111111111111111111111111111111112",
    )


def _fake_outcome(
        trade_id: int,
        evaluation_id: int,
        occurred_at: datetime,
        is_profitable: bool,
        holding_duration_minutes: float = 120.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        evaluation_id=evaluation_id,
        trade=_fake_trade(trade_id),
        occurred_at=occurred_at,
        holding_duration_minutes=holding_duration_minutes,
        realized_profit_and_loss_percentage=12.0 if is_profitable else -8.0,
        realized_profit_and_loss_usd=60.0 if is_profitable else -40.0,
        is_profitable=is_profitable,
    )


def test_sell_cloud_for_window_keeps_only_sells_inside_the_bucket() -> None:
    timezone_info = timezone(timedelta(hours=2))
    window_from = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone_info)
    window_to = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone_info)
    as_of = datetime(2026, 9, 14, 11, 30, 0, tzinfo=timezone_info)
    sell_points = [
        _sell_point(1, datetime(2026, 9, 14, 9, 59, 0, tzinfo=timezone_info), True),
        _sell_point(2, datetime(2026, 9, 14, 10, 15, 0, tzinfo=timezone_info), True),
        _sell_point(3, datetime(2026, 9, 14, 11, 0, 0, tzinfo=timezone_info), False),
        _sell_point(4, datetime(2026, 9, 14, 11, 45, 0, tzinfo=timezone_info), True),
        _sell_point(5, datetime(2026, 9, 14, 12, 1, 0, tzinfo=timezone_info), False),
    ]

    filtered_sell_points = _sell_cloud_for_window(
        sell_points=sell_points,
        from_datetime=window_from,
        to_datetime=window_to,
        as_of_datetime=as_of,
    )

    assert [sell_point.trade_id for sell_point in filtered_sell_points] == [2, 3]
    assert filtered_sell_points[0].is_profitable is True
    assert filtered_sell_points[1].is_profitable is False


def test_sell_cloud_for_window_keeps_opened_at_before_the_bucket() -> None:
    timezone_info = timezone(timedelta(hours=2))
    window_from = datetime(2026, 9, 14, 10, 0, 0, tzinfo=timezone_info)
    window_to = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone_info)
    as_of = datetime(2026, 9, 14, 11, 30, 0, tzinfo=timezone_info)
    opened_at = datetime(2026, 9, 13, 18, 0, 0, tzinfo=timezone_info)
    closed_at = datetime(2026, 9, 14, 10, 45, 0, tzinfo=timezone_info)

    filtered_sell_points = _sell_cloud_for_window(
        sell_points=[_sell_point(9, closed_at, True, opened_at)],
        from_datetime=window_from,
        to_datetime=window_to,
        as_of_datetime=as_of,
    )

    assert len(filtered_sell_points) == 1
    assert filtered_sell_points[0].trade_id == 9
    assert filtered_sell_points[0].opened_at_milliseconds == int(opened_at.timestamp() * 1000)
    assert filtered_sell_points[0].timestamp_milliseconds == int(closed_at.timestamp() * 1000)
    assert filtered_sell_points[0].opened_at_milliseconds < int(window_from.timestamp() * 1000)


def test_sell_cloud_for_window_samples_when_above_cap() -> None:
    timezone_info = timezone(timedelta(hours=2))
    window_from = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone_info)
    window_to = datetime(2026, 9, 14, 0, 0, 0, tzinfo=timezone_info)
    as_of = window_to
    sell_points = [
        _sell_point(
            trade_id=index,
            occurred_at=window_from + timedelta(minutes=index),
            is_profitable=index % 2 == 0,
        )
        for index in range(CHRONICLE_MAX_SELL_CLOUD_POINTS + 250)
    ]

    filtered_sell_points = _sell_cloud_for_window(
        sell_points=sell_points,
        from_datetime=window_from,
        to_datetime=window_to,
        as_of_datetime=as_of,
    )

    assert len(filtered_sell_points) == CHRONICLE_MAX_SELL_CLOUD_POINTS
    assert filtered_sell_points[0].trade_id == 0


def test_earliest_opened_at_by_evaluation_id_keeps_minimum() -> None:
    timezone_info = timezone(timedelta(hours=2))
    earlier = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone_info)
    later = datetime(2026, 9, 13, 18, 0, 0, tzinfo=timezone_info)
    opened_at_by_evaluation_id = _earliest_opened_at_by_evaluation_id(
        [
            SimpleNamespace(evaluation_id=7, opened_at=later),
            SimpleNamespace(evaluation_id=7, opened_at=earlier),
            SimpleNamespace(evaluation_id=8, opened_at=later),
        ]
    )

    assert opened_at_by_evaluation_id[7] == earlier
    assert opened_at_by_evaluation_id[8] == later


def test_convert_closed_sells_joins_opened_at() -> None:
    timezone_info = timezone(timedelta(hours=2))
    opened_at = datetime(2026, 9, 13, 18, 0, 0, tzinfo=timezone_info)
    closed_at = datetime(2026, 9, 14, 10, 15, 0, tzinfo=timezone_info)
    outcome = _fake_outcome(trade_id=2, evaluation_id=40, occurred_at=closed_at, is_profitable=True)

    sell_points = _convert_closed_sells_to_chronicle_points(
        outcomes=[outcome],
        opened_at_by_evaluation_id={40: opened_at},
        breakeven_arm_by_evaluation_id={},
    )

    assert len(sell_points) == 1
    assert sell_points[0].trade_id == 2
    assert sell_points[0].opened_at_milliseconds == int(opened_at.timestamp() * 1000)
    assert sell_points[0].timestamp_milliseconds == int(closed_at.timestamp() * 1000)
    assert sell_points[0].blockchain_network == "solana"
    assert sell_points[0].token_address == "So11111111111111111111111111111111111111112"
    assert sell_points[0].breakeven_stop_armed_at_milliseconds is None
    assert sell_points[0].breakeven_arm_pnl_percentage is None


def test_convert_closed_sells_falls_back_to_holding_duration_when_position_is_missing() -> None:
    timezone_info = timezone(timedelta(hours=2))
    closed_at = datetime(2026, 9, 14, 10, 15, 0, tzinfo=timezone_info)
    outcome = _fake_outcome(
        trade_id=2,
        evaluation_id=40,
        occurred_at=closed_at,
        is_profitable=True,
        holding_duration_minutes=90.0,
    )

    sell_points = _convert_closed_sells_to_chronicle_points(
        outcomes=[outcome],
        opened_at_by_evaluation_id={},
        breakeven_arm_by_evaluation_id={},
    )

    assert len(sell_points) == 1
    expected_opened_at = closed_at - timedelta(minutes=90.0)
    assert sell_points[0].opened_at_milliseconds == int(expected_opened_at.timestamp() * 1000)


def test_convert_closed_sells_omits_when_opened_at_cannot_be_resolved() -> None:
    timezone_info = timezone(timedelta(hours=2))
    closed_at = datetime(2026, 9, 14, 10, 15, 0, tzinfo=timezone_info)
    outcome = _fake_outcome(
        trade_id=2,
        evaluation_id=40,
        occurred_at=closed_at,
        is_profitable=True,
        holding_duration_minutes=0.0,
    )

    sell_points = _convert_closed_sells_to_chronicle_points(
        outcomes=[outcome],
        opened_at_by_evaluation_id={},
        breakeven_arm_by_evaluation_id={},
    )

    assert sell_points == []


def test_convert_closed_sells_omits_when_opened_at_is_not_before_close() -> None:
    timezone_info = timezone(timedelta(hours=2))
    closed_at = datetime(2026, 9, 14, 10, 15, 0, tzinfo=timezone_info)
    outcome = _fake_outcome(trade_id=2, evaluation_id=40, occurred_at=closed_at, is_profitable=True)

    sell_points = _convert_closed_sells_to_chronicle_points(
        outcomes=[outcome],
        opened_at_by_evaluation_id={40: closed_at},
        breakeven_arm_by_evaluation_id={},
    )

    assert sell_points == []


def test_breakeven_arm_by_evaluation_id_keeps_earliest_armed_at() -> None:
    timezone_info = timezone(timedelta(hours=2))
    earlier = datetime(2026, 9, 13, 19, 0, 0, tzinfo=timezone_info)
    later = datetime(2026, 9, 13, 20, 0, 0, tzinfo=timezone_info)
    breakeven_arm_by_evaluation_id = _breakeven_arm_by_evaluation_id(
        [
            SimpleNamespace(
                evaluation_id=7,
                breakeven_stop_armed_at=later,
                entry_price=1.0,
                breakeven_arm_price=1.1,
            ),
            SimpleNamespace(
                evaluation_id=7,
                breakeven_stop_armed_at=earlier,
                entry_price=1.0,
                breakeven_arm_price=1.1,
            ),
            SimpleNamespace(
                evaluation_id=8,
                breakeven_stop_armed_at=None,
                entry_price=1.0,
                breakeven_arm_price=1.1,
            ),
        ]
    )

    assert breakeven_arm_by_evaluation_id[7][0] == earlier
    assert breakeven_arm_by_evaluation_id[7][1] == pytest.approx(10.0)
    assert 8 not in breakeven_arm_by_evaluation_id


def test_convert_closed_sells_includes_in_window_breakeven_arm() -> None:
    timezone_info = timezone(timedelta(hours=2))
    opened_at = datetime(2026, 9, 13, 18, 0, 0, tzinfo=timezone_info)
    armed_at = datetime(2026, 9, 13, 20, 0, 0, tzinfo=timezone_info)
    closed_at = datetime(2026, 9, 14, 10, 15, 0, tzinfo=timezone_info)
    outcome = _fake_outcome(trade_id=2, evaluation_id=40, occurred_at=closed_at, is_profitable=False)

    sell_points = _convert_closed_sells_to_chronicle_points(
        outcomes=[outcome],
        opened_at_by_evaluation_id={40: opened_at},
        breakeven_arm_by_evaluation_id={40: (armed_at, 10.0)},
    )

    assert len(sell_points) == 1
    assert sell_points[0].breakeven_stop_armed_at_milliseconds == int(armed_at.timestamp() * 1000)
    assert sell_points[0].breakeven_arm_pnl_percentage == 10.0


def test_convert_closed_sells_drops_breakeven_arm_outside_hold() -> None:
    timezone_info = timezone(timedelta(hours=2))
    opened_at = datetime(2026, 9, 13, 18, 0, 0, tzinfo=timezone_info)
    closed_at = datetime(2026, 9, 14, 10, 15, 0, tzinfo=timezone_info)
    armed_before_open = datetime(2026, 9, 13, 17, 0, 0, tzinfo=timezone_info)
    outcome = _fake_outcome(trade_id=2, evaluation_id=40, occurred_at=closed_at, is_profitable=True)

    sell_points = _convert_closed_sells_to_chronicle_points(
        outcomes=[outcome],
        opened_at_by_evaluation_id={40: opened_at},
        breakeven_arm_by_evaluation_id={40: (armed_before_open, 10.0)},
    )

    assert len(sell_points) == 1
    assert sell_points[0].breakeven_stop_armed_at_milliseconds is None
    assert sell_points[0].breakeven_arm_pnl_percentage is None
