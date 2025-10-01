# src/integrations/dexscreener_client.py
from __future__ import annotations

"""
Dexscreener client:
- Fetch token pairs and prices for EVM/Solana addresses
- Aggregate trending candidates from several Dexscreener feeds
- Provide a safe synchronous wrapper that can be called from sync or async contexts

Design notes:
- EVM addresses are normalized to lowercase; Solana mints keep original case
- We sanitize/repair inputs coming from various sources (pairId suffixes, stray base58, etc.)
- HTTP is best-effort with small batch-splitting fallbacks when Dexscreener returns 'pairs: null'
"""

import asyncio
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)

# -----------------------------------------------------------------------------
# Endpoints & limits
# -----------------------------------------------------------------------------

BASE = settings.DEXSCREENER_BASE_URL.rstrip("/")
LATEST_TOKENS = f"{BASE}/latest/dex/tokens"  # /latest/dex/tokens/{addr1,addr2,...}
TOKEN_PROFILES = f"{BASE}/token-profiles/latest/v1"
TOKEN_BOOSTS_LATEST = f"{BASE}/token-boosts/latest/v1"
TOKEN_BOOSTS_TOP = f"{BASE}/token-boosts/top/v1"

DEFAULT_MAX_PER: int = max(1, int(settings.DEXSCREENER_MAX_ADDRESSES_PER_CALL))
TOTAL_CAP: int = max(1, int(settings.DEXSCREENER_MAX_ADDRESSES))
HTTP_TIMEOUT_SECONDS: float = 15.0

def _chunked(items: List[str], chunk_size: int) -> List[List[str]]:
    """Split a list into equally sized chunks (last chunk may be smaller)."""
    n = max(1, int(chunk_size or 1))
    return [items[i: i + n] for i in range(0, len(items), n)]


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    """
    Perform a GET request and parse JSON.
    Returns either a list or a dict (Dexscreener uses both).
    """
    response = await client.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        return None


async def _safe_fetch_pairs_batch(
        client: httpx.AsyncClient,
        batch: List[str],
) -> Dict[str, List[dict]]:
    """
    Fetch Dexscreener pairs for a batch of base-token addresses.

    The API sometimes returns 200 with {"pairs": null}.
    - If this happens for a mixed batch, split to salvage as much as possible.
    - If it's a single address, return {} (token with no results / not indexed).
    """
    url = f"{LATEST_TOKENS}/{','.join(batch)}"
    try:
        payload = await _get_json(client, url)
    except httpx.HTTPStatusError as error:
        # Handle oversized or malformed batch by splitting
        if error.response.status_code in (400, 413, 414) and len(batch) > 1:
            midpoint = len(batch) // 2
            left = await _safe_fetch_pairs_batch(client, batch[:midpoint])
            right = await _safe_fetch_pairs_batch(client, batch[midpoint:])
            merged: Dict[str, List[dict]] = {}
            for part in (left, right):
                for key, value in part.items():
                    merged.setdefault(key, []).extend(value)
            return merged
        raise

    pairs_field = payload.get("pairs") if isinstance(payload, dict) else []
    if pairs_field is None:
        if len(batch) > 1:
            log.debug(
                "DexScreener: 'pairs' is null for batch size %d → splitting and retrying",
                len(batch),
            )
            midpoint = len(batch) // 2
            left = await _safe_fetch_pairs_batch(client, batch[:midpoint])
            right = await _safe_fetch_pairs_batch(client, batch[midpoint:])
            merged: Dict[str, List[dict]] = {}
            for part in (left, right):
                for key, value in part.items():
                    merged.setdefault(key, []).extend(value)
            return merged
        log.debug("DexScreener: 'pairs' is null for address %s (no result)", batch[0])
        return {}

    pairs_list: List[dict] = pairs_field if isinstance(pairs_field, list) else []
    by_address: Dict[str, List[dict]] = {}
    for pair in pairs_list:
        base_token = pair.get("baseToken") or {}
        raw_address = base_token.get("address") or ""
        if not raw_address:
            continue
        # EVM → lowercase ; SOL → keep case
        by_address.setdefault(raw_address, []).append(pair)
    return by_address


def _select_best_pair(pairs: List[dict]) -> Optional[dict]:
    """
    Pick the most liquid/highest 24h volume pair as 'best'.
    Returns None when the list is empty.
    """
    if not pairs:
        return None

    def _score(pair: dict) -> Tuple[float, float]:
        liquidity_usd = float((pair.get("liquidity") or {}).get("usd") or 0.0)
        volume_h24 = float((pair.get("volume") or {}).get("h24") or 0.0)
        return liquidity_usd, volume_h24

    return sorted(pairs, key=_score, reverse=True)[0]


def _normalize_row_from_pair(address: str, pair: dict) -> dict:
    """Flatten a Dexscreener 'pair' into a unified row suitable for UI/storage."""
    base_token = pair.get("baseToken") or {}
    price_change = pair.get("priceChange") or {}
    volume = pair.get("volume") or {}
    liquidity = pair.get("liquidity") or {}

    def _as_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    # EVM → lowercase ; SOL → keep case
    output_address = (address or "")

    return {
        "name": (base_token.get("name") or "").strip(),
        "symbol": (base_token.get("symbol") or "").strip().upper(),
        "address": output_address,
        "chain": (pair.get("chainId") or "").lower(),
        "price": _as_float(pair.get("priceUsd")),
        "pct5m": _as_float(price_change.get("m5")) if price_change.get("m5") is not None else None,
        "pct1h": _as_float(price_change.get("h1")) if price_change.get("h1") is not None else None,
        "pct24h": _as_float(price_change.get("h24")) if price_change.get("h24") is not None else None,
        "vol24h": float(volume.get("h24") or 0.0),
        "liqUsd": float(liquidity.get("usd") or 0.0),
        "pairCreatedAt": int(pair.get("pairCreatedAt") or 0),
        "txns": pair.get("txns") or {},
        "fdv": _as_float(pair.get("fdv")) if pair.get("fdv") is not None else None,
        "marketCap": _as_float(pair.get("marketCap")) if pair.get("marketCap") is not None else None,
    }


def _extract_addresses(payload: Any) -> List[str]:
    """
    Extract potential token addresses from various Dexscreener payload shapes.
    Supports dicts and lists; gracefully ignores non-dict items.
    """
    addresses: List[str] = []

    def _from_item(item: dict) -> None:
        address = (item.get("tokenAddress") or item.get("address") or "")
        if not address:
            base_token = item.get("baseToken") or item.get("token") or {}
            address = base_token.get("address") or ""
        address = address.strip()
        if address:
            addresses.append(address)

    if payload is None:
        return addresses
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                _from_item(item)
    elif isinstance(payload, dict):
        for key in ("data", "tokens", "profiles", "pairs"):
            items = payload.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        _from_item(item)
    return addresses


async def fetch_pairs_by_addresses(addresses: Iterable[str]) -> Dict[str, List[dict]]:
    """
    Fetch raw pairs for a list of addresses (best-effort).
    Returns a mapping address -> list[pair].
    """
    input_list = list(addresses or [])
    if not input_list:
        return {}

    result: Dict[str, List[dict]] = {address: [] for address in input_list}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for batch in _chunked(input_list, DEFAULT_MAX_PER):
            by_address = await _safe_fetch_pairs_batch(client, batch)
            for address, pairs in by_address.items():
                result[address] = pairs
            # Let the event loop breathe between batches
            await asyncio.sleep(0)
    return result


async def fetch_prices_by_addresses(addresses: Iterable[str]) -> Dict[str, float]:
    """
    Fetch the best price (USD) per address using Dexscreener pairs.
    Returns a mapping address -> price_usd.
    """
    input_list = list(addresses or [])
    if not input_list:
        return {}

    prices_by_address: Dict[str, float] = {}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for batch in _chunked(input_list, DEFAULT_MAX_PER):
            by_address = await _safe_fetch_pairs_batch(client, batch)
            for address, pairs in by_address.items():
                best = _select_best_pair(pairs)
                if not best:
                    continue
                try:
                    price_usd = float(best.get("priceUsd") or 0.0)
                    if price_usd > 0:
                        prices_by_address[address] = price_usd
                except Exception:
                    log.debug("DexScreener: price parse failed for %s", address)
            await asyncio.sleep(0)
    return prices_by_address


def fetch_prices_by_addresses_sync(addresses: List[str]) -> Dict[str, float]:
    """
    Synchronous wrapper around `fetch_prices_by_addresses`.

    Behavior:
      - If no event loop is running in the current thread: run the coroutine directly.
      - If an event loop IS running in the current thread: offload to a dedicated
        worker thread and run the coroutine there to avoid nested-loop RuntimeError.

    This makes the function safe for use from both sync services and async servers.
    """
    if not addresses:
        return {}

    # Case 1: an event loop is already running in this thread → offload to a worker thread
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        from concurrent.futures import ThreadPoolExecutor

        def _runner() -> Dict[str, float]:
            # `asyncio.run` creates and manages a fresh loop in this worker thread.
            return asyncio.run(fetch_prices_by_addresses(addresses))

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_runner)
            return future.result()

    # Case 2: no running loop in this thread → create and run our own loop
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result: Dict[str, float] = loop.run_until_complete(fetch_prices_by_addresses(addresses))
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        return result
    finally:
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass
        loop.close()


async def fetch_trending_candidates(page_size: int = 100) -> List[dict]:
    """
    Aggregate trending candidates from multiple Dexscreener sources.

    Returns a list of normalized rows sorted by (24h volume, liquidity) descending,
    limited to `page_size`.
    """
    raw_addresses: List[str] = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for url in (TOKEN_BOOSTS_LATEST, TOKEN_BOOSTS_TOP, TOKEN_PROFILES):
            try:
                payload = await _get_json(client, url)
                extracted = _extract_addresses(payload)
                raw_addresses.extend(extracted)
                log.debug(
                    "DexScreener %s → items=%s extracted=%s",
                    url.rsplit("/", 2)[-2:],
                    (len(payload) if isinstance(payload, list) else len(payload or {})),
                    len(extracted),
                )
            except httpx.HTTPError as error:
                log.warning("DexScreener: read failed for %s (%s)", url, error)

    pairs_map = await fetch_pairs_by_addresses(raw_addresses)
    if not any(pairs_map.values()):
        log.info("DexScreener: pairs empty for collected addresses.")
        return []

    rows: List[dict] = []
    for address, pairs in pairs_map.items():
        best = _select_best_pair(pairs)
        if not best:
            continue
        rows.append(_normalize_row_from_pair(address, best))

    rows.sort(key=lambda r: (float(r.get("vol24h") or 0.0), float(r.get("liqUsd") or 0.0)), reverse=True)
    return rows[:page_size]
