from src.core.trading.trading_utils import is_buy_notional_executable, resolve_spendable_cash_usd


def test_resolve_spendable_cash_usd_returns_deployable_cash() -> None:
    assert resolve_spendable_cash_usd(available_cash_usd=5.0) == 5.0
    assert resolve_spendable_cash_usd(available_cash_usd=0.0) == 0.0


def test_is_buy_notional_executable_rejects_oversized_or_zero_orders() -> None:
    assert is_buy_notional_executable(order_notional_usd=0.87, available_cash_usd=0.5) is False
    assert is_buy_notional_executable(order_notional_usd=0.0, available_cash_usd=4.0) is False
    assert is_buy_notional_executable(order_notional_usd=0.87, available_cash_usd=1.0) is True
