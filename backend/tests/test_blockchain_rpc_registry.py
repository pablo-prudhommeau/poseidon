from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

from aiohttp import ClientResponseError
from web3.types import RPCEndpoint

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.blockchain_rpc_registry import (
    FREE_RPC_ENDPOINTS,
    BlockchainRpcRateLimitedError,
    RateLimitedRotatingAsyncHttpProvider,
)
from src.integrations.blockchain.evm.blockchain_evm_structures import BlockchainEvmRpcEndpoint


def _configure_rpc_settings(settings_mock: object, max_requests_per_second: int = 1000, max_cooldown_seconds: float = 900.0) -> None:
    settings_mock.EVM_RPC_MAX_REQUESTS_PER_SECOND = max_requests_per_second
    settings_mock.EVM_RPC_RATE_LIMIT_MAX_COOLDOWN_SECONDS = max_cooldown_seconds
    settings_mock.EVM_RPC_RATE_LIMIT_INITIAL_BACKOFF_SECONDS = 60.0


def _build_provider(
        rpc_endpoints: list[BlockchainEvmRpcEndpoint],
) -> RateLimitedRotatingAsyncHttpProvider:
    return RateLimitedRotatingAsyncHttpProvider(
        blockchain_network=BlockchainNetwork.AVALANCHE,
        rpc_endpoints=rpc_endpoints,
    )


def test_avalanche_free_endpoints_keep_archive_nodes_and_drop_ankr() -> None:
    avalanche_endpoints = FREE_RPC_ENDPOINTS[BlockchainNetwork.AVALANCHE]
    endpoint_by_url = {endpoint.url: endpoint for endpoint in avalanche_endpoints}

    assert "https://rpc.ankr.com/avalanche" not in endpoint_by_url
    assert "https://api.zan.top/avax-mainnet/ext/bc/C/rpc" not in endpoint_by_url
    assert avalanche_endpoints[0].url == "https://avalanche-mainnet.gateway.tenderly.co"
    assert endpoint_by_url["https://api.avax.network/ext/bc/C/rpc"].supports_historical_state is True
    assert endpoint_by_url["https://avalanche-mainnet.gateway.tenderly.co"].supports_historical_state is True
    assert endpoint_by_url["https://avalanche-c-chain-rpc.publicnode.com"].supports_historical_state is False


def test_rotating_provider_switches_endpoint_after_rate_limit_and_caps_retry_after() -> None:
    archive_endpoint = BlockchainEvmRpcEndpoint(
        url="https://archive.example",
        supports_historical_state=True,
    )
    fallback_endpoint = BlockchainEvmRpcEndpoint(
        url="https://fallback.example",
        supports_historical_state=True,
    )
    requested_urls: list[str] = []

    async def fake_post(endpoint_uri: object, data: bytes, headers: dict[str, str], timeout: float) -> bytes:
        requested_urls.append(str(endpoint_uri))
        if str(endpoint_uri) == archive_endpoint.url:
            raise ClientResponseError(
                None,
                (),
                status=429,
                message="Too Many Requests",
                headers={"Retry-After": "5000"},
            )
        return b'{"jsonrpc":"2.0","id":1,"result":"0x2"}'

    async def run_test() -> None:
        provider = _build_provider([archive_endpoint, fallback_endpoint])
        provider._request_session_manager.async_make_post_request = fake_post
        response = await provider.make_request(RPCEndpoint("eth_blockNumber"), [])
        assert response["result"] == "0x2"
        assert requested_urls == [archive_endpoint.url, fallback_endpoint.url]
        cooldown_until = provider._endpoint_states[0].cooldown_until_monotonic
        assert cooldown_until is not None
        assert 0 < cooldown_until - time.monotonic() <= 10.5

    with patch("src.integrations.blockchain.blockchain_rpc_registry.settings") as settings_mock:
        _configure_rpc_settings(settings_mock, max_cooldown_seconds=10.0)
        asyncio.run(run_test())


def test_rotating_provider_uses_only_archive_endpoints_for_historical_blocks() -> None:
    latest_endpoint = BlockchainEvmRpcEndpoint(
        url="https://latest.example",
        supports_historical_state=False,
    )
    archive_endpoint = BlockchainEvmRpcEndpoint(
        url="https://archive.example",
        supports_historical_state=True,
    )
    requested_urls: list[str] = []

    async def fake_post(endpoint_uri: object, data: bytes, headers: dict[str, str], timeout: float) -> bytes:
        requested_urls.append(str(endpoint_uri))
        return b'{"jsonrpc":"2.0","id":1,"result":"0x3"}'

    async def run_test() -> None:
        provider = _build_provider([latest_endpoint, archive_endpoint])
        provider._request_session_manager.async_make_post_request = fake_post
        await provider.make_request(
            RPCEndpoint("eth_call"),
            [{"to": "0x1111111111111111111111111111111111111111", "data": "0xabcdef"}, "0x10"],
        )
        assert requested_urls == [archive_endpoint.url]

    with patch("src.integrations.blockchain.blockchain_rpc_registry.settings") as settings_mock:
        _configure_rpc_settings(settings_mock)
        asyncio.run(run_test())


def test_rotating_provider_raises_when_every_endpoint_is_cooling_down() -> None:
    endpoint = BlockchainEvmRpcEndpoint(url="https://archive.example", supports_historical_state=True)
    post_called = False

    async def fake_post(endpoint_uri: object, data: bytes, headers: dict[str, str], timeout: float) -> bytes:
        nonlocal post_called
        post_called = True
        return b'{"jsonrpc":"2.0","id":1,"result":"0x1"}'

    async def run_test() -> None:
        provider = _build_provider([endpoint])
        provider._request_session_manager.async_make_post_request = fake_post
        provider._endpoint_states[0].cooldown_until_monotonic = time.monotonic() + 60
        try:
            await provider.make_request(RPCEndpoint("eth_blockNumber"), [])
            raise AssertionError("rate limit error was not raised")
        except BlockchainRpcRateLimitedError as rate_limit_error:
            assert rate_limit_error.blockchain_network == BlockchainNetwork.AVALANCHE
        assert post_called is False

    with patch("src.integrations.blockchain.blockchain_rpc_registry.settings") as settings_mock:
        _configure_rpc_settings(settings_mock)
        asyncio.run(run_test())


def test_rotating_provider_spaces_requests_with_the_token_bucket() -> None:
    slept_seconds: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept_seconds.append(seconds)

    async def run_test() -> None:
        provider = _build_provider([
            BlockchainEvmRpcEndpoint(url="https://archive.example", supports_historical_state=True),
        ])
        with patch("src.integrations.blockchain.blockchain_rpc_registry.time.monotonic", side_effect=[0.0, 0.0]):
            with patch("src.integrations.blockchain.blockchain_rpc_registry.asyncio.sleep", fake_sleep):
                await provider._wait_for_request_slot()
                await provider._wait_for_request_slot()
        assert slept_seconds == [0.5]

    with patch("src.integrations.blockchain.blockchain_rpc_registry.settings") as settings_mock:
        _configure_rpc_settings(settings_mock, max_requests_per_second=2)
        asyncio.run(run_test())
