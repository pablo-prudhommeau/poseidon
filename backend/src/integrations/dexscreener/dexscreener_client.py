from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Optional, Tuple

import httpx

from src.integrations.dexscreener.dexscreener_constants import (
    LATEST_TOKENS_ENDPOINT,
    TOTAL_ADDRESS_HARD_CAP,
    HTTP_TIMEOUT_SECONDS,
    DEFAULT_MAX_ADDRESSES_PER_CALL,
    TOKEN_BOOSTS_LATEST_ENDPOINT,
    TOKEN_BOOSTS_TOP_ENDPOINT,
    TOKEN_PROFILES_ENDPOINT, JSON,
)
from src.integrations.dexscreener.dexscreener_helpers import (
    _http_get_json,
    _merge_pair_maps,
    _deduplicate_preserving_order,
    _split_into_chunks,
    _extract_addresses,
    _normalize_row_from_pair,
)
from src.integrations.dexscreener.dexscreener_structures import DexscreenerPair, NormalizedRow
from src.logging.logger import get_logger

log = get_logger(__name__)


async def _fetch_pairs_batch_resilient(
        client: httpx.AsyncClient,
        batch: List[str],
) -> Dict[str, List[DexscreenerPair]]:
    """
    Fetch Dexscreener pairs for a batch of base-token addresses with resilience.

    The API sometimes returns HTTP 200 with a body containing {"pairs": null}.
    If that happens for a mixed batch, we split and retry to salvage partial results.
    If the batch contains a single address, we return an empty mapping.

    Args:
        client: The shared AsyncClient.
        batch: Addresses to query as a single batch.

    Returns:
        Mapping of base-token address -> list of strongly-typed pair objects.
    """
    url = f"{LATEST_TOKENS_ENDPOINT}/{','.join(batch)}"
    try:
        payload = await _http_get_json(client, url)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in (400, 413, 414) and len(batch) > 1:
            log.debug("[DEX][FETCH] HTTP %d for batch size %d → splitting and retrying.", status, len(batch))
            midpoint = len(batch) // 2
            left = await _fetch_pairs_batch_resilient(client, batch[:midpoint])
            right = await _fetch_pairs_batch_resilient(client, batch[midpoint:])
            return _merge_pair_maps(left, right)
        log.warning("[DEX][FETCH] HTTP error %d for URL '%s'.", status, url)
        raise

    pairs_list: List[Dict[str, JSON]] = []
    if isinstance(payload, dict):
        pairs_value = payload.get("pairs")
        if pairs_value is None:
            if len(batch) > 1:
                log.debug("[DEX][FETCH] 'pairs' is null for batch size %d → splitting and retrying.", len(batch))
                midpoint = len(batch) // 2
                left = await _fetch_pairs_batch_resilient(client, batch[:midpoint])
                right = await _fetch_pairs_batch_resilient(client, batch[midpoint:])
                return _merge_pair_maps(left, right)
            log.debug("[DEX][FETCH] 'pairs' is null for address '%s' (no result).", batch[0])
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
    Pick the most liquid/highest 24h volume pair as 'best'.

    Returns:
        The selected pair, or None if the input list is empty.
    """
    if not pairs:
        return None

    def pair_score(item: DexscreenerPair) -> Tuple[float, float]:
        return item.liquidity.usd, item.volume.h24

    return sorted(pairs, key=pair_score, reverse=True)[0]


async def fetch_pairs_by_addresses(addresses: Iterable[str]) -> Dict[str, List[DexscreenerPair]]:
    """
    Fetch raw pairs for a list of addresses (best-effort).

    Returns:
        Mapping of address -> list of pairs.
    """
    input_list_raw = list(addresses or [])
    if not input_list_raw:
        log.debug("[DEX][FETCH] called with an empty address list.")
        return {}

    input_list_unique = _deduplicate_preserving_order(input_list_raw)
    if len(input_list_unique) > TOTAL_ADDRESS_HARD_CAP:
        log.info("[DEX][FETCH] Capping address list from %d to hard cap %d.", len(input_list_unique), TOTAL_ADDRESS_HARD_CAP)
        input_list_unique = input_list_unique[:TOTAL_ADDRESS_HARD_CAP]

    result: Dict[str, List[DexscreenerPair]] = {addr: [] for addr in input_list_unique}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for batch in _split_into_chunks(input_list_unique, DEFAULT_MAX_ADDRESSES_PER_CALL):
            log.debug("[DEX][FETCH] fetching pairs for batch size %d.", len(batch))
            by_address = await _fetch_pairs_batch_resilient(client, batch)
            for addr, pairs in by_address.items():
                result[addr] = pairs
            await asyncio.sleep(0)
    return result


async def fetch_prices_by_token_addresses(tokenAddresses: Iterable[str]) -> Dict[str, float]:
    """
    Fetch the best price (USD) per address using Dexscreener pairs.

    Returns:
        Mapping of address -> price_usd.
    """
    input_list_raw = list(tokenAddresses or [])
    if not input_list_raw:
        log.debug("[DEX][PRICE] called with an empty address list.")
        return {}

    input_list_unique = _deduplicate_preserving_order(input_list_raw)
    if len(input_list_unique) > TOTAL_ADDRESS_HARD_CAP:
        log.info("[DEX][PRICE] Capping address list from %d to hard cap %d.", len(input_list_unique), TOTAL_ADDRESS_HARD_CAP)
        input_list_unique = input_list_unique[:TOTAL_ADDRESS_HARD_CAP]

    prices_by_address: Dict[str, float] = {}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for batch in _split_into_chunks(input_list_unique, DEFAULT_MAX_ADDRESSES_PER_CALL):
            log.debug("[DEX][PRICE] fetching prices for batch size %d.", len(batch))
            by_address = await _fetch_pairs_batch_resilient(client, batch)
            for addr, pairs in by_address.items():
                best = _select_best_pair(pairs)
                if best and best.price_usd is not None and best.price_usd > 0.0:
                    prices_by_address[addr] = best.price_usd
                else:
                    log.debug("[DEX][PRICE] price unavailable or not positive for '%s'.", addr)
            await asyncio.sleep(0)
    return prices_by_address


def fetch_prices_by_token_addresses_sync(addresses: List[str]) -> Dict[str, float]:
    """
    Synchronous wrapper around `fetch_prices_by_addresses`.

    Behavior:
    - If no event loop is running in the current thread: run the coroutine directly.
    - If an event loop IS running in the current thread: offload to a dedicated
      worker thread and run the coroutine there to avoid nested-loop RuntimeError.

    This makes the function safe for use from both sync services and async servers.
    """
    if not addresses:
        log.debug("[DEX][PRICE] sync fetch called with an empty address list.")
        return {}

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        from concurrent.futures import ThreadPoolExecutor

        def runner() -> Dict[str, float]:
            return asyncio.run(fetch_prices_by_token_addresses(addresses))

        log.debug("[DEX][PRICE] running synchronous price fetch in a worker thread.")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(runner)
            return future.result()

    log.debug("[DEX][PRICE] running synchronous price fetch in a new event loop.")
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result: Dict[str, float] = loop.run_until_complete(fetch_prices_by_token_addresses(addresses))
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


async def fetch_trending_candidates(page_size: int = 100) -> List[NormalizedRow]:
    """
    Aggregate trending candidates from multiple Dexscreener sources.

    Returns:
        A list of normalized rows sorted by (24h volume, liquidity) descending,
        limited to `page_size`.
    """
    log.info("[DEX][TREND] collecting trending candidates from public endpoints.")

    collected_addresses: List[str] = []
    endpoints = (
        TOKEN_BOOSTS_LATEST_ENDPOINT,
        TOKEN_BOOSTS_TOP_ENDPOINT,
        TOKEN_PROFILES_ENDPOINT,
    )

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for url in endpoints:
            try:
                payload = await _http_get_json(client, url)
                extracted = _extract_addresses(payload if isinstance(payload, (dict, list)) else None)
                collected_addresses.extend(extracted)
                payload_size = len(payload) if isinstance(payload, list) else len(payload or {})
                log.debug(
                    "[DEX][TREND] fetched '%s' → payload_items=%s, extracted_addresses=%s.",
                    url.rsplit("/", 2)[-2:],
                    payload_size,
                    len(extracted),
                )
            except httpx.HTTPError as error:
                log.warning("[DEX][TREND] read failed for '%s' (%s).", url, error)

    if not collected_addresses:
        log.info("[DEX][TREND] no addresses collected from trending sources.")
        return []

    pairs_map = await fetch_pairs_by_addresses(collected_addresses)
    if not any(pairs_map.values()):
        log.info("[DEX][TREND] pairs empty for collected addresses.")
        return []

    rows: List[NormalizedRow] = []
    for address, pairs in pairs_map.items():
        best = _select_best_pair(pairs)
        if best is None:
            continue
        rows.append(_normalize_row_from_pair(best))

    rows.sort(key=lambda r: (r.vol24h, r.liqUsd), reverse=True)
    limited = rows[: max(1, int(page_size or 1))]
    log.info("[DEX][TREND] returning %d trending candidates.", len(limited))
    return limited
