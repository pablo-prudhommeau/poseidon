from __future__ import annotations

import asyncio
import time
from typing import Any, Final, Optional

from aiohttp import ClientError, ClientResponseError
from eth_typing import URI
from web3 import AsyncWeb3, Web3
from web3._utils.http_session_manager import HTTPSessionManager
from web3.middleware import ExtraDataToPOAMiddleware
from web3.providers.async_base import AsyncJSONBaseProvider
from web3.types import RPCEndpoint, RPCResponse

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.evm.blockchain_evm_structures import (
    BlockchainEvmRpcEndpoint,
    BlockchainEvmRpcEndpointRateLimitState,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_EVM_RPC_REQUEST_TIMEOUT_SECONDS: Final[float] = 10.0
_TRANSIENT_RPC_FAILURE_COOLDOWN_SECONDS: Final[float] = 5.0
_NON_HISTORICAL_BLOCK_TAGS: Final[frozenset[str]] = frozenset({
    "latest",
    "pending",
    "earliest",
    "safe",
    "finalized",
})
_MISSING_HISTORICAL_STATE_MESSAGE_FRAGMENTS: Final[tuple[str, ...]] = (
    "block not found",
    "missing trie node",
    "header not found",
    "historical state",
)
_EVM_RPC_REQUEST_HEADERS: Final[dict[str, str]] = {
    "Content-Type": "application/json",
    "User-Agent": "poseidon-evm-rpc",
}


def _rpc_endpoint(url: str, supports_historical_state: bool = True) -> BlockchainEvmRpcEndpoint:
    return BlockchainEvmRpcEndpoint(url=url, supports_historical_state=supports_historical_state)


FREE_RPC_ENDPOINTS: dict[BlockchainNetwork, list[BlockchainEvmRpcEndpoint]] = {
    BlockchainNetwork.SOLANA: [
        _rpc_endpoint("https://api.mainnet-beta.solana.com"),
        _rpc_endpoint("https://solana-rpc.publicnode.com"),
        _rpc_endpoint("https://rpc.ankr.com/solana"),
    ],
    BlockchainNetwork.BSC: [
        _rpc_endpoint("https://bsc-dataseed.binance.org/"),
        _rpc_endpoint("https://bsc-dataseed1.defibit.io/"),
        _rpc_endpoint("https://bsc-dataseed2.defibit.io/"),
    ],
    BlockchainNetwork.BASE: [
        _rpc_endpoint("https://base.gateway.tenderly.co"),
        _rpc_endpoint("https://1rpc.io/base"),
        _rpc_endpoint("https://mainnet.base.org"),
    ],
    BlockchainNetwork.AVALANCHE: [
        _rpc_endpoint("https://avalanche-mainnet.gateway.tenderly.co", supports_historical_state=True),
        _rpc_endpoint("https://api.avax.network/ext/bc/C/rpc", supports_historical_state=True),
        _rpc_endpoint("https://avalanche-c-chain-rpc.publicnode.com", supports_historical_state=False),
        _rpc_endpoint("https://avalanche.drpc.org", supports_historical_state=False),
    ],
    BlockchainNetwork.ROBINHOOD: [
        _rpc_endpoint("https://rpc.mainnet.chain.robinhood.com"),
    ],
}

_resolved_web3_provider_cache: dict[BlockchainNetwork, Web3] = {}
_resolved_async_web3_provider_cache: dict[BlockchainNetwork, AsyncWeb3] = {}
_resolved_rpc_url_cache: dict[BlockchainNetwork, str] = {}
_blacklisted_rpc_urls: dict[str, float] = {}

_POA_EVM_CHAINS: frozenset[BlockchainNetwork] = frozenset({
    BlockchainNetwork.AVALANCHE,
})


def _inject_poa_middleware_if_required(chain: BlockchainNetwork, web3_client: Web3 | AsyncWeb3) -> None:
    if chain not in _POA_EVM_CHAINS:
        return
    web3_client.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)


def _is_rpc_url_blacklisted(rpc_url: str) -> bool:
    blacklist_timestamp = _blacklisted_rpc_urls.get(rpc_url)
    if blacklist_timestamp is None:
        return False

    if time.time() - blacklist_timestamp > settings.EVM_RPC_BLACKLIST_DURATION_SECONDS:
        del _blacklisted_rpc_urls[rpc_url]
        return False

    return True


def invalidate_rpc_cache_for_chain(chain: BlockchainNetwork) -> None:
    removed_url = _resolved_rpc_url_cache.pop(chain, None)
    removed_provider = _resolved_web3_provider_cache.pop(chain, None)
    _resolved_async_web3_provider_cache.pop(chain, None)
    if removed_url:
        _blacklisted_rpc_urls[removed_url] = time.time()
    if removed_url or removed_provider:
        logger.debug(
            "[BLOCKCHAIN][RPC][REGISTRY] RPC cache invalidated — blockchain_network=%s previous_rpc_url=%s",
            chain.value,
            removed_url,
        )


_PREMIUM_RPC_SETTING_NAME_BY_CHAIN: dict[BlockchainNetwork, str] = {
    BlockchainNetwork.SOLANA: "RPC_PREMIUM_URL_SOLANA",
    BlockchainNetwork.BSC: "RPC_PREMIUM_URL_BSC",
    BlockchainNetwork.BASE: "RPC_PREMIUM_URL_BASE",
    BlockchainNetwork.AVALANCHE: "RPC_PREMIUM_URL_AVALANCHE",
    BlockchainNetwork.ROBINHOOD: "RPC_PREMIUM_URL_ROBINHOOD",
}


def _get_premium_rpc_url(chain: BlockchainNetwork) -> str:
    setting_name = _PREMIUM_RPC_SETTING_NAME_BY_CHAIN.get(chain)
    if setting_name is None:
        return ""
    return getattr(settings, setting_name, "") or ""


def list_fallback_rpc_urls_for_chain(chain: BlockchainNetwork, primary_url: str) -> list[str]:
    urls: list[str] = []

    def _append_if_usable(candidate: str | None) -> None:
        if not candidate:
            return
        if candidate == primary_url:
            return
        if candidate in urls:
            return
        if _is_rpc_url_blacklisted(candidate):
            return
        urls.append(candidate)

    for free_rpc_endpoint in FREE_RPC_ENDPOINTS.get(chain, []):
        _append_if_usable(free_rpc_endpoint.url)

    _append_if_usable(_get_premium_rpc_url(chain))

    return urls


def _test_evm_rpc_connectivity(rpc_url: str) -> bool:
    try:
        import requests
        response = requests.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
            timeout=5,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 429:
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] EVM RPC rate-limited (HTTP 429) at %s", rpc_url)
            return False
        if response.status_code != 200:
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] EVM RPC returned HTTP %d at %s", response.status_code, rpc_url)
            return False
        response_json = response.json()
        if "error" in response_json:
            error_message = response_json["error"].get("message", "unknown")
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] EVM RPC returned JSON-RPC error at %s: %s", rpc_url, error_message)
            return False
        return "result" in response_json
    except Exception:
        return False


def _test_solana_rpc_connectivity(rpc_url: str) -> bool:
    try:
        import requests
        response = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [
                    ["11111111111111111111111111111111"],
                    {"encoding": "base64"}
                ]
            },
            timeout=5,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 429:
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Solana RPC rate-limited (HTTP 429) at %s", rpc_url)
            return False
        if response.status_code in (403, 413):
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Solana RPC blocked/limited (HTTP %d) at %s", response.status_code, rpc_url)
            return False
        if response.status_code != 200:
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Solana RPC returned HTTP %d at %s", response.status_code, rpc_url)
            return False
        response_json = response.json()
        if "error" in response_json:
            error_message = response_json["error"].get("message", "unknown")
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Solana RPC returned JSON-RPC error at %s: %s", rpc_url, error_message)
            return False
        result_value = response_json.get("result")
        return isinstance(result_value, dict) and "value" in result_value
    except Exception:
        return False


def resolve_rpc_url_for_chain(chain: BlockchainNetwork) -> str:
    cached_url = _resolved_rpc_url_cache.get(chain)
    if cached_url is not None:
        return cached_url

    free_endpoints = FREE_RPC_ENDPOINTS.get(chain, [])
    is_solana = (chain == BlockchainNetwork.SOLANA)
    failed_free_endpoint_count = 0

    for free_rpc_endpoint in free_endpoints:
        free_rpc_url = free_rpc_endpoint.url
        if _is_rpc_url_blacklisted(free_rpc_url):
            logger.debug(
                "[BLOCKCHAIN][RPC][REGISTRY] Skipping blacklisted free RPC — blockchain_network=%s rpc_url=%s",
                chain.value,
                free_rpc_url,
            )
            continue

        logger.debug(
            "[BLOCKCHAIN][RPC][REGISTRY] Testing free RPC endpoint — blockchain_network=%s rpc_url=%s",
            chain.value,
            free_rpc_url,
        )
        connectivity_test_passed = (
            _test_solana_rpc_connectivity(free_rpc_url) if is_solana
            else _test_evm_rpc_connectivity(free_rpc_url)
        )
        if connectivity_test_passed:
            logger.debug(
                "[BLOCKCHAIN][RPC][REGISTRY] Connected to free RPC endpoint — blockchain_network=%s rpc_url=%s",
                chain.value,
                free_rpc_url,
            )
            _resolved_rpc_url_cache[chain] = free_rpc_url
            return free_rpc_url
        failed_free_endpoint_count += 1
        logger.debug(
            "[BLOCKCHAIN][RPC][REGISTRY] Free RPC endpoint unreachable — blockchain_network=%s rpc_url=%s",
            chain.value,
            free_rpc_url,
        )

    if failed_free_endpoint_count > 0:
        logger.warning(
            "[BLOCKCHAIN][RPC][REGISTRY] All tested free RPC endpoints unreachable — "
            "blockchain_network=%s tested_endpoint_count=%d",
            chain.value,
            failed_free_endpoint_count,
        )

    premium_rpc_url = _get_premium_rpc_url(chain)
    if premium_rpc_url:
        if _is_rpc_url_blacklisted(premium_rpc_url):
            logger.debug(
                "[BLOCKCHAIN][RPC][REGISTRY] Skipping blacklisted premium RPC endpoint — blockchain_network=%s",
                chain.value,
            )
        else:
            logger.debug(
                "[BLOCKCHAIN][RPC][REGISTRY] Testing premium RPC endpoint — blockchain_network=%s rpc_url=%s",
                chain.value,
                premium_rpc_url,
            )
            connectivity_test_passed = (
                _test_solana_rpc_connectivity(premium_rpc_url) if is_solana
                else _test_evm_rpc_connectivity(premium_rpc_url)
            )
            if connectivity_test_passed:
                logger.info(
                    "[BLOCKCHAIN][RPC][REGISTRY] Connected to premium RPC endpoint — "
                    "blockchain_network=%s",
                    chain.value,
                )
                _resolved_rpc_url_cache[chain] = premium_rpc_url
                return premium_rpc_url
            logger.warning(
                "[BLOCKCHAIN][RPC][REGISTRY] Premium RPC endpoint unreachable — blockchain_network=%s",
                chain.value,
            )
    else:
        logger.debug(
            "[BLOCKCHAIN][RPC][REGISTRY] No premium RPC configured — blockchain_network=%s",
            chain.value,
        )

    raise ConnectionError(f"[BLOCKCHAIN][RPC][REGISTRY] No reachable RPC endpoint found for chain {chain.value}")


def resolve_web3_provider_for_chain(chain: BlockchainNetwork) -> Optional[Web3]:
    cached_provider = _resolved_web3_provider_cache.get(chain)
    if cached_provider is not None:
        return cached_provider

    try:
        rpc_url = resolve_rpc_url_for_chain(chain)
    except ConnectionError:
        logger.warning("[BLOCKCHAIN][RPC][REGISTRY] Cannot resolve any RPC for chain %s", chain.value)
        return None

    provider = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
    _inject_poa_middleware_if_required(chain, provider)
    _resolved_web3_provider_cache[chain] = provider
    return provider


def _resolve_reachable_premium_rpc_endpoint(chain: BlockchainNetwork) -> Optional[BlockchainEvmRpcEndpoint]:
    premium_rpc_url = _get_premium_rpc_url(chain)
    if not premium_rpc_url:
        return None
    if _is_rpc_url_blacklisted(premium_rpc_url):
        logger.debug(
            "[BLOCKCHAIN][RPC][REGISTRY] Skipping blacklisted premium RPC endpoint — blockchain_network=%s",
            chain.value,
        )
        return None

    is_solana = chain == BlockchainNetwork.SOLANA
    connectivity_test_passed = (
        _test_solana_rpc_connectivity(premium_rpc_url) if is_solana
        else _test_evm_rpc_connectivity(premium_rpc_url)
    )
    if not connectivity_test_passed:
        logger.warning(
            "[BLOCKCHAIN][RPC][REGISTRY] Premium RPC endpoint unreachable — blockchain_network=%s",
            chain.value,
        )
        return None

    return BlockchainEvmRpcEndpoint(url=premium_rpc_url, supports_historical_state=True)


def _collect_rpc_endpoints_for_chain(chain: BlockchainNetwork) -> list[BlockchainEvmRpcEndpoint]:
    collected_rpc_endpoints: list[BlockchainEvmRpcEndpoint] = []
    seen_rpc_urls: set[str] = set()
    for free_rpc_endpoint in FREE_RPC_ENDPOINTS.get(chain, []):
        if _is_rpc_url_blacklisted(free_rpc_endpoint.url):
            continue
        if free_rpc_endpoint.url in seen_rpc_urls:
            continue
        seen_rpc_urls.add(free_rpc_endpoint.url)
        collected_rpc_endpoints.append(free_rpc_endpoint)

    premium_rpc_endpoint = _resolve_reachable_premium_rpc_endpoint(chain)
    if premium_rpc_endpoint is not None and premium_rpc_endpoint.url not in seen_rpc_urls:
        collected_rpc_endpoints.append(premium_rpc_endpoint)
    return collected_rpc_endpoints


def resolve_async_web3_provider_for_chain(chain: BlockchainNetwork) -> AsyncWeb3:
    cached_provider = _resolved_async_web3_provider_cache.get(chain)
    if cached_provider is not None:
        return cached_provider

    rpc_endpoints = _collect_rpc_endpoints_for_chain(chain)
    if len(rpc_endpoints) == 0:
        logger.warning("[BLOCKCHAIN][RPC][REGISTRY] Cannot resolve any RPC for chain %s", chain.value)
        raise ConnectionError(f"[BLOCKCHAIN][RPC][REGISTRY] No reachable RPC endpoint found for chain {chain.value}")

    rotating_provider = RateLimitedRotatingAsyncHttpProvider(
        blockchain_network=chain,
        rpc_endpoints=rpc_endpoints,
    )
    web3_client = AsyncWeb3(rotating_provider)
    _inject_poa_middleware_if_required(chain, web3_client)
    _resolved_async_web3_provider_cache[chain] = web3_client
    logger.info(
        "[BLOCKCHAIN][RPC][REGISTRY] Rotating RPC provider ready — blockchain_network=%s endpoint_count=%d",
        chain.value,
        len(rpc_endpoints),
    )
    return web3_client


def get_supported_evm_chains() -> list[BlockchainNetwork]:
    return [chain for chain in FREE_RPC_ENDPOINTS if chain != BlockchainNetwork.SOLANA]


class BlockchainRpcRateLimitedError(ConnectionError):
    def __init__(self, blockchain_network: BlockchainNetwork, detail: str) -> None:
        self.blockchain_network: BlockchainNetwork = blockchain_network
        super().__init__(detail)


class RateLimitedRotatingAsyncHttpProvider(AsyncJSONBaseProvider):
    def __init__(
            self,
            blockchain_network: BlockchainNetwork,
            rpc_endpoints: list[BlockchainEvmRpcEndpoint],
    ) -> None:
        super().__init__()
        self._blockchain_network: BlockchainNetwork = blockchain_network
        self._rpc_endpoints: list[BlockchainEvmRpcEndpoint] = list(rpc_endpoints)
        self._endpoint_states: list[BlockchainEvmRpcEndpointRateLimitState] = [
            BlockchainEvmRpcEndpointRateLimitState(rpc_url=rpc_endpoint.url)
            for rpc_endpoint in self._rpc_endpoints
        ]
        self._request_session_manager: HTTPSessionManager = HTTPSessionManager()
        self._coordination_lock: asyncio.Lock = asyncio.Lock()
        self._next_request_not_before_monotonic: Optional[float] = None
        self._last_successful_rpc_url: Optional[str] = None

    async def make_request(self, method: RPCEndpoint, params: Any) -> RPCResponse:
        requires_historical_state = _request_targets_historical_block(params)
        request_data = self.encode_rpc_request(method, params)
        excluded_rpc_urls: set[str] = set()
        last_missing_historical_state_response: Optional[RPCResponse] = None

        while True:
            selected_endpoint = await self._select_available_endpoint(
                requires_historical_state=requires_historical_state,
                excluded_rpc_urls=excluded_rpc_urls,
            )
            if selected_endpoint is None:
                if last_missing_historical_state_response is not None:
                    return last_missing_historical_state_response
                logger.warning(
                    "[BLOCKCHAIN][RPC][REGISTRY][RATE_LIMIT] All eligible RPC endpoints are cooling down "
                    "— blockchain_network=%s historical_state_required=%s",
                    self._blockchain_network.value,
                    requires_historical_state,
                )
                raise BlockchainRpcRateLimitedError(
                    blockchain_network=self._blockchain_network,
                    detail=(
                        "[BLOCKCHAIN][RPC][REGISTRY][RATE_LIMIT] No RPC endpoint available for "
                        f"{self._blockchain_network.value}"
                    ),
                )

            await self._wait_for_request_slot()
            try:
                raw_response = await self._request_session_manager.async_make_post_request(
                    URI(selected_endpoint.url),
                    request_data,
                    headers=_EVM_RPC_REQUEST_HEADERS,
                    timeout=_EVM_RPC_REQUEST_TIMEOUT_SECONDS,
                )
            except ClientResponseError as response_error:
                excluded_rpc_urls.add(selected_endpoint.url)
                if response_error.status == 429:
                    cooldown_seconds = await self._cool_down_after_rate_limit(
                        rpc_url=selected_endpoint.url,
                        retry_after_seconds=_extract_retry_after_seconds(response_error),
                    )
                    logger.warning(
                        "[BLOCKCHAIN][RPC][REGISTRY][RATE_LIMIT] RPC endpoint rate limited "
                        "— blockchain_network=%s rpc_url=%s cooldown_seconds=%0.0f",
                        self._blockchain_network.value,
                        selected_endpoint.url,
                        cooldown_seconds,
                    )
                    continue
                if response_error.status >= 500:
                    await self._cool_down_after_transient_failure(rpc_url=selected_endpoint.url)
                    logger.warning(
                        "[BLOCKCHAIN][RPC][REGISTRY][ROTATION] RPC endpoint returned HTTP %s "
                        "— blockchain_network=%s rpc_url=%s",
                        response_error.status,
                        self._blockchain_network.value,
                        selected_endpoint.url,
                    )
                    continue
                raise
            except (TimeoutError, ClientError):
                excluded_rpc_urls.add(selected_endpoint.url)
                await self._cool_down_after_transient_failure(rpc_url=selected_endpoint.url)
                logger.debug(
                    "[BLOCKCHAIN][RPC][REGISTRY][ROTATION] RPC endpoint request failed "
                    "— blockchain_network=%s rpc_url=%s",
                    self._blockchain_network.value,
                    selected_endpoint.url,
                )
                continue

            try:
                response = self.decode_rpc_response(raw_response)
            except (ValueError, TypeError):
                excluded_rpc_urls.add(selected_endpoint.url)
                await self._cool_down_after_transient_failure(rpc_url=selected_endpoint.url)
                logger.debug(
                    "[BLOCKCHAIN][RPC][REGISTRY][ROTATION] RPC endpoint returned an unreadable payload "
                    "— blockchain_network=%s rpc_url=%s",
                    self._blockchain_network.value,
                    selected_endpoint.url,
                )
                continue

            if _response_reports_missing_historical_state(response):
                excluded_rpc_urls.add(selected_endpoint.url)
                if not selected_endpoint.supports_historical_state:
                    await self._mark_historical_state_unavailable(rpc_url=selected_endpoint.url)
                await self._cool_down_after_transient_failure(rpc_url=selected_endpoint.url)
                last_missing_historical_state_response = response
                logger.debug(
                    "[BLOCKCHAIN][RPC][REGISTRY][ROTATION] RPC endpoint has no historical state "
                    "— blockchain_network=%s rpc_url=%s",
                    self._blockchain_network.value,
                    selected_endpoint.url,
                )
                continue

            await self._record_successful_endpoint(rpc_url=selected_endpoint.url)
            return response

    async def disconnect(self) -> None:
        session_cache = self._request_session_manager.session_cache
        for _, cached_session in session_cache.items():
            await cached_session.close()
        session_cache.clear()

    async def _select_available_endpoint(
            self,
            requires_historical_state: bool,
            excluded_rpc_urls: set[str],
    ) -> Optional[BlockchainEvmRpcEndpoint]:
        now_monotonic = time.monotonic()
        async with self._coordination_lock:
            for rpc_endpoint, endpoint_state in zip(self._rpc_endpoints, self._endpoint_states, strict=True):
                if rpc_endpoint.url in excluded_rpc_urls:
                    continue
                if (
                        endpoint_state.cooldown_until_monotonic is not None
                        and now_monotonic < endpoint_state.cooldown_until_monotonic
                ):
                    continue
                if requires_historical_state and (
                        not rpc_endpoint.supports_historical_state
                        or endpoint_state.historical_state_unavailable
                ):
                    continue
                return rpc_endpoint
        return None

    async def _wait_for_request_slot(self) -> None:
        minimum_spacing_seconds = 1.0 / float(settings.EVM_RPC_MAX_REQUESTS_PER_SECOND)
        async with self._coordination_lock:
            now_monotonic = time.monotonic()
            scheduled_monotonic = now_monotonic
            if (
                    self._next_request_not_before_monotonic is not None
                    and self._next_request_not_before_monotonic > now_monotonic
            ):
                scheduled_monotonic = self._next_request_not_before_monotonic
            self._next_request_not_before_monotonic = scheduled_monotonic + minimum_spacing_seconds
            sleep_seconds = scheduled_monotonic - now_monotonic
        if sleep_seconds > 0.0:
            await asyncio.sleep(sleep_seconds)

    async def _cool_down_after_rate_limit(
            self,
            rpc_url: str,
            retry_after_seconds: Optional[int],
    ) -> float:
        async with self._coordination_lock:
            endpoint_state = self._resolve_endpoint_state(rpc_url)
            endpoint_state.consecutive_failure_count += 1
            if retry_after_seconds is not None and retry_after_seconds > 0:
                cooldown_seconds = min(
                    float(retry_after_seconds),
                    float(settings.EVM_RPC_RATE_LIMIT_MAX_COOLDOWN_SECONDS),
                )
            else:
                exponential_backoff_seconds = settings.EVM_RPC_RATE_LIMIT_INITIAL_BACKOFF_SECONDS * (
                    2 ** (endpoint_state.consecutive_failure_count - 1)
                )
                cooldown_seconds = min(
                    exponential_backoff_seconds,
                    float(settings.EVM_RPC_RATE_LIMIT_MAX_COOLDOWN_SECONDS),
                )
            endpoint_state.cooldown_until_monotonic = time.monotonic() + cooldown_seconds
            return cooldown_seconds

    async def _cool_down_after_transient_failure(self, rpc_url: str) -> None:
        async with self._coordination_lock:
            endpoint_state = self._resolve_endpoint_state(rpc_url)
            endpoint_state.cooldown_until_monotonic = time.monotonic() + _TRANSIENT_RPC_FAILURE_COOLDOWN_SECONDS

    async def _mark_historical_state_unavailable(self, rpc_url: str) -> None:
        async with self._coordination_lock:
            endpoint_state = self._resolve_endpoint_state(rpc_url)
            endpoint_state.historical_state_unavailable = True

    async def _record_successful_endpoint(self, rpc_url: str) -> None:
        async with self._coordination_lock:
            endpoint_state = self._resolve_endpoint_state(rpc_url)
            endpoint_state.consecutive_failure_count = 0
            endpoint_state.cooldown_until_monotonic = None
            endpoint_changed = self._last_successful_rpc_url != rpc_url
            self._last_successful_rpc_url = rpc_url
        if endpoint_changed:
            logger.debug(
                "[BLOCKCHAIN][RPC][REGISTRY][ROTATION] RPC endpoint selected "
                "— blockchain_network=%s rpc_url=%s",
                self._blockchain_network.value,
                rpc_url,
            )

    def _resolve_endpoint_state(self, rpc_url: str) -> BlockchainEvmRpcEndpointRateLimitState:
        for endpoint_state in self._endpoint_states:
            if endpoint_state.rpc_url == rpc_url:
                return endpoint_state
        raise KeyError(f"No RPC endpoint state registered for {rpc_url}")


def _request_targets_historical_block(params: object) -> bool:
    if not isinstance(params, (list, tuple)) or len(params) == 0:
        return False
    block_identifier = params[-1]
    if isinstance(block_identifier, bool):
        return False
    if isinstance(block_identifier, int):
        return True
    if not isinstance(block_identifier, str):
        return False
    normalized_block_identifier = block_identifier.lower()
    if normalized_block_identifier in _NON_HISTORICAL_BLOCK_TAGS:
        return False
    if not normalized_block_identifier.startswith("0x"):
        return False
    hexadecimal_body = normalized_block_identifier[2:]
    if len(hexadecimal_body) == 0 or len(hexadecimal_body) >= 40:
        return False
    for character in hexadecimal_body:
        if character not in "0123456789abcdef":
            return False
    return True


def _response_reports_missing_historical_state(response: RPCResponse) -> bool:
    if not isinstance(response, dict) or "error" not in response:
        return False
    error_payload = response["error"]
    if not isinstance(error_payload, dict) or "message" not in error_payload:
        return False
    error_message = error_payload["message"]
    if not isinstance(error_message, str):
        return False
    normalized_error_message = error_message.lower()
    for message_fragment in _MISSING_HISTORICAL_STATE_MESSAGE_FRAGMENTS:
        if message_fragment in normalized_error_message:
            return True
    return False


def _extract_retry_after_seconds(response_error: ClientResponseError) -> Optional[int]:
    if response_error.headers is None:
        return None
    raw_retry_after = response_error.headers.get("Retry-After")
    if raw_retry_after is None:
        return None
    try:
        parsed_retry_after_seconds = int(str(raw_retry_after).strip())
    except ValueError:
        return None
    if parsed_retry_after_seconds <= 0:
        return None
    return parsed_retry_after_seconds
