from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Optional

import httpx

from src.core.structures.structures import Token
from src.core.utils.date_utils import timezone_now
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
    _normalize_row_from_pair,
    _fetch_pairs_batch_resilient,
    _chunk_strings,
    _fetch_pairs_for_chain,
    _select_best_pair,
    _deduplicate_token_addresses_preserving_order,
    _split_token_addressed_into_chunks,
)
from src.integrations.dexscreener.dexscreener_structures import (
    DexscreenerPair,
    NormalizedRow,
    TokenPrice,
    TransactionActivity,
)
from src.logging.logger import get_logger

log = get_logger(__name__)


async def fetch_pairs_by_tokens(tokens: Iterable[Token]) -> Dict[str, List[DexscreenerPair]]:
    """
    Fetch raw pairs for a list of tokens (best-effort, batched and chain-agnostic).

    Returns:
        Mapping { base_token_address -> [DexscreenerPair, ...] }.
    """
    tokens_list: List[Token] = list(tokens or [])
    if not tokens_list:
        log.debug("[DEX][FETCH][PAIRS] Called with an empty token list.")
        return {}

    unique_tokens: List[Token] = _deduplicate_preserving_order(tokens_list)
    if len(unique_tokens) > TOTAL_ADDRESS_HARD_CAP:
        log.info(
            "[DEX][FETCH][PAIRS] Capping token list from %d to hard cap %d.",
            len(unique_tokens),
            TOTAL_ADDRESS_HARD_CAP,
        )
        unique_tokens = unique_tokens[:TOTAL_ADDRESS_HARD_CAP]

    result: Dict[str, List[DexscreenerPair]] = {t.tokenAddress: [] for t in unique_tokens}
    address_chunks: List[List[str]] = _split_into_chunks(unique_tokens, DEFAULT_MAX_ADDRESSES_PER_CALL)

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for address_batch in address_chunks:
            if not address_batch:
                continue
            log.debug("[DEX][FETCH][PAIRS] Fetching pairs for batch size=%d.", len(address_batch))
            by_address = await _fetch_pairs_batch_resilient(client, address_batch)
            for addr, pairs in by_address.items():
                result[addr] = pairs
            await asyncio.sleep(0)

    return result


async def fetch_prices_by_tokens(tokens: Iterable[Token]) -> List[TokenPrice]:
    """
    Fetch USD prices and slow-moving metrics for the **exact pairAddress** of each token.
    This is a strict pair-only flow (no best-pair fallback).

    Returns:
        List of TokenPrice, at most one per input token with a positive price.
    """
    tokens_list: List[Token] = list(tokens or [])
    if not tokens_list:
        log.debug("[DEX][PAIR][PRICE] Called with an empty token list.")
        return []

    unique_tokens: List[Token] = _deduplicate_preserving_order(tokens_list)
    if len(unique_tokens) > TOTAL_ADDRESS_HARD_CAP:
        log.info(
            "[DEX][PAIR][PRICE] Capping token list from %d to hard cap %d.",
            len(unique_tokens),
            TOTAL_ADDRESS_HARD_CAP,
        )
        unique_tokens = unique_tokens[:TOTAL_ADDRESS_HARD_CAP]

    # Group tokens by chain to hit /latest/pairs/{chain}/{pair1,pair2,...}
    tokens_by_chain: Dict[str, List[Token]] = {}
    for token in unique_tokens:
        if not token.chain or not token.pairAddress:
            log.debug("[DEX][PAIR][PRICE] Skipping token without chain/pair: %s", str(token))
            continue
        tokens_by_chain.setdefault(token.chain, []).append(token)

    # Retain the full DexscreenerPair per strict pairAddress
    pair_by_address: Dict[str, DexscreenerPair] = {}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
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
                    pairs: List[DexscreenerPair] = await _fetch_pairs_for_chain(client, chain_id, batch)
                except httpx.HTTPStatusError as error:
                    status_code = error.response.status_code
                    if status_code in (400, 413, 414) and len(batch) > 1:
                        log.debug(
                            "[DEX][PAIR][PRICE] HTTP %d for batch size=%d → splitting and retrying.",
                            status_code,
                            len(batch),
                        )
                        midpoint = len(batch) // 2
                        left = await _fetch_pairs_for_chain(client, chain_id, batch[:midpoint])
                        right = await _fetch_pairs_for_chain(client, chain_id, batch[midpoint:])
                        pairs = left + right
                    else:
                        log.warning(
                            "[DEX][PAIR][PRICE] HTTP error %d for URL '%s'.",
                            status_code,
                            f"{LATEST_PAIRS_ENDPOINT}/{chain_id}/…",
                        )
                        raise

                for pair in pairs:
                    if pair.pair_address and pair.price_usd is not None and pair.price_usd > 0.0:
                        pair_by_address[pair.pair_address] = pair

            await asyncio.sleep(0)

    # Build TokenPrice with extended signals where available
    prices: List[TokenPrice] = []
    for token in unique_tokens:
        model: Optional[DexscreenerPair] = pair_by_address.get(token.pairAddress)
        if model is None or model.price_usd is None or model.price_usd <= 0.0:
            continue

        liquidity_usd: Optional[float] = float(model.liquidity.usd) if (model.liquidity and model.liquidity.usd) else None
        fdv_usd: Optional[float] = float(model.fdv) if model.fdv is not None else None
        market_cap_usd: Optional[float] = float(model.market_cap) if model.market_cap is not None else None

        buys_5m: Optional[int] = model.txns.m5.buys if (model.txns and model.txns.m5) else None
        sells_5m: Optional[int] = model.txns.m5.sells if (model.txns and model.txns.m5) else None
        txns_activity: Optional[TransactionActivity] = model.txns if model.txns else None
        volume_h24_usd: Optional[float] = float(model.volume.h24) if (model.volume and model.volume.h24) else None

        token_price = TokenPrice(
            token=token,
            priceUsd=float(model.price_usd),
            liquidityUsd=liquidity_usd,
            fdvUsd=fdv_usd,
            marketCapUsd=market_cap_usd,
            buys5m=buys_5m,
            sells5m=sells_5m,
            txns=txns_activity,
            volumeH24Usd=volume_h24_usd,
            asOf=timezone_now(),
        )
        prices.append(token_price)

    log.info("[DEX][PAIR][PRICE] Returning %d prices (requested=%d).", len(prices), len(unique_tokens))
    return prices


def fetch_price_by_tokens_sync(tokens: List[Token]) -> List[TokenPrice]:
    """
    Synchronous wrapper around `fetch_prices_by_tokens`.

    If an event loop is already running, the coroutine is executed in a worker thread.
    Otherwise, it is executed in a dedicated event loop.
    """
    if not tokens:
        log.debug("[DEX][PRICE][SYNC] Called with an empty token list.")
        return []

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        from concurrent.futures import ThreadPoolExecutor

        def run_coroutine() -> List[TokenPrice]:
            return asyncio.run(fetch_prices_by_tokens(tokens))

        log.debug("[DEX][PRICE][SYNC] Executing synchronous fetch in a worker thread.")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_coroutine)
            return future.result()

    log.debug("[DEX][PRICE][SYNC] Executing synchronous fetch in a new event loop.")
    event_loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(event_loop)
        result: List[TokenPrice] = event_loop.run_until_complete(fetch_prices_by_tokens(tokens))
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


async def fetch_pairs_by_token_addresses(token_addresses: Iterable[str]) -> Dict[str, List[DexscreenerPair]]:
    """
    Fetch raw pairs for a list of base-token addresses (best-effort).

    Returns:
        Mapping { address -> [DexscreenerPair, ...] }.
    """
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

    result: Dict[str, List[DexscreenerPair]] = {address: [] for address in unique_addresses}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for batch in _split_token_addressed_into_chunks(unique_addresses, DEFAULT_MAX_ADDRESSES_PER_CALL):
            if not batch:
                continue
            log.debug("[DEX][FETCH][PAIRS] Fetching pairs for batch size=%d.", len(batch))
            by_address = await _fetch_pairs_batch_resilient(client, batch)
            for address, pairs in by_address.items():
                result[address] = pairs
            await asyncio.sleep(0)

    return result


async def fetch_trending_candidates(page_size: int = 100) -> List[NormalizedRow]:
    """
    Aggregate trending candidates from public Dexscreener sources and normalize them.

    The sources are combined, their addresses deduplicated, then the best pair for each
    address is selected and normalized. The result is sorted by (24h volume, liquidity)
    descending and limited to `page_size`.

    Returns:
        A list of NormalizedRow.
    """
    log.info("[DEX][TREND] Collecting trending candidates from public endpoints.")

    collected_addresses: List[str] = []
    endpoints: List[str] = [
        TOKEN_BOOSTS_LATEST_ENDPOINT,
        TOKEN_BOOSTS_TOP_ENDPOINT,
        TOKEN_PROFILES_ENDPOINT,
    ]

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
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

    pairs_by_address = await fetch_pairs_by_token_addresses(collected_addresses)
    if not any(pairs_by_address.values()):
        log.info("[DEX][TREND] Pairs empty for collected addresses.")
        return []

    rows: List[NormalizedRow] = []
    for address, pairs in pairs_by_address.items():
        best_pair = _select_best_pair(pairs)
        if best_pair is None:
            continue
        rows.append(_normalize_row_from_pair(best_pair))

    rows.sort(key=lambda r: (r.vol24h, r.liqUsd), reverse=True)
    limited_rows = rows[: max(1, int(page_size or 1))]
    log.info("[DEX][TREND] Returning %d trending candidates.", len(limited_rows))
    return limited_rows
