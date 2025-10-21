from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List

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
    _split_into_chunks,
    _extract_addresses,
    _normalize_row_from_pair, _fetch_pairs_batch_resilient, _chunk_strings, _fetch_pairs_for_chain, _select_best_pair,
)
from src.integrations.dexscreener.dexscreener_structures import DexscreenerPair, NormalizedRow, TokenPrice
from src.logging.logger import get_logger

log = get_logger(__name__)


async def fetch_pairs_by_tokens(tokens: Iterable[Token]) -> Dict[str, List[DexscreenerPair]]:
    """
    Fetch raw pairs for a list of Token objects (best-effort).

    Returns:
        Mapping of base-token **address** (str) -> list[DexscreenerPair].
    """
    tokens_list = list(tokens or [])
    if not tokens_list:
        log.debug("[DEX][FETCH] called with an empty token list.")
        return {}

    tokens_unique = _deduplicate_preserving_order(tokens_list)
    if len(tokens_unique) > TOTAL_ADDRESS_HARD_CAP:
        log.info("[DEX][FETCH] Capping token list from %d to hard cap %d.", len(tokens_unique), TOTAL_ADDRESS_HARD_CAP)
        tokens_unique = tokens_unique[:TOTAL_ADDRESS_HARD_CAP]

    result: Dict[str, List[DexscreenerPair]] = {t.tokenAddress: [] for t in tokens_unique}

    # _split_into_chunks returns List[List[str]] of token addresses for our Token list
    address_chunks: List[List[str]] = _split_into_chunks(tokens_unique, DEFAULT_MAX_ADDRESSES_PER_CALL)

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for address_batch in address_chunks:
            if not address_batch:
                continue
            log.debug("[DEX][FETCH] fetching pairs for batch size %d.", len(address_batch))
            by_address = await _fetch_pairs_batch_resilient(client, address_batch)
            for addr, pairs in by_address.items():
                result[addr] = pairs
            await asyncio.sleep(0)
    return result


async def fetch_prices_by_tokens(tokens: Iterable[Token]) -> List[TokenPrice]:
    """
    Fetch **USD prices** for the **exact pairAddress** of each Token.
    No fallback, no best pair — strict pair-only.

    Returns:
        List[TokenPrice] — one entry per Token with a positive price.
    """
    tokens_list = list(tokens or [])
    if not tokens_list:
        log.debug("[DEX][PAIR][PRICE] called with an empty token list.")
        return []

    tokens_unique = _deduplicate_preserving_order(tokens_list)
    if len(tokens_unique) > TOTAL_ADDRESS_HARD_CAP:
        log.info("[DEX][PAIR][PRICE] Capping token list from %d to hard cap %d.", len(tokens_unique),
                 TOTAL_ADDRESS_HARD_CAP)
        tokens_unique = tokens_unique[:TOTAL_ADDRESS_HARD_CAP]

    # Group tokens by chain to query /pairs per chain
    tokens_by_chain: Dict[str, List[Token]] = {}
    for t in tokens_unique:
        if not t.chain or not t.pairAddress:
            log.debug("[DEX][PAIR][PRICE] skipping token without chain/pair — %s", str(t))
            continue
        tokens_by_chain.setdefault(t.chain, []).append(t)

    price_by_pair: Dict[str, float] = {}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for chain_id, chain_tokens in tokens_by_chain.items():
            if not chain_tokens:
                continue

            # deduplicate pair addresses preserving order
            seen: set[str] = set()
            pair_addresses: List[str] = []
            for t in chain_tokens:
                if t.pairAddress not in seen:
                    seen.add(t.pairAddress)
                    pair_addresses.append(t.pairAddress)

            for batch in _chunk_strings(pair_addresses, DEFAULT_MAX_ADDRESSES_PER_CALL):
                try:
                    pairs = await _fetch_pairs_for_chain(client, chain_id, batch)
                except httpx.HTTPStatusError as error:
                    status = error.response.status_code
                    if status in (400, 413, 414) and len(batch) > 1:
                        log.debug("[DEX][PAIR][PRICE] HTTP %d for batch size %d → splitting and retrying.", status,
                                  len(batch))
                        mid = len(batch) // 2
                        pairs_left = await _fetch_pairs_for_chain(client, chain_id, batch[:mid])
                        pairs_right = await _fetch_pairs_for_chain(client, chain_id, batch[mid:])
                        pairs = pairs_left + pairs_right
                    else:
                        log.warning("[DEX][PAIR][PRICE] HTTP error %d for URL '%s'.", status,
                                    f"{LATEST_PAIRS_ENDPOINT}/{chain_id}/…")
                        raise

                for pair in pairs:
                    if pair.pair_address and pair.price_usd is not None and pair.price_usd > 0.0:
                        price_by_pair[pair.pair_address] = float(pair.price_usd)
            await asyncio.sleep(0)

    # Build the result in input order for determinism
    out: List[TokenPrice] = []
    for t in tokens_unique:
        price = price_by_pair.get(t.pairAddress)
        if price is not None and price > 0.0:
            out.append(TokenPrice(token=t, priceUsd=price))

    log.info("[DEX][PAIR][PRICE] returning %d token prices (exact pair only).", len(out))
    return out


def fetch_price_by_tokens_sync(tokens: List[Token]) -> List[TokenPrice]:
    """
    Synchronous wrapper around `fetch_prices_by_tokens`.

    - If an event loop is running, offload to a worker thread.
    - Otherwise, run the coroutine in a fresh loop.
    """
    if not tokens:
        log.debug("[DEX][PRICE][SYNC] called with an empty token list.")
        return []

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        from concurrent.futures import ThreadPoolExecutor

        def runner() -> List[TokenPrice]:
            return asyncio.run(fetch_prices_by_tokens(tokens))

        log.debug("[DEX][PRICE][SYNC] running synchronous price fetch in a worker thread.")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(runner)
            return future.result()

    log.debug("[DEX][PRICE][SYNC] running synchronous price fetch in a new event loop.")
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result: List[TokenPrice] = loop.run_until_complete(fetch_prices_by_tokens(tokens))
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


# ---------------------------------------------------------------------------
# Trending — keeps legacy "best pair" behavior (ONLY here)
# ---------------------------------------------------------------------------
async def fetch_trending_candidates(token_addresses: Iterable[str], page_size: int = 100) -> List[NormalizedRow]:
    """
    Build trending candidates from an explicit list of **base token addresses**.

    Policy:
        - Query Dexscreener /latest/dex/tokens for those addresses (batched).
        - For each token address, pick the **best pair** (liquidity.usd, then volume.h24).
        - Normalize into rows and sort by (vol24h, liqUsd) descending.
        - Return at most `page_size` rows.

    Args:
        token_addresses: Iterable of base token addresses (strings).
        page_size: Max number of rows to return (defaults to 100).

    Returns:
        A list of NormalizedRow items.
    """
    # Normalize & cap input
    token_addresses_input = [a for a in (token_addresses or []) if isinstance(a, str) and a.strip()]
    if not token_addresses_input:
        log.info("[DEX][TREND] No token addresses provided — returning empty list.")
        return []

    # Deduplicate preserving order
    seen: set[str] = set()
    token_addresses_unique: List[str] = []
    for addr in token_addresses_input:
        if addr not in seen:
            seen.add(addr)
            token_addresses_unique.append(addr)

    if len(token_addresses_unique) > TOTAL_ADDRESS_HARD_CAP:
        log.info(
            "[DEX][TREND] Capping token address list from %d to hard cap %d.",
            len(token_addresses_unique),
            TOTAL_ADDRESS_HARD_CAP,
        )
        token_addresses_unique = token_addresses_unique[:TOTAL_ADDRESS_HARD_CAP]

    # Fetch pairs per batch of base token addresses
    pairs_by_address: Dict[str, List[DexscreenerPair]] = {}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        step = max(1, int(DEFAULT_MAX_ADDRESSES_PER_CALL or 1))
        for i in range(0, len(token_addresses_unique), step):
            batch = token_addresses_unique[i : i + step]
            try:
                log.debug("[DEX][TREND] Fetching pairs for batch size %d.", len(batch))
                batch_map = await _fetch_pairs_batch_resilient(client, batch)
                for addr, pairs in batch_map.items():
                    pairs_by_address.setdefault(addr, []).extend(pairs)
            except httpx.HTTPError as error:
                log.warning("[DEX][TREND] Batch read failed (%s).", error)
            await asyncio.sleep(0)

    if not any(pairs_by_address.values()):
        log.info("[DEX][TREND] No pairs found for provided addresses.")
        return []

    # Choose best pair per token address, then normalize and sort
    rows: List[NormalizedRow] = []
    for addr in token_addresses_unique:
        pairs = pairs_by_address.get(addr, [])
        best = _select_best_pair(pairs)
        if best is None:
            continue
        rows.append(_normalize_row_from_pair(best))

    rows.sort(key=lambda r: (r.vol24h, r.liqUsd), reverse=True)
    limited = rows[: max(1, int(page_size or 1))]
    log.info("[DEX][TREND] Returning %d trending candidates (best pair per token).", len(limited))
    return limited
