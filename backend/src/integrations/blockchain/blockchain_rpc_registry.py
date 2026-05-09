from __future__ import annotations

from typing import Optional

from web3 import AsyncWeb3, Web3

from src.configuration.config import settings
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

from src.core.structures.structures import BlockchainNetwork
import time

FREE_RPC_ENDPOINTS: dict[BlockchainNetwork, list[str]] = {
    BlockchainNetwork.SOLANA: [
        "https://api.mainnet-beta.solana.com",
        "https://solana-rpc.publicnode.com",
        "https://rpc.ankr.com/solana",
    ],
    BlockchainNetwork.BSC: [
        "https://bsc-dataseed.binance.org/",
        "https://bsc-dataseed1.defibit.io/",
        "https://bsc-dataseed2.defibit.io/",
    ],
    BlockchainNetwork.BASE: [
        "https://base.gateway.tenderly.co",
        "https://1rpc.io/base",
        "https://mainnet.base.org",
    ],
    BlockchainNetwork.AVALANCHE: [
        "https://api.avax.network/ext/bc/C/rpc",
        "https://rpc.ankr.com/avalanche",
    ],
}

_resolved_web3_provider_cache: dict[BlockchainNetwork, Web3] = {}
_resolved_async_web3_provider_cache: dict[BlockchainNetwork, AsyncWeb3] = {}
_resolved_rpc_url_cache: dict[BlockchainNetwork, str] = {}
_blacklisted_rpc_urls: dict[str, float] = {}


def _is_rpc_url_blacklisted(rpc_url: str) -> bool:
    blacklist_timestamp = _blacklisted_rpc_urls.get(rpc_url)
    if blacklist_timestamp is None:
        return False

    if time.time() - blacklist_timestamp > 5:
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
        logger.warning("[BLOCKCHAIN][RPC][REGISTRY] Invalidated cached RPC for %s (was %s) and temporarily blacklisted", chain.value, removed_url)


_PREMIUM_RPC_SETTING_NAME_BY_CHAIN: dict[BlockchainNetwork, str] = {
    BlockchainNetwork.SOLANA: "RPC_PREMIUM_URL_SOLANA",
    BlockchainNetwork.BSC: "RPC_PREMIUM_URL_BSC",
    BlockchainNetwork.BASE: "RPC_PREMIUM_URL_BASE",
    BlockchainNetwork.AVALANCHE: "RPC_PREMIUM_URL_AVALANCHE",
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

    for free_url in FREE_RPC_ENDPOINTS.get(chain, []):
        _append_if_usable(free_url)

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

    for free_rpc_url in free_endpoints:
        if _is_rpc_url_blacklisted(free_rpc_url):
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Skipping blacklisted free RPC for %s at %s", chain.value, free_rpc_url)
            continue

        logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Testing free RPC for %s at %s", chain.value, free_rpc_url)
        connectivity_test_passed = (
            _test_solana_rpc_connectivity(free_rpc_url) if is_solana
            else _test_evm_rpc_connectivity(free_rpc_url)
        )
        if connectivity_test_passed:
            logger.info("[BLOCKCHAIN][RPC][REGISTRY] Connected to free RPC for %s at %s", chain.value, free_rpc_url)
            _resolved_rpc_url_cache[chain] = free_rpc_url
            return free_rpc_url
        logger.warning("[BLOCKCHAIN][RPC][REGISTRY] Free RPC unreachable for %s at %s", chain.value, free_rpc_url)

    premium_rpc_url = _get_premium_rpc_url(chain)
    if premium_rpc_url:
        if _is_rpc_url_blacklisted(premium_rpc_url):
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Skipping blacklisted premium RPC for %s", chain.value)
        else:
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Testing premium RPC for %s at %s", chain.value, premium_rpc_url)
            connectivity_test_passed = (
                _test_solana_rpc_connectivity(premium_rpc_url) if is_solana
                else _test_evm_rpc_connectivity(premium_rpc_url)
            )
            if connectivity_test_passed:
                logger.info("[BLOCKCHAIN][RPC][REGISTRY] Connected to premium RPC for %s", chain.value)
                _resolved_rpc_url_cache[chain] = premium_rpc_url
                return premium_rpc_url
            logger.warning("[BLOCKCHAIN][RPC][REGISTRY] Premium RPC also unreachable for %s", chain.value)
    else:
        logger.debug("[BLOCKCHAIN][RPC][REGISTRY] No premium RPC configured for chain %s", chain.value)

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
    _resolved_web3_provider_cache[chain] = provider
    return provider


def resolve_async_web3_provider_for_chain(chain: BlockchainNetwork) -> AsyncWeb3:
    cached_provider = _resolved_async_web3_provider_cache.get(chain)
    if cached_provider is not None:
        return cached_provider

    rpc_url = resolve_rpc_url_for_chain(chain)
    provider = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
    _resolved_async_web3_provider_cache[chain] = provider
    return provider


def get_supported_evm_chains() -> list[BlockchainNetwork]:
    return [chain for chain in FREE_RPC_ENDPOINTS if chain != BlockchainNetwork.SOLANA]
