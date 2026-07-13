from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from web3 import Web3

from src.integrations.routescan.routescan_client import RoutescanClient

FAKE_WALLET_LOWER = "0x1111111111111111111111111111111111111111"
FAKE_WALLET_CHECKSUM = Web3.to_checksum_address(FAKE_WALLET_LOWER)


def test_routescan_client_normalizes_wallet_addresses() -> None:
    routescan_client = RoutescanClient(wallet_address=FAKE_WALLET_LOWER)

    assert routescan_client.wallet_address == FAKE_WALLET_LOWER
    assert routescan_client._wallet_checksum_address == FAKE_WALLET_CHECKSUM


def test_routescan_client_picks_highest_block_from_recent_window() -> None:
    async def run_test() -> None:
        routescan_client = RoutescanClient(wallet_address=FAKE_WALLET_LOWER)
        request_json_mock = AsyncMock(return_value={
            "result": [
                {"hash": "0xbbbb", "blockNumber": "100"},
                {"hash": "0xaaaa", "blockNumber": "200"},
            ],
        })

        with patch.object(routescan_client, "_request_json", request_json_mock):
            latest_transaction_hash = await routescan_client.fetch_latest_normal_transaction_hash()

        assert latest_transaction_hash == "0xaaaa"
        request_parameters = request_json_mock.await_args.kwargs["request_parameters"]
        assert request_parameters["address"] == FAKE_WALLET_CHECKSUM
        assert request_parameters["offset"] == 5

    asyncio.run(run_test())


def test_routescan_client_adds_cache_busting_parameter() -> None:
    busted_parameters = RoutescanClient._cache_busting_parameters({"address": FAKE_WALLET_CHECKSUM})

    assert "_" in busted_parameters
    assert busted_parameters["address"] == FAKE_WALLET_CHECKSUM
