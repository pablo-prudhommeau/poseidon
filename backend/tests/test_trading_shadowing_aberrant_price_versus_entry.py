from __future__ import annotations

from src.core.trading.shadowing.trading_shadowing_verdict_tracker import (
    is_shadowing_price_aberrant_versus_entry,
    is_take_profit_percentage_aberrant_versus_entry,
)


def test_sane_take_profit_gap_stays_inside_the_entry_band() -> None:
    assert is_take_profit_percentage_aberrant_versus_entry(
        realized_profit_and_loss_percentage=1184.78,
    ) is False
    assert is_shadowing_price_aberrant_versus_entry(
        entry_price_usd=0.00005137,
        current_price_usd=0.000061644,
    ) is False


def test_maximum_tick_spot_is_aberrant_versus_entry() -> None:
    assert is_take_profit_percentage_aberrant_versus_entry(
        realized_profit_and_loss_percentage=1.7823218922000304e48,
    ) is True
    assert is_shadowing_price_aberrant_versus_entry(
        entry_price_usd=0.00005137,
        current_price_usd=9.156e41,
    ) is True


def test_unusable_prices_are_aberrant_versus_entry() -> None:
    assert is_shadowing_price_aberrant_versus_entry(
        entry_price_usd=0.0,
        current_price_usd=1.0,
    ) is True
    assert is_shadowing_price_aberrant_versus_entry(
        entry_price_usd=1.0,
        current_price_usd=0.0,
    ) is True
