from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.structures.structures import BlockchainNetwork, Token
from src.integrations.blockchain.blockchain_exceptions import BlockchainPriceUnavailableError
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens
from src.integrations.blockchain.solana.blockchain_solana_price_reader import (
    read_solana_pool_price_usd,
    read_solana_pool_prices_usd_batch,
)


@patch("src.integrations.blockchain.solana.blockchain_solana_price_reader.get_solana_rpc_url")
def test_read_solana_pool_prices_usd_batch_raises_when_rpc_unavailable(
        get_solana_rpc_url_mock: MagicMock,
) -> None:
    get_solana_rpc_url_mock.side_effect = ConnectionError(
        "[BLOCKCHAIN][RPC][REGISTRY] No reachable RPC endpoint found for chain solana",
    )

    with pytest.raises(BlockchainPriceUnavailableError) as raised_error:
        read_solana_pool_prices_usd_batch([
            ("token-address", "pair-address", "pumpswap"),
        ])

    assert raised_error.value.blockchain_network == BlockchainNetwork.SOLANA


def test_read_solana_pool_price_usd_skips_unsupported_dex_without_rpc() -> None:
    price_usd = read_solana_pool_price_usd(
        pool_address="pair-address",
        target_token_address="token-address",
        dex_id="raydium",
    )

    assert price_usd is None


@patch("src.integrations.blockchain.blockchain_price_service.read_solana_pool_price_usd")
@patch("src.integrations.blockchain.solana.blockchain_solana_price_reader.read_solana_pool_prices_usd_batch")
def test_fetch_onchain_prices_for_tokens_raises_when_solana_unavailable(
        read_solana_batch_mock: MagicMock,
        read_solana_single_mock: MagicMock,
) -> None:
    read_solana_batch_mock.side_effect = BlockchainPriceUnavailableError(
        "no rpc",
        blockchain_network=BlockchainNetwork.SOLANA,
    )
    read_solana_single_mock.side_effect = BlockchainPriceUnavailableError(
        "no rpc",
        blockchain_network=BlockchainNetwork.SOLANA,
    )
    token = Token(
        symbol="TEST",
        chain=BlockchainNetwork.SOLANA,
        token_address="token-address",
        pair_address="pair-address",
        dex_id="raydium",
    )

    with pytest.raises(BlockchainPriceUnavailableError):
        fetch_onchain_prices_for_tokens([token])


@patch("src.integrations.blockchain.blockchain_price_service.read_solana_pool_price_usd")
@patch("src.integrations.blockchain.blockchain_price_service.read_solana_pool_prices_usd_batch")
def test_fetch_onchain_prices_for_tokens_resilient_skips_missing_when_not_required(
        read_solana_batch_mock: MagicMock,
        read_solana_single_mock: MagicMock,
) -> None:
    read_solana_batch_mock.return_value = {"token-address": 1.25}
    token = Token(
        symbol="TEST",
        chain=BlockchainNetwork.SOLANA,
        token_address="token-address",
        pair_address="pair-address",
        dex_id="raydium",
    )
    missing_token = Token(
        symbol="MISSING",
        chain=BlockchainNetwork.SOLANA,
        token_address="missing-token",
        pair_address="missing-pair",
        dex_id="raydium",
    )

    prices = fetch_onchain_prices_for_tokens([token, missing_token], require_all_prices=False)

    assert prices.resolve_price_usd_for_pair_address("pair-address", blockchain_network=BlockchainNetwork.SOLANA) == 1.25
    with pytest.raises(BlockchainPriceUnavailableError):
        prices.resolve_price_usd_for_pair_address("missing-pair", blockchain_network=BlockchainNetwork.SOLANA)
    read_solana_single_mock.assert_not_called()


@patch("src.integrations.blockchain.blockchain_price_service.read_solana_pool_price_usd")
@patch("src.integrations.blockchain.blockchain_price_service.read_solana_pool_prices_usd_batch")
def test_fetch_solana_pool_prices_resilient_falls_back_to_per_token(
        read_solana_batch_mock: MagicMock,
        read_solana_single_mock: MagicMock,
) -> None:
    from src.integrations.blockchain.blockchain_price_service import _fetch_solana_pool_prices_resilient

    read_solana_batch_mock.side_effect = [
        BlockchainPriceUnavailableError("batch failed", blockchain_network=BlockchainNetwork.SOLANA),
        BlockchainPriceUnavailableError("chunk failed", blockchain_network=BlockchainNetwork.SOLANA),
    ]
    read_solana_single_mock.return_value = 0.42

    prices, had_infrastructure_failure = _fetch_solana_pool_prices_resilient([
        ("token-address", "pair-address", "raydium"),
    ])

    assert prices == {"token-address": 0.42}
    assert had_infrastructure_failure is False


@patch("src.integrations.blockchain.blockchain_price_service.read_solana_pool_price_usd")
@patch("src.integrations.blockchain.blockchain_price_service.read_solana_pool_prices_usd_batch")
def test_fetch_onchain_prices_with_metadata_marks_infrastructure_failure_when_rpc_totally_unavailable(
        read_solana_batch_mock: MagicMock,
        read_solana_single_mock: MagicMock,
) -> None:
    from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens_with_metadata

    read_solana_batch_mock.side_effect = BlockchainPriceUnavailableError(
        "rpc down",
        blockchain_network=BlockchainNetwork.SOLANA,
    )
    read_solana_single_mock.side_effect = BlockchainPriceUnavailableError(
        "rpc down",
        blockchain_network=BlockchainNetwork.SOLANA,
    )
    token = Token(
        symbol="MISSING",
        chain=BlockchainNetwork.SOLANA,
        token_address="missing-token",
        pair_address="missing-pair",
        dex_id="raydium",
    )

    fetch_result = fetch_onchain_prices_for_tokens_with_metadata([token], require_all_prices=False)

    assert fetch_result.onchain_prices.entry_count() == 0
    assert fetch_result.had_infrastructure_failure is True


@patch("src.integrations.blockchain.blockchain_price_service.read_solana_pool_prices_usd_batch")
def test_fetch_onchain_prices_with_metadata_partial_success_is_not_infrastructure_failure(
        read_solana_batch_mock: MagicMock,
) -> None:
    from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens_with_metadata

    read_solana_batch_mock.return_value = {"priced-token": 1.25}
    priced_token = Token(
        symbol="PRICED",
        chain=BlockchainNetwork.SOLANA,
        token_address="priced-token",
        pair_address="priced-pair",
        dex_id="raydium",
    )
    missing_token = Token(
        symbol="MISSING",
        chain=BlockchainNetwork.SOLANA,
        token_address="missing-token",
        pair_address="missing-pair",
        dex_id="raydium",
    )

    fetch_result = fetch_onchain_prices_for_tokens_with_metadata(
        [priced_token, missing_token],
        require_all_prices=False,
    )

    assert fetch_result.onchain_prices.entry_count() == 1
    assert fetch_result.had_infrastructure_failure is False


@patch("src.integrations.blockchain.blockchain_price_service.resolve_web3_provider_for_chain")
@patch("src.integrations.blockchain.blockchain_price_service.read_evm_pair_price_usd")
def test_fetch_onchain_prices_skips_missing_evm_when_not_required(
        read_evm_pair_mock: MagicMock,
        resolve_web3_provider_mock: MagicMock,
) -> None:
    from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens_with_metadata

    resolve_web3_provider_mock.return_value = MagicMock()
    read_evm_pair_mock.return_value = None
    missing_evm_token = Token(
        symbol="VELVET",
        chain=BlockchainNetwork.BASE,
        token_address="0xtoken",
        pair_address="0xpair",
        dex_id="uniswap",
    )

    fetch_result = fetch_onchain_prices_for_tokens_with_metadata(
        [missing_evm_token],
        require_all_prices=False,
    )

    assert fetch_result.onchain_prices.entry_count() == 0
    assert fetch_result.had_infrastructure_failure is False
