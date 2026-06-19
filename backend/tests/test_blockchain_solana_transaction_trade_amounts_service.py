from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.integrations.blockchain.solana.blockchain_solana_transaction_trade_amounts_service import (
    _build_owner_token_balance_raw_by_mint,
    resolve_solana_executed_trade_amounts_from_transaction,
)


def _build_token_balance_entry(owner: str, mint: str, amount_raw: int) -> SimpleNamespace:
    return SimpleNamespace(
        owner=owner,
        mint=mint,
        ui_token_amount=SimpleNamespace(amount=str(amount_raw)),
    )


def test_build_owner_token_balance_raw_by_mint_sums_matching_accounts() -> None:
    wallet_address = "wallet-address"
    token_balances = [
        _build_token_balance_entry(wallet_address, "token-mint", 1_000_000),
        _build_token_balance_entry(wallet_address, "token-mint", 500_000),
        _build_token_balance_entry("other-wallet", "token-mint", 9_000_000),
    ]

    balance_raw_by_mint = _build_owner_token_balance_raw_by_mint(
        token_balances=token_balances,
        wallet_address=wallet_address,
    )

    assert balance_raw_by_mint["token-mint"] == 1_500_000


@patch("src.integrations.blockchain.solana.blockchain_solana_transaction_trade_amounts_service.build_default_solana_signer")
@patch(
    "src.integrations.blockchain.solana.blockchain_solana_transaction_trade_amounts_service._fetch_confirmed_transaction_token_balances",
)
@patch(
    "src.integrations.blockchain.solana.blockchain_solana_transaction_trade_amounts_service.resolve_stablecoin_address_for_blockchain",
)
def test_resolve_solana_executed_trade_amounts_from_transaction_parses_sell_amounts(
        resolve_stablecoin_address_mock: MagicMock,
        fetch_token_balances_mock: MagicMock,
        build_signer_mock: MagicMock,
) -> None:
    wallet_address = "wallet-address"
    stablecoin_mint = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
    token_mint = "target-token-mint"
    resolve_stablecoin_address_mock.return_value = stablecoin_mint
    build_signer_mock.return_value = SimpleNamespace(address=wallet_address)

    pre_token_balances = [
        _build_token_balance_entry(wallet_address, stablecoin_mint, 0),
        _build_token_balance_entry(wallet_address, token_mint, 482_691_805_047),
    ]
    post_token_balances = [
        _build_token_balance_entry(wallet_address, stablecoin_mint, 10_209_658),
        _build_token_balance_entry(wallet_address, token_mint, 0),
    ]
    fetch_token_balances_mock.return_value = (pre_token_balances, post_token_balances)

    executed_trade_amounts = resolve_solana_executed_trade_amounts_from_transaction(
        transaction_signature="transaction-signature",
        target_token_mint_address=token_mint,
        token_decimals=6,
    )

    assert executed_trade_amounts is not None
    assert executed_trade_amounts.stablecoin_balance_delta_usd == 10.209658
    assert executed_trade_amounts.token_balance_delta_raw == -482_691_805_047
    assert executed_trade_amounts.executed_token_quantity == 482_691.805047
    assert abs(executed_trade_amounts.executed_token_price_usd - (10.209658 / 482_691.805047)) < 1e-12
