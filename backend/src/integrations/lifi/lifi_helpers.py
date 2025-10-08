from typing import Dict, Mapping, cast

import httpx

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)


def _build_lifi_headers() -> Dict[str, str]:
    """
    Construct LI.FI HTTP headers, optionally including an API key if configured.
    """
    headers: Dict[str, str] = {}
    api_key = getattr(settings, "LIFI_API_KEY", None)
    if isinstance(api_key, str) and api_key.strip():
        headers["x-lifi-api-key"] = api_key.strip()
    return headers


def _http_get_json(url: str, params: Mapping[str, object]) -> Dict[str, object]:
    """
    Perform a GET request with sane timeouts and return parsed JSON.

    Raises:
        httpx.HTTPStatusError on non-2xx responses.
        httpx.RequestError on connection/timeout errors.
    """
    timeout = httpx.Timeout(12.0, connect=6.0)
    try:
        with httpx.Client(timeout=timeout, headers=_build_lifi_headers()) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            return cast(Dict[str, object], payload)
    except httpx.HTTPStatusError as exc:
        log.warning(
            "LI.FI GET fails: url=%s status=%s body=%s",
            url,
            exc.response.status_code if exc.response is not None else "n/a",
            exc.response.text if exc.response is not None else "n/a",
        )
        raise
    except httpx.RequestError as exc:
        log.warning("LI.FI GET request error: url=%s error=%s", url, str(exc))
        raise


def _normalize_chain_key(raw_chain_key: str | None) -> str:
    """
    Normalize incoming chain keys from Dexscreener for robust lookups.

    Returns:
        A lowercase canonical registry key, or empty string if input is falsy.
    """
    if not raw_chain_key:
        return ""
    lowered = raw_chain_key.strip().lower()

    if lowered in {"eth", "ethereum-mainnet"}:
        return "ethereum"
    if lowered in {"arb", "arbitrum-one"}:
        return "arbitrum"
    if lowered in {"op", "optimism-mainnet"}:
        return "optimism"
    if lowered in {"bsc-mainnet", "binance-smart-chain", "binance"}:
        return "bsc"
    if lowered in {"matic", "polygon-pos", "polygon-mainnet"}:
        return "polygon"
    if lowered in {"avax", "avalanche-c"}:
        return "avalanche"
    if lowered in {"xdai"}:
        return "gnosis"
    if lowered in {"zk-sync", "zk-sync-era", "zksync-era"}:
        return "zksync"
    if lowered in {"polygonzkevm", "polygon-zk-evm"}:
        return "polygon-zkevm"
    return lowered
