from __future__ import annotations

from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingVerdictCycleStatistics


def test_trading_shadowing_verdict_cycle_statistics_merge_aggregates_counters() -> None:
    first_batch = TradingShadowingVerdictCycleStatistics(
        pending_verdict_count=100,
        resolved_verdict_count=12,
        resolved_honeypot_count=2,
        deferred_onchain_price_unavailable_count=3,
    )
    second_batch = TradingShadowingVerdictCycleStatistics(
        pending_verdict_count=50,
        resolved_verdict_count=4,
        resolved_lethargic_count=1,
        deferred_transient_slippage_count=5,
    )

    cycle_statistics = TradingShadowingVerdictCycleStatistics()
    cycle_statistics.merge(first_batch)
    cycle_statistics.merge(second_batch)

    assert cycle_statistics.pending_verdict_count == 150
    assert cycle_statistics.resolved_verdict_count == 16
    assert cycle_statistics.resolved_honeypot_count == 2
    assert cycle_statistics.resolved_lethargic_count == 1
    assert cycle_statistics.deferred_onchain_price_unavailable_count == 3
    assert cycle_statistics.deferred_transient_slippage_count == 5


def test_trading_shadowing_verdict_cycle_statistics_format_non_zero_breakdown() -> None:
    cycle_statistics = TradingShadowingVerdictCycleStatistics(
        resolved_honeypot_count=2,
        deferred_onchain_price_unavailable_count=3,
    )

    breakdown = cycle_statistics.format_non_zero_breakdown()

    assert "honeypot=2" in breakdown
    assert "deferred_onchain=3" in breakdown
    assert "lethargic=" not in breakdown


def test_trading_shadowing_verdict_cycle_statistics_format_empty_breakdown() -> None:
    cycle_statistics = TradingShadowingVerdictCycleStatistics()

    assert cycle_statistics.format_non_zero_breakdown() == "no breakdown counters"
