from __future__ import annotations

from src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_guard_service import (
    clear_pending_stablecoin_settlement,
    register_live_sell_stablecoin_settlement_pending,
    should_skip_live_portfolio_for_pending_stablecoin_settlement,
)


def test_pending_stablecoin_settlement_skips_until_deployable_exceeds_baseline() -> None:
    clear_pending_stablecoin_settlement()
    try:
        register_live_sell_stablecoin_settlement_pending(
            confirmed_swap_transaction_signature="confirmed-swap-signature",
            baseline_deployable_cash_usd=20.0,
        )

        assert should_skip_live_portfolio_for_pending_stablecoin_settlement(current_deployable_cash_usd=20.0) is True
        assert should_skip_live_portfolio_for_pending_stablecoin_settlement(current_deployable_cash_usd=20.01) is False
        assert should_skip_live_portfolio_for_pending_stablecoin_settlement(current_deployable_cash_usd=26.0) is False
    finally:
        clear_pending_stablecoin_settlement()


def test_pending_stablecoin_settlement_keeps_skipping_when_deployable_stays_at_baseline() -> None:
    clear_pending_stablecoin_settlement()
    try:
        register_live_sell_stablecoin_settlement_pending(
            confirmed_swap_transaction_signature="confirmed-swap-signature",
            baseline_deployable_cash_usd=10.0,
        )

        assert should_skip_live_portfolio_for_pending_stablecoin_settlement(current_deployable_cash_usd=10.0) is True
        assert should_skip_live_portfolio_for_pending_stablecoin_settlement(current_deployable_cash_usd=9.99) is True
    finally:
        clear_pending_stablecoin_settlement()
