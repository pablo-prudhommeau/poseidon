from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Optional, Union

import httpx

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.trading_chain_capability_service import (
    resolve_trading_allowed_blockchain_networks,
)
from src.core.utils.format_utils import tail
from src.integrations.dexscreener.dexscreener_constants import (
    COMMUNITY_TAKEOVERS_ENDPOINT,
    DEFAULT_MAX_ADDRESSES_PER_CALL,
    HTTP_TIMEOUT_SECONDS,
    JSON,
    LATEST_PAIRS_ENDPOINT,
    LATEST_TOKENS_ENDPOINT,
    TOKEN_BOOSTS_LATEST_ENDPOINT,
    TOKEN_BOOSTS_TOP_ENDPOINT,
    TOKEN_PROFILES_ENDPOINT,
    TOKEN_PROFILES_RECENT_UPDATES_ENDPOINT,
    TOTAL_ADDRESS_HARD_CAP,
)
from src.integrations.dexscreener.dexscreener_helpers import (
    apply_per_chain_trending_quota,
    calculate_trending_rank_score,
    extract_pair_payloads_from_token_batch_response,
    map_pairs_list_payload_to_token_information_list,
    map_pairs_response_payload_to_token_information_list,
    select_best_pair,
)
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.integrations.dexscreener.dexscreener_utils import (
    chunk_strings,
    deduplicate_token_addresses_preserving_order,
    deduplicate_tokens_preserving_order,
    extract_addresses,
    split_token_addresses_into_chunks,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_shared_async_client: Optional[httpx.AsyncClient] = None
_shared_async_client_loop_id: Optional[int] = None


def _get_shared_client() -> httpx.AsyncClient:
    global _shared_async_client, _shared_async_client_loop_id

    try:
        current_loop = asyncio.get_running_loop()
        current_loop_id = id(current_loop)
    except RuntimeError:
        current_loop_id = None

    if _shared_async_client is None or _shared_async_client_loop_id != current_loop_id:
        _shared_async_client = httpx.AsyncClient()
        _shared_async_client_loop_id = current_loop_id

    return _shared_async_client


async def _http_get_json(
        client: httpx.AsyncClient,
        url: str,
) -> Union[Dict[str, JSON], List[JSON], None]:
    response = await client.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        logger.debug("[DEX][HTTP] JSON parse failed for URL '%s'.", url)
        return None


async def _fetch_token_information_for_chain(
        client: httpx.AsyncClient,
        chain: BlockchainNetwork,
        pair_addresses: List[str],
) -> List[DexscreenerTokenInformation]:
    if not pair_addresses:
        return []

    url = f"{LATEST_PAIRS_ENDPOINT}/{chain.value}/{','.join(pair_addresses)}"
    payload = await _http_get_json(client, url)
    return map_pairs_response_payload_to_token_information_list(payload)


async def _fetch_token_information_list(
        client: httpx.AsyncClient,
        batch_addresses: List[str],
) -> List[DexscreenerTokenInformation]:
    if not batch_addresses:
        return []

    url = f"{LATEST_TOKENS_ENDPOINT}/{','.join(batch_addresses)}"
    try:
        payload = await _http_get_json(client, url)
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in (400, 413, 414) and len(batch_addresses) > 1:
            logger.debug("[DEX][HTTP][FETCH] HTTP %d for batch size %d → splitting and retrying.", status, len(batch_addresses))
            middle_index = len(batch_addresses) // 2
            left_side_results = await _fetch_token_information_list(client, batch_addresses[:middle_index])
            right_side_results = await _fetch_token_information_list(client, batch_addresses[middle_index:])
            return left_side_results + right_side_results
        logger.warning("[DEX][HTTP][FETCH] HTTP error %d for URL '%s'.", status, url)
        raise

    pairs_list = extract_pair_payloads_from_token_batch_response(payload)
    if payload is not None and isinstance(payload, dict) and payload.get("pairs") is None:
        if len(batch_addresses) > 1:
            logger.debug("[DEX][HTTP][FETCH] 'pairs' is null for batch size %d → splitting and retrying.", len(batch_addresses))
            middle_index = len(batch_addresses) // 2
            left_side_results = await _fetch_token_information_list(client, batch_addresses[:middle_index])
            right_side_results = await _fetch_token_information_list(client, batch_addresses[middle_index:])
            return left_side_results + right_side_results
        logger.debug("[DEX][HTTP][FETCH] 'pairs' is null for address '%s' (no result).", batch_addresses[0])
        return []

    return map_pairs_list_payload_to_token_information_list(pairs_list)


async def fetch_dexscreener_token_information_list(
        tokens: Iterable[Token],
        client: Optional[httpx.AsyncClient] = None,
) -> List[DexscreenerTokenInformation]:
    tokens_list: List[Token] = list(tokens or [])
    if not tokens_list:
        logger.debug("[DEX][HTTP][TOKEN] Called with an empty token list.")
        return []

    unique_tokens: List[Token] = deduplicate_tokens_preserving_order(tokens_list)
    if len(unique_tokens) > TOTAL_ADDRESS_HARD_CAP:
        logger.info(
            "[DEX][HTTP][TOKEN] Capping token list from %d to hard cap %d.",
            len(unique_tokens),
            TOTAL_ADDRESS_HARD_CAP,
        )
        unique_tokens = unique_tokens[:TOTAL_ADDRESS_HARD_CAP]

    tokens_by_chain: Dict[BlockchainNetwork, List[Token]] = {}
    for token in unique_tokens:
        if not token.chain or not token.pair_address:
            logger.debug("[DEX][HTTP][TOKEN] Skipping token without chain/pair: %s", str(token))
            continue
        tokens_by_chain.setdefault(token.chain, []).append(token)

    http_client = client if client is not None else _get_shared_client()

    token_information_list: List[DexscreenerTokenInformation] = []
    for chain, chain_tokens in tokens_by_chain.items():
        if not chain_tokens:
            continue

        seen_pair_addresses: set[str] = set()
        pair_addresses: List[str] = []
        symbol_by_pair_address: dict[str, str] = {}
        for token in chain_tokens:
            if token.pair_address not in seen_pair_addresses:
                seen_pair_addresses.add(token.pair_address)
                pair_addresses.append(token.pair_address)
                symbol_by_pair_address[token.pair_address] = token.symbol

        for batch in chunk_strings(pair_addresses, DEFAULT_MAX_ADDRESSES_PER_CALL):
            symbols_in_batch = [symbol_by_pair_address.get(address, "") for address in batch]
            logger.debug(
                "[DEX][HTTP][TOKEN] Fetching chain=%s batch_size=%d pairs=%s symbols=%s",
                chain.value,
                len(batch),
                ",".join([tail(address) for address in batch]),
                ",".join([symbol for symbol in symbols_in_batch if symbol]),
            )
            try:
                token_information_list_fetched = await _fetch_token_information_for_chain(http_client, chain, batch)
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                if status_code in (400, 413, 414) and len(batch) > 1:
                    logger.debug(
                        "[DEX][HTTP][TOKEN] HTTP %d for batch size=%d → splitting and retrying.",
                        status_code,
                        len(batch),
                    )
                    midpoint = len(batch) // 2
                    left = await _fetch_token_information_for_chain(http_client, chain, batch[:midpoint])
                    right = await _fetch_token_information_for_chain(http_client, chain, batch[midpoint:])
                    token_information_list_fetched = left + right
                else:
                    logger.warning(
                        "[DEX][HTTP][TOKEN] HTTP error %d for URL '%s'.",
                        status_code,
                        f"{LATEST_PAIRS_ENDPOINT}/{chain.value}/…",
                    )
                    raise

            for token_information_item in token_information_list_fetched:
                if (
                        token_information_item.pair_address
                        and token_information_item.price_usd is not None
                        and token_information_item.price_usd > 0.0
                ):
                    token_information_list.append(token_information_item)

        await asyncio.sleep(0)

    logger.info(
        "[DEX][HTTP][TOKEN] Returning %d token information (requested=%d).",
        len(token_information_list),
        len(unique_tokens),
    )
    return token_information_list


def fetch_dexscreener_token_information_list_sync(tokens: List[Token]) -> List[DexscreenerTokenInformation]:
    if not tokens:
        logger.debug("[DEX][HTTP][TOKEN] Called with an empty token list.")
        return []

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        from concurrent.futures import ThreadPoolExecutor

        def run_coroutine() -> List[DexscreenerTokenInformation]:
            return asyncio.run(fetch_dexscreener_token_information_list(tokens))

        logger.debug("[DEX][HTTP][TOKEN] Executing synchronous fetch in a worker thread.")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_coroutine)
            return future.result()

    logger.debug("[DEX][HTTP][TOKEN] Executing synchronous fetch in a new event loop.")
    event_loop = asyncio.new_event_loop()

    async def run_with_local_client() -> List[DexscreenerTokenInformation]:
        async with httpx.AsyncClient() as local_client:
            return await fetch_dexscreener_token_information_list(tokens, client=local_client)

    try:
        asyncio.set_event_loop(event_loop)
        result: List[DexscreenerTokenInformation] = event_loop.run_until_complete(run_with_local_client())
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


async def fetch_token_information_by_token_addresses(
        token_addresses: Iterable[str],
) -> Dict[str, List[DexscreenerTokenInformation]]:
    input_addresses: List[str] = list(token_addresses or [])
    if not input_addresses:
        logger.debug("[DEX][HTTP][PAIRS] Called with an empty address list.")
        return {}

    unique_addresses: List[str] = deduplicate_token_addresses_preserving_order(input_addresses)
    if len(unique_addresses) > TOTAL_ADDRESS_HARD_CAP:
        logger.info(
            "[DEX][HTTP][PAIRS] Capping address list from %d to hard cap %d.",
            len(unique_addresses),
            TOTAL_ADDRESS_HARD_CAP,
        )
        unique_addresses = unique_addresses[:TOTAL_ADDRESS_HARD_CAP]

    result: Dict[str, List[DexscreenerTokenInformation]] = {address: [] for address in unique_addresses}

    http_client = _get_shared_client()
    for batch in split_token_addresses_into_chunks(unique_addresses, DEFAULT_MAX_ADDRESSES_PER_CALL):
        if not batch:
            continue
        logger.debug("[DEX][HTTP][PAIRS] Fetching pairs for batch size=%d.", len(batch))
        token_information_list = await _fetch_token_information_list(http_client, batch)
        for token_information in token_information_list:
            address = token_information.base_token.address
            if address in result:
                result[address].append(token_information)
        await asyncio.sleep(0)

    return result


async def fetch_trending_candidates() -> List[DexscreenerTokenInformation]:
    logger.debug("[DEX][HTTP][TREND] Collecting trending candidates from public endpoints.")

    allowed_blockchain_networks = resolve_trading_allowed_blockchain_networks()
    allowed_blockchain_network_set = set(allowed_blockchain_networks)

    collected_addresses: List[str] = []
    endpoint_address_counts: dict[str, int] = {}
    endpoints: List[str] = [
        TOKEN_BOOSTS_LATEST_ENDPOINT,
        TOKEN_BOOSTS_TOP_ENDPOINT,
        TOKEN_PROFILES_ENDPOINT,
        TOKEN_PROFILES_RECENT_UPDATES_ENDPOINT,
        COMMUNITY_TAKEOVERS_ENDPOINT,
    ]

    async with httpx.AsyncClient() as client:
        for url in endpoints:
            endpoint_label = "/".join(url.rsplit("/", 2)[-2:])
            try:
                payload = await _http_get_json(client, url)
                extracted = extract_addresses(payload if isinstance(payload, (dict, list)) else None)
                collected_addresses.extend(extracted)
                endpoint_address_counts[endpoint_label] = len(extracted)

                payload_size = len(payload) if isinstance(payload, list) else len(payload or {})
                logger.debug(
                    "[DEX][HTTP][TREND] Fetched %s → payload_items=%s, extracted_addresses=%s.",
                    endpoint_label,
                    payload_size,
                    len(extracted),
                )
            except httpx.HTTPError as error:
                endpoint_address_counts[endpoint_label] = 0
                logger.warning("[DEX][HTTP][TREND] Read failed for '%s' (%s).", url, error)

    unique_collected_addresses = deduplicate_token_addresses_preserving_order(collected_addresses)
    logger.info(
        "[DEX][HTTP][TREND][FUNNEL] Source extraction — endpoints=%s unique_addresses=%d raw_addresses=%d",
        ",".join(f"{label}={count}" for label, count in sorted(endpoint_address_counts.items())),
        len(unique_collected_addresses),
        len(collected_addresses),
    )

    if not unique_collected_addresses:
        logger.info("[DEX][HTTP][TREND] No addresses collected from trending sources.")
        return []

    pairs_by_address = await fetch_token_information_by_token_addresses(unique_collected_addresses)
    if not any(pairs_by_address.values()):
        logger.info("[DEX][HTTP][TREND] Pairs empty for collected addresses.")
        return []

    token_information: List[DexscreenerTokenInformation] = []
    addresses_without_pairs = 0
    filtered_disallowed_chain_count = 0
    dex_counts: dict[str, int] = {}
    chain_counts: dict[str, int] = {}
    for address, pairs in pairs_by_address.items():
        best_pair = select_best_pair(pairs)
        if best_pair is None:
            addresses_without_pairs += 1
            continue
        if best_pair.chain_id not in allowed_blockchain_network_set:
            filtered_disallowed_chain_count += 1
            continue
        token_information.append(best_pair)
        dex_key = (best_pair.dex_id or "unknown").strip().lower()
        chain_key = best_pair.chain_id.value
        dex_counts[dex_key] = dex_counts.get(dex_key, 0) + 1
        chain_counts[chain_key] = chain_counts.get(chain_key, 0) + 1

    logger.info(
        "[DEX][HTTP][TREND][FUNNEL] Pair hydration — hydrated=%d without_pairs=%d "
        "filtered_disallowed_chains=%d chains=%s top_dexes=%s",
        len(token_information),
        addresses_without_pairs,
        filtered_disallowed_chain_count,
        ",".join(f"{chain}={count}" for chain, count in sorted(chain_counts.items())),
        ",".join(
            f"{dex_id}={count}"
            for dex_id, count in sorted(dex_counts.items(), key=lambda item: item[1], reverse=True)[:8]
        ),
    )

    token_information.sort(key=calculate_trending_rank_score, reverse=True)

    limited_rows = apply_per_chain_trending_quota(
        ranked_token_information=token_information,
        page_size=settings.DEXSCREENER_TRENDING_PAGE_SIZE,
        allowed_blockchain_networks=allowed_blockchain_networks,
    )

    logger.info(
        "[DEX][HTTP][TREND][FUNNEL] Returning %d trending candidates (ranked=%d page_size=%d).",
        len(limited_rows),
        len(token_information),
        settings.DEXSCREENER_TRENDING_PAGE_SIZE,
    )
    return limited_rows
