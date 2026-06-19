from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.trading.execution.solana.trading_execution_solana_service import (
    build_solana_sell_route_with_smallest_unit_amount,
    resolve_sell_amount_in_lamports_for_close,
    resolve_wallet_token_balance_raw_for_mint,
)


@patch("src.core.trading.execution.solana.trading_execution_solana_service.resolve_solana_wallet_snapshot")
def test_resolve_wallet_token_balance_raw_for_mint_sums_all_accounts(
        resolve_wallet_snapshot_mock: MagicMock,
) -> None:
    resolve_wallet_snapshot_mock.return_value = MagicMock(
        token_accounts=[
            MagicMock(token_mint_address="token-mint", balance_raw=482_691_805_046),
            MagicMock(token_mint_address="token-mint", balance_raw=1),
            MagicMock(token_mint_address="other-mint", balance_raw=999),
        ],
    )

    total_balance_raw = resolve_wallet_token_balance_raw_for_mint("token-mint")

    assert total_balance_raw == 482_691_805_047


@patch("src.core.trading.execution.solana.trading_execution_solana_service.resolve_wallet_token_balance_raw_for_mint")
def test_resolve_sell_amount_in_lamports_for_close_uses_exact_wallet_balance_on_full_close(
        resolve_wallet_balance_raw_mock: MagicMock,
) -> None:
    resolve_wallet_balance_raw_mock.return_value = 482_691_805_047

    amount_in_lamports = resolve_sell_amount_in_lamports_for_close(
        token_mint_address="token-mint",
        sell_quantity_human=689.303435,
        token_decimals=6,
        is_full_close=True,
    )

    assert amount_in_lamports == 482_691_805_047


@patch("src.core.trading.execution.solana.trading_execution_solana_service.generate_jupiter_swap_transaction")
@patch("src.core.trading.execution.solana.trading_execution_solana_service.build_default_solana_signer")
@patch("src.core.trading.execution.solana.trading_execution_solana_service.resolve_stablecoin_address_for_blockchain")
def test_build_solana_sell_route_with_smallest_unit_amount_uses_explicit_amount(
        resolve_stablecoin_mock: MagicMock,
        build_signer_mock: MagicMock,
        generate_swap_mock: MagicMock,
) -> None:
    resolve_stablecoin_mock.return_value = "stablecoin-mint"
    build_signer_mock.return_value = MagicMock(address="wallet-address")
    generate_swap_mock.return_value = "base64-transaction"

    build_solana_sell_route_with_smallest_unit_amount(
        token_mint="token-mint",
        token_amount_in_smallest_unit=482_691_805_047,
    )

    generate_swap_mock.assert_called_once()
    assert generate_swap_mock.call_args.kwargs["amount_in_lamports"] == 482_691_805_047
