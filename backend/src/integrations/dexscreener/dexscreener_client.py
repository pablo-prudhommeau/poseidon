from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Optional

import httpx

from src.core.structures.structures import Token
from src.integrations.dexscreener.dexscreener_constants import (
    LATEST_PAIRS_ENDPOINT,
    TOTAL_ADDRESS_HARD_CAP,
    HTTP_TIMEOUT_SECONDS,
    DEFAULT_MAX_ADDRESSES_PER_CALL,
    TOKEN_BOOSTS_LATEST_ENDPOINT,
    TOKEN_BOOSTS_TOP_ENDPOINT,
    TOKEN_PROFILES_ENDPOINT,
)
from src.integrations.dexscreener.dexscreener_helpers import (
    _http_get_json,
    _deduplicate_preserving_order,
    _extract_addresses,
    _fetch_token_information_list,
    _chunk_strings,
    _fetch_token_information_for_chain,
    _select_best_pair,
    _deduplicate_token_addresses_preserving_order,
    _split_token_addressed_into_chunks,
)
from src.integrations.dexscreener.dexscreener_structures import (
    DexscreenerTokenInformation,
)
from src.logging.logger import get_logger

log = get_logger(__name__)

_shared_async_client: Optional[httpx.AsyncClient] = None


def _get_shared_client() -> httpx.AsyncClient:
    """
    Returns a shared httpx.AsyncClient instance.
    Lazy initialization ensures the client is created within the running event loop.
    """
    global _shared_async_client
    if _shared_async_client is None or _shared_async_client.is_closed:
        log.debug("[DEX][CLIENT] Initializing shared HTTP client.")
        _shared_async_client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
    return _shared_async_client


async def fetch_dexscreener_token_information_list(tokens: Iterable[Token]) -> List[DexscreenerTokenInformation]:
    tokens_list: List[Token] = list(tokens or [])
    if not tokens_list:
        log.debug("[DEX][PAIR][PRICE] Called with an empty token list.")
        return []

    unique_tokens: List[Token] = _deduplicate_preserving_order(tokens_list)
    if len(unique_tokens) > TOTAL_ADDRESS_HARD_CAP:
        log.info(
            "[DEX][TOKEN][INFORMATION] Capping token list from %d to hard cap %d.",
            len(unique_tokens),
            TOTAL_ADDRESS_HARD_CAP,
        )
        unique_tokens = unique_tokens[:TOTAL_ADDRESS_HARD_CAP]

    tokens_by_chain: Dict[str, List[Token]] = {}
    for token in unique_tokens:
        if not token.chain or not token.pairAddress:
            log.debug("[DEX][TOKEN][INFORMATION] Skipping token without chain/pair: %s", str(token))
            continue
        tokens_by_chain.setdefault(token.chain, []).append(token)

    token_information_list: List[DexscreenerTokenInformation] = []
    client = _get_shared_client()
    for chain_id, chain_tokens in tokens_by_chain.items():
        if not chain_tokens:
            continue

        seen_pair_addresses: set[str] = set()
        pair_addresses: List[str] = []
        for token in chain_tokens:
            if token.pairAddress not in seen_pair_addresses:
                seen_pair_addresses.add(token.pairAddress)
                pair_addresses.append(token.pairAddress)

        for batch in _chunk_strings(pair_addresses, DEFAULT_MAX_ADDRESSES_PER_CALL):
            try:
                token_information_list_fetched: List[DexscreenerTokenInformation] = \
                    await _fetch_token_information_for_chain(client, chain_id, batch)
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                if status_code in (400, 413, 414) and len(batch) > 1:
                    log.debug(
                        "[DEX][TOKEN][INFORMATION] HTTP %d for batch size=%d → splitting and retrying.",
                        status_code,
                        len(batch),
                    )
                    midpoint = len(batch) // 2
                    left = await _fetch_token_information_for_chain(client, chain_id, batch[:midpoint])
                    right = await _fetch_token_information_for_chain(client, chain_id, batch[midpoint:])
                    token_information_list_fetched = left + right
                else:
                    log.warning(
                        "[DEX][TOKEN][INFORMATION] HTTP error %d for URL '%s'.",
                        status_code,
                        f"{LATEST_PAIRS_ENDPOINT}/{chain_id}/…",
                    )
                    raise

            for tokenInformation in token_information_list_fetched:
                if tokenInformation.pair_address and tokenInformation.price_usd is not None and tokenInformation.price_usd > 0.0:
                    token_information_list.append(tokenInformation)

        await asyncio.sleep(0)

    log.info("[DEX][TOKEN][INFORMATION] Returning %d token information (requested=%d).",
             len(token_information_list),
             len(unique_tokens))
    return token_information_list


def fetch_dexscreener_token_information_list_sync(tokens: List[Token]) -> List[DexscreenerTokenInformation]:
    """
    Synchronous wrapper for fetch_dexscreener_token_information_list.
    NOTE: This creates a separate event loop/thread, so it CANNOT use the shared client
    bound to the main loop. It uses a one-off client internally via asyncio.run context.
    """
    if not tokens:
        log.debug("[DEX][TOKEN][INFORMATION] Called with an empty token list.")
        return []

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        from concurrent.futures import ThreadPoolExecutor

        def run_coroutine() -> List[DexscreenerTokenInformation]:
            return asyncio.run(fetch_dexscreener_token_information_list(tokens))

        log.debug("[DEX][TOKEN][INFORMATION] Executing synchronous fetch in a worker thread.")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_coroutine)
            return future.result()

    log.debug("[DEX][TOKEN][INFORMATION] Executing synchronous fetch in a new event loop.")
    event_loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(event_loop)
        result: List[DexscreenerTokenInformation] = event_loop.run_until_complete(
            fetch_dexscreener_token_information_list(tokens))

        global _shared_async_client
        if _shared_async_client and not _shared_async_client.is_closed:
            event_loop.run_until_complete(_shared_async_client.aclose())
            _shared_async_client = None

        try:
            event_loop.run_until_complete(event_loop.shutdown_asyncgens())
        except Exception:
            pass
        return result
    finally:
        try:
            asyncio.set_event_loop(None)
        except Exception:
            pass
        event_loop.close()


async def fetch_token_information_by_token_addresses(token_addresses: Iterable[str]) \
        -> Dict[str, List[DexscreenerTokenInformation]]:
    input_addresses: List[str] = list(token_addresses or [])
    if not input_addresses:
        log.debug("[DEX][FETCH][PAIRS] Called with an empty address list.")
        return {}

    unique_addresses: List[str] = _deduplicate_token_addresses_preserving_order(input_addresses)
    if len(unique_addresses) > TOTAL_ADDRESS_HARD_CAP:
        log.info(
            "[DEX][FETCH][PAIRS] Capping address list from %d to hard cap %d.",
            len(unique_addresses),
            TOTAL_ADDRESS_HARD_CAP,
        )
        unique_addresses = unique_addresses[:TOTAL_ADDRESS_HARD_CAP]

    result: Dict[str, List[DexscreenerTokenInformation]] = {address: [] for address in unique_addresses}

    client = _get_shared_client()
    for batch in _split_token_addressed_into_chunks(unique_addresses, DEFAULT_MAX_ADDRESSES_PER_CALL):
        if not batch:
            continue
        log.debug("[DEX][FETCH][PAIRS] Fetching pairs for batch size=%d.", len(batch))
        token_information_list = await _fetch_token_information_list(client, batch)
        for token_information in token_information_list:
            address = token_information.base_token.address
            if address in result:
                result[address].append(token_information)
        await asyncio.sleep(0)

    return result


async def fetch_trending_candidates(page_size: int = 100) -> List[DexscreenerTokenInformation]:
    """
    Aggregate trending candidates from public Dexscreener sources and normalize them.
    Uses the shared HTTP client to maintain connection persistence.
    """
    log.info("[DEX][TREND] Collecting trending candidates from public endpoints.")

    collected_addresses: List[str] = []
    endpoints: List[str] = [
        TOKEN_BOOSTS_LATEST_ENDPOINT,
        TOKEN_BOOSTS_TOP_ENDPOINT,
        TOKEN_PROFILES_ENDPOINT,
    ]

    client = _get_shared_client()
    for url in endpoints:
        try:
            payload = await _http_get_json(client, url)
            extracted = _extract_addresses(payload if isinstance(payload, (dict, list)) else None)
            collected_addresses.extend(extracted)

            payload_size = len(payload) if isinstance(payload, list) else len(payload or {})
            log.debug(
                "[DEX][TREND] Fetched %s → payload_items=%s, extracted_addresses=%s.",
                "/".join(url.rsplit("/", 2)[-2:]),
                payload_size,
                len(extracted),
            )
        except httpx.HTTPError as error:
            log.warning("[DEX][TREND] Read failed for '%s' (%s).", url, error)

    if not collected_addresses:
        log.info("[DEX][TREND] No addresses collected from trending sources.")
        return []

    pairs_by_address = await fetch_token_information_by_token_addresses(collected_addresses)
    if not any(pairs_by_address.values()):
        log.info("[DEX][TREND] Pairs empty for collected addresses.")
        return []

    token_information: List[DexscreenerTokenInformation] = []
    for address, pairs in pairs_by_address.items():
        best_pair = _select_best_pair(pairs)
        if best_pair is None:
            continue
        token_information.append(best_pair)

    token_information.sort(key=lambda t: (t.volume.h24, t.liquidity.usd), reverse=True)
    limited_rows = token_information[: max(1, int(page_size or 1))]
    log.info("[DEX][TREND] Returning %d trending candidates.", len(limited_rows))
    return limited_rows