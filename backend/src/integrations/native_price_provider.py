from __future__ import annotations

"""
Native price provider for chain base assets (e.g., SOL, ETH, BNB) in USD.

Goals:
- Provide a simple `get_native_price_usd(chain_key)` that returns a Decimal price.
- Try multiple public sources with short timeouts.
- Cache results briefly to avoid hammering endpoints.

Currently implemented sources:
- CoinGecko (robust public API): /simple/price?ids=solana&vs_currencies=usd

Design:
- We normalize Dexscreener `chain` keys first.
- We maintain an in-memory TTL cache (per-chain).
"""

from decimal import Decimal
from typing import Dict, Optional, Tuple
import time
import httpx

from src.logging.logger import get_logger

log = get_logger(__name__)

# ------------------------- Normalization & mapping -------------------------

def _normalize_chain_key(raw: str | None) -> str:
    if not raw:
        return ""
    key = raw.strip().lower()
    aliases = {
        "eth": "ethereum",
        "ethereum-mainnet": "ethereum",
        "arb": "arbitrum",
        "arbitrum-one": "arbitrum",
        "op": "optimism",
        "optimism-mainnet": "optimism",
        "bsc-mainnet": "bsc",
        "binance-smart-chain": "bsc",
        "binance": "bsc",
        "matic": "polygon",
        "polygon-pos": "polygon",
        "polygon-mainnet": "polygon",
        "avax": "avalanche",
        "avalanche-c": "avalanche",
        "xdai": "gnosis",
        "zk-sync": "zksync",
        "zk-sync-era": "zksync",
        "zksync-era": "zksync",
        "polygonzkevm": "polygon-zkevm",
        "polygon-zk-evm": "polygon-zkevm",
    }
    return aliases.get(key, key)

# Map normalized chain key -> CoinGecko id for the native coin
_COINGECKO_IDS: Dict[str, str] = {
    "solana": "solana",
    "ethereum": "ethereum",
    "base": "base",
    "optimism": "optimism",
    "arbitrum": "arbitrum",
    "bsc": "binancecoin",
    "polygon": "matic-network",
    "avalanche": "avalanche-2",
    "fantom": "fantom",
    "cronos": "crypto-com-chain",
    "gnosis": "xdai",
    "celo": "celo",
    "metis": "metis-token",
    "mantle": "mantle",
    "kava": "kava",
    "moonbeam": "moonbeam",
    "moonriver": "moonriver",
    "linea": "ethereum",          # L2 ETH
    "scroll": "ethereum",         # L2 ETH
    "blast": "ethereum",          # L2 ETH
    "zksync": "ethereum",         # L2 ETH
    "polygon-zkevm": "ethereum",  # L2 ETH
}

# ------------------------- Tiny TTL cache -------------------------

# cache: chain_key -> (price_usd, expires_at_epoch_seconds)
_CACHE: Dict[str, Tuple[Decimal, float]] = {}

def _cache_get(chain_key: str) -> Optional[Decimal]:
    now = time.time()
    entry = _CACHE.get(chain_key)
    if not entry:
        return None
    price, expires = entry
    if now >= expires:
        _CACHE.pop(chain_key, None)
        return None
    return price

def _cache_set(chain_key: str, price: Decimal, ttl_seconds: int = 15) -> None:
    _CACHE[chain_key] = (price, time.time() + ttl_seconds)

# ------------------------- HTTP helpers -------------------------

def _http_get_json(url: str, params: Dict[str, str]) -> Dict:
    timeout = httpx.Timeout(8.0, connect=4.0)
    headers = {"Accept": "application/json", "User-Agent": "poseidon-price-provider/1.0"}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

# ------------------------- Providers -------------------------

def _coingecko_price_usd_by_id(coingecko_id: str) -> Optional[Decimal]:
    try:
        data = _http_get_json(
            "https://api.coingecko.com/api/v3/simple/price",
            {"ids": coingecko_id, "vs_currencies": "usd"},
        )
        node = data.get(coingecko_id) or {}
        usd = node.get("usd")
        if usd is None:
            return None
        price = Decimal(str(usd))
        if price > 0:
            return price
        return None
    except Exception as exc:
        log.debug("NativePrice: CoinGecko fetch failed for %s: %s", coingecko_id, exc)
        return None

# ------------------------- Public API -------------------------

def get_native_price_usd(chain_key_raw: str) -> Optional[Decimal]:
    """
    Return the USD price of the chain's native asset (e.g. SOL for 'solana').
    Uses short TTL cache and public providers with fallbacks.
    """
    chain_key = _normalize_chain_key(chain_key_raw)
    if not chain_key:
        return None

    # cache
    cached = _cache_get(chain_key)
    if cached is not None:
        return cached

    coingecko_id = _COINGECKO_IDS.get(chain_key)
    if not coingecko_id:
        log.debug("NativePrice: no mapping to CoinGecko id for chain '%s'", chain_key)
        return None

    price = _coingecko_price_usd_by_id(coingecko_id)
    if price is not None:
        _cache_set(chain_key, price, ttl_seconds=15)
        log.debug("NativePrice: %s USD=%.6f (CoinGecko)", chain_key, price)
        return price

    # No other provider succeeded
    return None
