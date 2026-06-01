from src.core.trading.trading_utils import is_buy_notional_executable, resolve_spendable_cash_usd


def test_resolve_spendable_cash_usd_respects_buffer() -> None:
    assert resolve_spendable_cash_usd(available_cash_usd=5.0, min_free_cash_usd=2.0) == 3.0
    assert resolve_spendable_cash_usd(available_cash_usd=2.0, min_free_cash_usd=2.0) == 0.0
    assert resolve_spendable_cash_usd(available_cash_usd=1.5, min_free_cash_usd=2.0) == 0.0


def test_is_buy_notional_executable_rejects_oversized_or_zero_orders() -> None:
    assert is_buy_notional_executable(order_notional_usd=0.87, available_cash_usd=4.0, min_free_cash_usd=4.0) is False
    assert is_buy_notional_executable(order_notional_usd=0.0, available_cash_usd=4.0, min_free_cash_usd=0.0) is False
    assert is_buy_notional_executable(order_notional_usd=0.87, available_cash_usd=5.0, min_free_cash_usd=4.0) is True
