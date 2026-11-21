from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from web3 import Web3

from src.integrations.routescan.routescan_client import RoutescanClient
from src.integrations.routescan.routescan_constants import ROUTESCAN_END_BLOCK

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
        assert request_parameters["endblock"] == ROUTESCAN_END_BLOCK
        assert request_parameters["endblock"] > 99_999_999

    asyncio.run(run_test())


def test_routescan_pagination_requests_blocks_past_the_old_ceiling() -> None:
    async def run_test() -> None:
        routescan_client = RoutescanClient(wallet_address=FAKE_WALLET_LOWER)
        response = MagicMock()
        response.json.return_value = {"status": "1", "result": []}
        http_client = AsyncMock()
        http_client.get = AsyncMock(return_value=response)
        http_client.__aenter__.return_value = http_client
        http_client.__aexit__.return_value = None

        with patch(
                "src.integrations.routescan.routescan_client.httpx.AsyncClient",
                return_value=http_client,
        ):
            records = await routescan_client.fetch_all_token_transactions()

        assert records == []
        request_parameters = http_client.get.await_args.kwargs["params"]
        assert request_parameters["endblock"] == ROUTESCAN_END_BLOCK
        assert request_parameters["endblock"] > 99_999_999

    asyncio.run(run_test())


def test_routescan_client_adds_cache_busting_parameter() -> None:
    busted_parameters = RoutescanClient._cache_busting_parameters({"address": FAKE_WALLET_CHECKSUM})

    assert "_" in busted_parameters
    assert busted_parameters["address"] == FAKE_WALLET_CHECKSUM
