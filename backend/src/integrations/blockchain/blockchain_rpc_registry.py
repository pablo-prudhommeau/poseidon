from __future__ import annotations

from typing import Optional

from web3 import AsyncWeb3, Web3

from src.configuration.config import settings
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

FREE_RPC_ENDPOINTS: dict[str, list[str]] = {
    "solana": [
        "https://api.mainnet-beta.solana.com",
    ],
    "bsc": [
        "https://bsc-dataseed.binance.org/",
        "https://bsc-dataseed1.defibit.io/",
    ],
    "base": [
        "https://base.gateway.tenderly.co",
        "https://1rpc.io/base",
        "https://mainnet.base.org",
    ],
    "ethereum": [
        "https://eth.llamarpc.com",
        "https://rpc.ankr.com/eth",
    ],
    "avalanche": [
        "https://api.avax.network/ext/bc/C/rpc",
        "https://rpc.ankr.com/avalanche",
    ],
}

PREMIUM_RPC_SETTING_BY_CHAIN: dict[str, str] = {
    "solana": "SOLANA_RPC_PREMIUM_URL",
    "bsc": "BSC_RPC_PREMIUM_URL",
    "base": "BASE_RPC_PREMIUM_URL",
    "ethereum": "ETHEREUM_RPC_PREMIUM_URL",
    "avalanche": "AVALANCHE_RPC_PREMIUM_URL",
}

_resolved_web3_provider_cache: dict[str, Web3] = {}
_resolved_async_web3_provider_cache: dict[str, AsyncWeb3] = {}
_resolved_rpc_url_cache: dict[str, str] = {}


def _get_premium_rpc_url(chain_identifier: str) -> str:
    setting_name = PREMIUM_RPC_SETTING_BY_CHAIN.get(chain_identifier, "")
    if not setting_name:
        return ""
    return getattr(settings, setting_name, "")


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
            json={"jsonrpc": "2.0", "id": 1, "method": "getSlot"},
            timeout=5,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 429:
            logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Solana RPC rate-limited (HTTP 429) at %s", rpc_url)
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
        return isinstance(result_value, int) and result_value > 0
    except Exception:
        return False


def _is_solana_chain(chain_identifier: str) -> bool:
    return chain_identifier in {"solana", "sol"}


def resolve_rpc_url_for_chain(chain_identifier: str) -> str:
    normalized_chain = chain_identifier.lower()
    if normalized_chain == "sol":
        normalized_chain = "solana"

    cached_url = _resolved_rpc_url_cache.get(normalized_chain)
    if cached_url is not None:
        return cached_url

    free_endpoints = FREE_RPC_ENDPOINTS.get(normalized_chain, [])
    is_solana = _is_solana_chain(normalized_chain)

    for free_rpc_url in free_endpoints:
        logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Testing free RPC for %s at %s", normalized_chain, free_rpc_url)
        connectivity_test_passed = (
            _test_solana_rpc_connectivity(free_rpc_url) if is_solana
            else _test_evm_rpc_connectivity(free_rpc_url)
        )
        if connectivity_test_passed:
            logger.info("[BLOCKCHAIN][RPC][REGISTRY] Connected to free RPC for %s at %s", normalized_chain, free_rpc_url)
            _resolved_rpc_url_cache[normalized_chain] = free_rpc_url
            return free_rpc_url
        logger.warning("[BLOCKCHAIN][RPC][REGISTRY] Free RPC unreachable for %s at %s", normalized_chain, free_rpc_url)

    premium_rpc_url = _get_premium_rpc_url(normalized_chain)
    if premium_rpc_url:
        logger.debug("[BLOCKCHAIN][RPC][REGISTRY] Testing premium RPC for %s", normalized_chain)
        connectivity_test_passed = (
            _test_solana_rpc_connectivity(premium_rpc_url) if is_solana
            else _test_evm_rpc_connectivity(premium_rpc_url)
        )
        if connectivity_test_passed:
            logger.info("[BLOCKCHAIN][RPC][REGISTRY] Connected to premium RPC for %s", normalized_chain)
            _resolved_rpc_url_cache[normalized_chain] = premium_rpc_url
            return premium_rpc_url
        logger.warning("[BLOCKCHAIN][RPC][REGISTRY] Premium RPC also unreachable for %s", normalized_chain)

    raise ConnectionError(f"[BLOCKCHAIN][RPC][REGISTRY] No reachable RPC endpoint found for chain {normalized_chain}")


def resolve_web3_provider_for_chain(chain_identifier: str) -> Optional[Web3]:
    normalized_chain = chain_identifier.lower()
    if normalized_chain == "sol":
        normalized_chain = "solana"

    cached_provider = _resolved_web3_provider_cache.get(normalized_chain)
    if cached_provider is not None:
        return cached_provider

    try:
        rpc_url = resolve_rpc_url_for_chain(normalized_chain)
    except ConnectionError:
        logger.warning("[BLOCKCHAIN][RPC][REGISTRY] Cannot resolve any RPC for chain %s", normalized_chain)
        return None

    provider = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
    _resolved_web3_provider_cache[normalized_chain] = provider
    return provider


def resolve_async_web3_provider_for_chain(chain_identifier: str) -> AsyncWeb3:
    normalized_chain = chain_identifier.lower()
    if normalized_chain == "sol":
        normalized_chain = "solana"

    cached_provider = _resolved_async_web3_provider_cache.get(normalized_chain)
    if cached_provider is not None:
        return cached_provider

    rpc_url = resolve_rpc_url_for_chain(normalized_chain)
    provider = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
    _resolved_async_web3_provider_cache[normalized_chain] = provider
    return provider


def get_supported_evm_chains() -> list[str]:
    return [chain for chain in FREE_RPC_ENDPOINTS if chain != "solana"]
