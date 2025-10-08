from __future__ import annotations

from typing import List, Dict, Iterable, Union

import httpx

from src.integrations.dexscreener.dexscreener_client import HTTP_TIMEOUT_SECONDS
from src.integrations.dexscreener.dexscreener_constants import JSON
from src.integrations.dexscreener.dexscreener_structures import (
    DexscreenerPair,
    NormalizedRow,
)
from src.logging.logger import get_logger

log = get_logger(__name__)


def _split_into_chunks(items: List[str], chunk_size: int) -> List[List[str]]:
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


def _deduplicate_preserving_order(values: Iterable[str]) -> List[str]:
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
