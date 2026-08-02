from __future__ import annotations

from unittest.mock import patch

import pytest

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.solana.dex_parsers.meteora_dlmm_pool_parser import (
    METEORA_DLMM_LB_PAIR_DISCRIMINATOR,
    METEORA_DLMM_PROGRAM_ID,
    MeteoraDlmmPoolParser,
)
from src.integrations.blockchain.solana.dex_parsers.solana_dex_pool_price_utils import (
    resolve_spl_token_decimals_pair_or_none,
)
from src.integrations.blockchain.solana.solana_structures import SolanaRpcFailureReason


def _build_lb_pair_account_data() -> bytes:
    account_data = bytearray(152)
    account_data[:8] = METEORA_DLMM_LB_PAIR_DISCRIMINATOR
    return bytes(account_data)


def test_meteora_parser_rejects_wrong_owner_program_without_decimals_lookup() -> None:
    parser = MeteoraDlmmPoolParser()
    with patch(
            "src.integrations.blockchain.solana.dex_parsers.meteora_dlmm_pool_parser.resolve_spl_token_decimals_pair_or_none",
    ) as resolve_decimals_mock:
        parsed_price = parser.parse_pool_price(
            rpc_url="https://example.invalid",
            account_data=_build_lb_pair_account_data(),
            target_token_address="target-mint",
            owner_program="OtherProgram1111111111111111111111111111111",
        )

    assert parsed_price is None
    resolve_decimals_mock.assert_not_called()


def test_meteora_parser_rejects_non_lb_pair_discriminator_without_decimals_lookup() -> None:
    parser = MeteoraDlmmPoolParser()
    account_data = bytearray(152)
    account_data[:8] = b"\x00\x01\x02\x03\x04\x05\x06\x07"

    with patch(
            "src.integrations.blockchain.solana.dex_parsers.meteora_dlmm_pool_parser.resolve_spl_token_decimals_pair_or_none",
    ) as resolve_decimals_mock:
        parsed_price = parser.parse_pool_price(
            rpc_url="https://example.invalid",
            account_data=bytes(account_data),
            target_token_address="target-mint",
            owner_program=METEORA_DLMM_PROGRAM_ID,
        )

    assert parsed_price is None
    resolve_decimals_mock.assert_not_called()


def test_resolve_spl_token_decimals_pair_or_none_soft_fails_on_missing_account() -> None:
    missing_account_error = BlockchainRpcUnavailableError(
        "mint missing",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="getAccountInfo",
        failure_reason=SolanaRpcFailureReason.MISSING_ACCOUNT,
        rpc_url="https://example.invalid",
    )

    with patch(
            "src.integrations.blockchain.solana.solana_rpc_client.get_spl_token_decimals",
            side_effect=missing_account_error,
    ):
        mint_decimals = resolve_spl_token_decimals_pair_or_none(
            rpc_url="https://example.invalid",
            mint_address_a="mint-a",
            mint_address_b="mint-b",
        )

    assert mint_decimals is None


def test_resolve_spl_token_decimals_pair_or_none_reraises_transient_rpc_failure() -> None:
    rate_limited_error = BlockchainRpcUnavailableError(
        "rate limited",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="getAccountInfo",
        failure_reason=SolanaRpcFailureReason.RATE_LIMITED,
        rpc_url="https://example.invalid",
    )

    with patch(
            "src.integrations.blockchain.solana.solana_rpc_client.get_spl_token_decimals",
            side_effect=rate_limited_error,
    ):
        with pytest.raises(BlockchainRpcUnavailableError) as raised_error:
            resolve_spl_token_decimals_pair_or_none(
                rpc_url="https://example.invalid",
                mint_address_a="mint-a",
                mint_address_b="mint-b",
            )

    assert raised_error.value.failure_reason == SolanaRpcFailureReason.RATE_LIMITED
