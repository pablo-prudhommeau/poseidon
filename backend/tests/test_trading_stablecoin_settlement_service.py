from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service import (
    poll_deployable_stablecoin_until_swap_settled,
)
from src.core.trading.portfolio.trading_portfolio_structures import StablecoinSwapSettlementDirection


@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.time.sleep")
@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.resolve_total_deployable_stablecoin_cash_usd")
def test_poll_deployable_stablecoin_detects_sell_credit(
        resolve_deployable_mock: MagicMock,
        sleep_mock: MagicMock,
) -> None:
    resolve_deployable_mock.side_effect = [20.0, 20.0, 20.5]

    poll_result = poll_deployable_stablecoin_until_swap_settled(
        deployable_cash_before_swap_usd=20.0,
        settlement_direction=StablecoinSwapSettlementDirection.SELL_CREDIT,
        transaction_signature="confirmed-sell-signature",
    )

    assert poll_result.swap_settled_on_chain is True
    assert poll_result.deployable_cash_usd == 20.5


@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.time.sleep")
@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.resolve_total_deployable_stablecoin_cash_usd")
def test_poll_deployable_stablecoin_detects_buy_debit(
        resolve_deployable_mock: MagicMock,
        sleep_mock: MagicMock,
) -> None:
    resolve_deployable_mock.side_effect = [20.0, 19.5]

    poll_result = poll_deployable_stablecoin_until_swap_settled(
        deployable_cash_before_swap_usd=20.0,
        settlement_direction=StablecoinSwapSettlementDirection.BUY_DEBIT,
        transaction_signature="confirmed-buy-signature",
    )

    assert poll_result.swap_settled_on_chain is True
    assert poll_result.deployable_cash_usd == 19.5


@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.STABLECOIN_DEPLOYABLE_POLL_TIMEOUT_SECONDS", 0.0)
@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.time.sleep")
@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.resolve_total_deployable_stablecoin_cash_usd")
def test_poll_deployable_stablecoin_times_out_when_deployable_unchanged(
        resolve_deployable_mock: MagicMock,
        sleep_mock: MagicMock,
) -> None:
    resolve_deployable_mock.return_value = 20.0

    poll_result = poll_deployable_stablecoin_until_swap_settled(
        deployable_cash_before_swap_usd=20.0,
        settlement_direction=StablecoinSwapSettlementDirection.SELL_CREDIT,
        transaction_signature="confirmed-sell-signature",
    )

    assert poll_result.swap_settled_on_chain is False
    assert poll_result.deployable_cash_usd == 20.0
    sleep_mock.assert_not_called()


@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.invalidate_solana_onchain_wallet_context_cache")
@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.time.sleep")
@patch("src.core.trading.portfolio.trading_portfolio_stablecoin_settlement_service.resolve_total_deployable_stablecoin_cash_usd")
def test_poll_deployable_stablecoin_force_refreshes_deployable_balance_each_attempt(
        resolve_deployable_mock: MagicMock,
        sleep_mock: MagicMock,
        invalidate_cache_mock: MagicMock,
) -> None:
    resolve_deployable_mock.side_effect = [20.0, 19.5]

    poll_deployable_stablecoin_until_swap_settled(
        deployable_cash_before_swap_usd=20.0,
        settlement_direction=StablecoinSwapSettlementDirection.BUY_DEBIT,
        transaction_signature="confirmed-buy-signature",
    )

    invalidate_cache_mock.assert_called_once()
    assert all(call.kwargs.get("force_refresh") is True for call in resolve_deployable_mock.call_args_list)
