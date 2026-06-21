from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import to_epoch_milliseconds
from src.core.trading.shadowing.trading_shadowing_regime_gate_timeline import (
    build_regime_gate_timeline_for_metric_timestamps,
)
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingVerdictChronicleVerdict


def _build_chronicle_verdict(
        verdict_id: int,
        resolved_at: datetime,
        realized_pnl_usd: float,
) -> TradingShadowingVerdictChronicleVerdict:
    return TradingShadowingVerdictChronicleVerdict(
        id=verdict_id,
        resolved_at=resolved_at,
        realized_pnl_percentage=1.0,
        realized_pnl_usd=realized_pnl_usd,
        is_profitable=realized_pnl_usd > 0.0,
        exit_reason="TAKE_PROFIT",
        order_notional_value_usd=100.0,
    )


def test_regime_gate_timeline_uses_rolling_lookback_per_metric_timestamp() -> None:
    local_timezone = timezone(timedelta(hours=2))
    as_of_datetime = datetime(2026, 6, 14, 12, 0, 0, tzinfo=local_timezone)
    verdicts: list[TradingShadowingVerdictChronicleVerdict] = [
        _build_chronicle_verdict(
            verdict_id=index,
            resolved_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=local_timezone) + timedelta(hours=index),
            realized_pnl_usd=10.0,
        )
        for index in range(120)
    ]
    early_metric_timestamp_milliseconds = to_epoch_milliseconds(
        datetime(2026, 6, 5, 12, 0, 0, tzinfo=local_timezone)
    )

    regime_gate_points = build_regime_gate_timeline_for_metric_timestamps(
        verdicts=verdicts,
        as_of_datetime=as_of_datetime,
        metric_timestamps_milliseconds=[early_metric_timestamp_milliseconds],
    )

    early_regime_gate_point = regime_gate_points[0]

    assert early_regime_gate_point.regime_sparse_expected_value_usd_sma is not None
    assert early_regime_gate_point.regime_profit_factor_sma is not None
