from __future__ import annotations

from typing import List, Dict, Iterable, Union, Optional, Tuple

import httpx

from src.core.structures.structures import Token
from src.integrations.dexscreener.dexscreener_constants import JSON, LATEST_TOKENS_ENDPOINT, LATEST_PAIRS_ENDPOINT, HTTP_TIMEOUT_SECONDS
from src.integrations.dexscreener.dexscreener_structures import (
    DexscreenerTokenInformation,
)
from src.logging.logger import get_logger

logger = get_logger(__name__)


def _split_into_chunks(tokens: List[Token], chunk_size: int) -> List[List[str]]:
    chunks: List[List[str]] = []
    for i in range(0, len(tokens), chunk_size):
        chunk = [token.token_address for token in tokens[i: i + chunk_size]]
        chunks.append(chunk)
    return chunks


def _split_token_addressed_into_chunks(items: List[str], chunk_size: int) -> List[List[str]]:
    effective_size = max(1, int(chunk_size or 1))
    return [items[i: i + effective_size] for i in range(0, len(items), effective_size)]


def _deduplicate_preserving_order(values: Iterable[Token]) -> List[Token]:
    seen = set()
    deduped: List[Token] = []
    for token in values:
        identifier = (token.symbol, token.chain, token.token_address, token.pair_address)
        if identifier not in seen:
            seen.add(identifier)
            deduped.append(token)
    return deduped


def _deduplicate_token_addresses_preserving_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    unique: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


async def _http_get_json(client: httpx.AsyncClient, url: str) -> Union[Dict[str, JSON], List[JSON], None]:
    response = await client.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        logger.debug("[DEX][HTTP] JSON parse failed for URL '%s'.", url)
        return None


def _extract_addresses(payload: Union[Dict[str, JSON], List[JSON], None]) -> List[str]:
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


def _chunk_strings(items: List[str], size: int) -> List[List[str]]:
    limit = max(1, int(size or 1))
    return [items[i: i + limit] for i in range(0, len(items), limit)]


async def _fetch_token_information_for_chain(
        client: httpx.AsyncClient,
        chain_id: str,
        pair_addresses: List[str],
) -> List[DexscreenerTokenInformation]:
    if not pair_addresses:
        return []

    url = f"{LATEST_PAIRS_ENDPOINT}/{chain_id}/{','.join(pair_addresses)}"
    payload = await _http_get_json(client, url)

    pairs: List[DexscreenerTokenInformation] = []
    if isinstance(payload, dict):
        raw_list = payload.get("pairs")
        if isinstance(raw_list, list):
            for item in raw_list:
                if isinstance(item, dict):
                        try:
                            pairs.append(DexscreenerTokenInformation.model_validate(item))
                        except Exception:
                            continue
    return pairs


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
            logger.debug("[DEX][FETCH] HTTP %d for batch size %d → splitting and retrying.", status, len(batch_addresses))
            middle_index = len(batch_addresses) // 2
            left_side_results = await _fetch_token_information_list(client, batch_addresses[:middle_index])
            right_side_results = await _fetch_token_information_list(client, batch_addresses[middle_index:])
            return left_side_results + right_side_results
        logger.warning("[DEX][FETCH] HTTP error %d for URL '%s'.", status, url)
        raise

    pairs_list: List[Dict[str, JSON]] = []
    if isinstance(payload, dict):
        pairs_value = payload.get("pairs")
        if pairs_value is None:
            if len(batch_addresses) > 1:
                logger.debug("[DEX][FETCH] 'pairs' is null for batch size %d → splitting and retrying.",
                             len(batch_addresses))
                middle_index = len(batch_addresses) // 2
                left_side_results = await _fetch_token_information_list(client, batch_addresses[:middle_index])
                right_side_results = await _fetch_token_information_list(client, batch_addresses[middle_index:])
                return left_side_results + right_side_results
            logger.debug("[DEX][FETCH] 'pairs' is null for address '%s' (no result).", batch_addresses[0])
            return []
        if isinstance(pairs_value, list):
            pairs_list = [pair_item for pair_item in pairs_value if isinstance(pair_item, dict)]

    token_information_list: List[DexscreenerTokenInformation] = []
    for pair_payload in pairs_list:
        dexscreener_token_information = DexscreenerTokenInformation.model_validate(pair_payload)
        address = dexscreener_token_information.base_token.address
        if not address:
            continue
        token_information_list.append(dexscreener_token_information)
    return token_information_list


def _select_best_pair(pairs: List[DexscreenerTokenInformation]) -> Optional[DexscreenerTokenInformation]:
    if not pairs:
        return None

    def _calculate_pair_score(item: DexscreenerTokenInformation) -> tuple[float, float]:
        liquidity_usd = item.liquidity.usd if item.liquidity and item.liquidity.usd else 0.0
        volume_h24 = item.volume.h24 if item.volume and item.volume.h24 else 0.0
        return liquidity_usd, volume_h24

    return sorted(pairs, key=_calculate_pair_score, reverse=True)[0]
