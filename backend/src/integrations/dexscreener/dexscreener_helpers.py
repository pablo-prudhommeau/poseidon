from __future__ import annotations

from typing import List, Dict, Iterable, Union, Optional, Tuple

import httpx

from src.core.structures.structures import Token
from src.integrations.dexscreener.dexscreener_client import HTTP_TIMEOUT_SECONDS
from src.integrations.dexscreener.dexscreener_constants import JSON, LATEST_TOKENS_ENDPOINT, LATEST_PAIRS_ENDPOINT
from src.integrations.dexscreener.dexscreener_structures import (
    DexscreenerPair,
    NormalizedRow,
)
from src.logging.logger import get_logger

log = get_logger(__name__)


def _split_into_chunks(tokens: List[Token], chunk_size: int) -> List[List[str]]:
    """
    Split a list into equally sized chunks (last chunk may be smaller).

    Args:
        tokens: The list of items to split.
        chunk_size: The desired chunk size; values <= 0 are coerced to 1.

    Returns:
        A list of chunks preserving the original order.
    """
    chunks: List[List[str]] = []
    for i in range(0, len(tokens), chunk_size):
        chunk = [token.tokenAddress for token in tokens[i: i + chunk_size]]
        chunks.append(chunk)
    return chunks

def _split_token_addressed_into_chunks(items: List[str], chunk_size: int) -> List[List[str]]:
    """
    Split a list into equally sized chunks (last chunk may be smaller).

    Args:
        items: The list of items to split.
        chunk_size: The desired chunk size; values <= 0 are coerced to 1.

    Returns:
        A list of chunks preserving the original order.
    """
    effective_size = max(1, int(chunk_size or 1))
    return [items[i: i + effective_size] for i in range(0, len(items), effective_size)]


def _merge_pair_maps(
        left: Dict[str, List[DexscreenerPair]],
        right: Dict[str, List[DexscreenerPair]],
) -> Dict[str, List[DexscreenerPair]]:
    """
    Merge two address->pairs mappings by concatenating lists.
    """
    merged: Dict[str, List[DexscreenerPair]] = {}
    for part in (left, right):
        for key, value in part.items():
            merged.setdefault(key, []).extend(value)
    return merged


def _deduplicate_preserving_order(values: Iterable[Token]) -> List[Token]:
    """
    Deduplicate tokens while preserving their first-seen order.
    """
    seen = set()
    deduped: List[Token] = []
    for token in values:
        identifier = (token.symbol, token.chain, token.tokenAddress, token.pairAddress)
        if identifier not in seen:
            seen.add(identifier)
            deduped.append(token)
    return deduped


def _deduplicate_token_addresses_preserving_order(values: Iterable[str]) -> List[str]:
    """
    Deduplicate string values while preserving their first-seen order.
    """
    seen: set[str] = set()
    unique: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


async def _http_get_json(client: httpx.AsyncClient, url: str) -> Union[Dict[str, JSON], List[JSON], None]:
    """
    Perform an HTTP GET request and parse the response as JSON.

    Returns:
        The decoded JSON document (object or array) or None if parsing fails.
    """
    response = await client.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        log.debug("[DEX][HTTP] JSON parse failed for URL '%s'.", url)
        return None


def _extract_addresses(payload: Union[Dict[str, JSON], List[JSON], None]) -> List[str]:
    """
    Extract potential token addresses from various Dexscreener payload shapes.
    Supports dicts and lists; gracefully ignores non-dict items.

    Returns:
        A list of addresses (possibly empty) discovered in the payload.
    """
    addresses: List[str] = []

    def _pull_from_item(item: Dict[str, JSON]) -> None:
        candidate = (item.get("tokenAddress") or item.get("address") or "")
        if not isinstance(candidate, str) or not candidate:
            base = item.get("baseToken") or item.get("token") or {}
            if isinstance(base, dict):
                base_address = base.get("address") or ""
                if isinstance(base_address, str):
                    candidate = base_address
        if isinstance(candidate, str):
            trimmed = candidate.strip()
            if trimmed:
                addresses.append(trimmed)

    if payload is None:
        return addresses

    if isinstance(payload, list):
        for element in payload:
            if isinstance(element, dict):
                _pull_from_item(element)
        return addresses

    if isinstance(payload, dict):
        for key in ("data", "tokens", "profiles", "pairs"):
            maybe_items = payload.get(key)
            if isinstance(maybe_items, list):
                for item in maybe_items:
                    if isinstance(item, dict):
                        _pull_from_item(item)
        return addresses

    return addresses


def _normalize_row_from_pair(pair: DexscreenerPair) -> NormalizedRow:
    """Flatten a DexscreenerPair into a strongly-typed NormalizedRow."""
    base = pair.base_token
    change = pair.price_change

    return NormalizedRow(
        name=(base.name or "").strip(),
        symbol=(base.symbol or "").strip().upper(),
        tokenAddress=pair.base_token.address,
        pairAddress=pair.pair_address,
        chain=pair.chain_id,
        priceUsd=pair.price_usd,
        priceNative=pair.price_native,
        pct5m=change.m5,
        pct1h=change.h1,
        pct24h=change.h24,
        vol24h=pair.volume.h24,
        liqUsd=pair.liquidity.usd,
        pairCreatedAt=pair.pair_created_at,
        txns=pair.txns,
        fdv=pair.fdv,
        marketCap=pair.market_cap,
    )


def _chunk_strings(items: List[str], size: int) -> List[List[str]]:
    """Split a list of strings into chunks of at most 'size' elements."""
    limit = max(1, int(size or 1))
    return [items[i: i + limit] for i in range(0, len(items), limit)]


async def _fetch_pairs_for_chain(
        client: httpx.AsyncClient,
        chain_id: str,
        pair_addresses: List[str],
) -> List[DexscreenerPair]:
    """
    Fetch Dexscreener pairs for a given chain and **pair address** list.
    """
    if not pair_addresses:
        return []

    url = f"{LATEST_PAIRS_ENDPOINT}/{chain_id}/{','.join(pair_addresses)}"
    payload = await _http_get_json(client, url)

    pairs: List[DexscreenerPair] = []
    if isinstance(payload, dict):
        raw_list = payload.get("pairs")
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, dict):
                    try:
                        pairs.append(DexscreenerPair.from_json(item))
                    except Exception:
                        continue
    return pairs


async def _fetch_pairs_batch_resilient(
        client: httpx.AsyncClient,
        batch_addresses: List[str],
) -> Dict[str, List[DexscreenerPair]]:
    """
    Fetch Dexscreener pairs for a batch of **base token addresses** with resilience.

    Dexscreener sometimes returns HTTP 200 with {"pairs": null}.
    For mixed batches, we split and retry to salvage partial results.
    """
    if not batch_addresses:
        return {}

    url = f"{LATEST_TOKENS_ENDPOINT}/{','.join(batch_addresses)}"
    try:
        payload = await _http_get_json(client, url)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in (400, 413, 414) and len(batch_addresses) > 1:
            log.debug("[DEX][FETCH] HTTP %d for batch size %d → splitting and retrying.", status, len(batch_addresses))
            mid = len(batch_addresses) // 2
            left = await _fetch_pairs_batch_resilient(client, batch_addresses[:mid])
            right = await _fetch_pairs_batch_resilient(client, batch_addresses[mid:])
            return _merge_pair_maps(left, right)
        log.warning("[DEX][FETCH] HTTP error %d for URL '%s'.", status, url)
        raise

    pairs_list: List[Dict[str, JSON]] = []
    if isinstance(payload, dict):
        pairs_value = payload.get("pairs")
        if pairs_value is None:
            if len(batch_addresses) > 1:
                log.debug("[DEX][FETCH] 'pairs' is null for batch size %d → splitting and retrying.",
                          len(batch_addresses))
                mid = len(batch_addresses) // 2
                left = await _fetch_pairs_batch_resilient(client, batch_addresses[:mid])
                right = await _fetch_pairs_batch_resilient(client, batch_addresses[mid:])
                return _merge_pair_maps(left, right)
            log.debug("[DEX][FETCH] 'pairs' is null for address '%s' (no result).", batch_addresses[0])
            return {}
        if isinstance(pairs_value, list):
            pairs_list = [p for p in pairs_value if isinstance(p, dict)]

    by_address: Dict[str, List[DexscreenerPair]] = {}
    for pair_payload in pairs_list:
        model = DexscreenerPair.from_json(pair_payload)
        address = model.base_token.address
        if not address:
            continue
        by_address.setdefault(address, []).append(model)
    return by_address


def _select_best_pair(pairs: List[DexscreenerPair]) -> Optional[DexscreenerPair]:
    """
    Select the 'best' pair using (liquidity.usd, volume.h24) as a score.
    Used **only** by fetch_trending_candidates (per product policy).
    """
    if not pairs:
        return None

    def score(item: DexscreenerPair) -> Tuple[float, float]:
        return item.liquidity.usd, item.volume.h24

    return sorted(pairs, key=score, reverse=True)[0]
