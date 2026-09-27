from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_protocol_reader import AaveProtocolReader
from src.integrations.aave.aave_structures import AaveScaledBalanceBatchRequest
from src.integrations.blockchain.blockchain_rpc_registry import BlockchainRpcRateLimitedError


def _build_reader_with_pool_contract() -> AaveProtocolReader:
    reader = AaveProtocolReader()
    reader._web3_client = MagicMock()
    reader._pool_contract = MagicMock()
    reader._pool_contract.address = "0x794a61358d6845594f94dc1db02a252b5b4814ad"
    reader._pool_contract.encode_abi.return_value = "0x1234"
    token_contract = MagicMock()
    token_contract.encode_abi.return_value = "0xabcd"
    reader._web3_client.eth.contract.return_value = token_contract
    return reader


def test_protocol_reader_propagates_rate_limit_errors() -> None:
    reader = _build_reader_with_pool_contract()

    async def run_test() -> None:
        with patch(
                "src.integrations.aave.aave_protocol_reader.execute_multicall3_aggregate",
                side_effect=BlockchainRpcRateLimitedError(
                    blockchain_network=BlockchainNetwork.AVALANCHE,
                    detail="cooling down",
                ),
        ):
            with pytest.raises(BlockchainRpcRateLimitedError):
                await reader.fetch_scaled_balances_at_block_batch(
                    wallet_address="0x0000000000000000000000000000000000000001",
                    scaled_balance_batch_requests=[
                        AaveScaledBalanceBatchRequest(
                            underlying_address="0x0000000000000000000000000000000000000002",
                            a_token_address="0x0000000000000000000000000000000000000003",
                            variable_debt_token_address="0x0000000000000000000000000000000000000004",
                            decimal_count=6,
                        ),
                    ],
                    block_number=12,
                )

    asyncio.run(run_test())


def test_protocol_reader_returns_an_empty_batch_for_other_errors() -> None:
    reader = _build_reader_with_pool_contract()

    async def run_test() -> None:
        with patch(
                "src.integrations.aave.aave_protocol_reader.execute_multicall3_aggregate",
                side_effect=RuntimeError("node unavailable"),
        ):
            scaled_balances = await reader.fetch_scaled_balances_at_block_batch(
                wallet_address="0x0000000000000000000000000000000000000001",
                scaled_balance_batch_requests=[
                    AaveScaledBalanceBatchRequest(
                        underlying_address="0x0000000000000000000000000000000000000002",
                        a_token_address="0x0000000000000000000000000000000000000003",
                        variable_debt_token_address="0x0000000000000000000000000000000000000004",
                        decimal_count=6,
                    ),
                ],
                block_number=12,
            )
        assert scaled_balances == []

    asyncio.run(run_test())
