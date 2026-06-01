from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.core.structures.structures import BlockchainNetwork, Token
from src.integrations.blockchain.blockchain_exceptions import BlockchainPriceUnavailableError
from src.integrations.blockchain.blockchain_price_service import fetch_onchain_prices_for_tokens
from src.integrations.blockchain.solana.blockchain_solana_price_reader import read_solana_pool_prices_usd_batch


@patch("src.integrations.blockchain.solana.blockchain_solana_price_reader.get_solana_rpc_url")
def test_read_solana_pool_prices_usd_batch_raises_when_rpc_unavailable(
        get_solana_rpc_url_mock: MagicMock,
) -> None:
    get_solana_rpc_url_mock.side_effect = ConnectionError(
        "[BLOCKCHAIN][RPC][REGISTRY] No reachable RPC endpoint found for chain solana",
    )

    with pytest.raises(BlockchainPriceUnavailableError) as raised_error:
        read_solana_pool_prices_usd_batch([
            ("token-address", "pair-address", "raydium"),
        ])

    assert raised_error.value.blockchain_network == BlockchainNetwork.SOLANA


@patch("src.integrations.blockchain.solana.blockchain_solana_price_reader.read_solana_pool_prices_usd_batch")
def test_fetch_onchain_prices_for_tokens_returns_empty_when_solana_unavailable(
        read_solana_batch_mock: MagicMock,
) -> None:
    read_solana_batch_mock.side_effect = BlockchainPriceUnavailableError(
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

    prices_by_pair_address = fetch_onchain_prices_for_tokens([token])

    assert prices_by_pair_address == {}
