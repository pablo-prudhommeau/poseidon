from __future__ import annotations

from typing import Dict, List, Optional, Union

from src.integrations.dexscreener.dexscreener_constants import JSON
from src.integrations.dexscreener.dexscreener_structures import (
    DexscreenerTokenInformation,
    is_blockchain_network_supported,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def map_pair_payload_to_token_information(
        pair_payload: Dict[str, JSON],
) -> Optional[DexscreenerTokenInformation]:
    chain_id = pair_payload.get("chainId")
    if not is_blockchain_network_supported(chain_id):
        return None
    try:
        return DexscreenerTokenInformation.model_validate(pair_payload)
    except Exception as error:
        logger.debug("[DEX][MAP][PAIR] Failed to validate pair payload: %s", error)
        return None


def map_pairs_list_payload_to_token_information_list(
        pairs_list: List[Dict[str, JSON]],
) -> List[DexscreenerTokenInformation]:
    token_information_list: List[DexscreenerTokenInformation] = []
    unsupported_chains_count: dict[str, int] = {}

    for pair_payload in pairs_list:
        chain_id = pair_payload.get("chainId")
        if not is_blockchain_network_supported(chain_id):
            unsupported_chains_count[str(chain_id)] = unsupported_chains_count.get(str(chain_id), 0) + 1
            continue

        token_information = map_pair_payload_to_token_information(pair_payload)
        if token_information is None:
            continue
        if not token_information.base_token.address:
            continue
        token_information_list.append(token_information)

    if unsupported_chains_count:
        chains_summary = ", ".join(
            [f"{chain}({count})" for chain, count in sorted(unsupported_chains_count.items())]
        )
        logger.debug("[DEX][MAP][FILTER] Filtered unsupported blockchains: %s", chains_summary)

    return token_information_list


def map_pairs_response_payload_to_token_information_list(
        payload: Union[Dict[str, JSON], List[JSON], None],
) -> List[DexscreenerTokenInformation]:
    if payload is None:
        return []

    if isinstance(payload, dict):
        raw_list = payload.get("pairs")
        if not isinstance(raw_list, list):
            return []
        pairs_list = [pair_item for pair_item in raw_list if isinstance(pair_item, dict)]
        return map_pairs_list_payload_to_token_information_list(pairs_list)

    if isinstance(payload, list):
        pairs_list = [pair_item for pair_item in payload if isinstance(pair_item, dict)]
        return map_pairs_list_payload_to_token_information_list(pairs_list)

    return []


def extract_pair_payloads_from_token_batch_response(
        payload: Union[Dict[str, JSON], List[JSON], None],
) -> List[Dict[str, JSON]]:
    if not isinstance(payload, dict):
        return []
    pairs_value = payload.get("pairs")
    if pairs_value is None:
        return []
    if not isinstance(pairs_value, list):
        return []
    return [pair_item for pair_item in pairs_value if isinstance(pair_item, dict)]


def select_best_pair(pairs: List[DexscreenerTokenInformation]) -> Optional[DexscreenerTokenInformation]:
    if not pairs:
        return None

    def calculate_pair_score(item: DexscreenerTokenInformation) -> tuple[float, float]:
        liquidity_usd = item.liquidity.usd if item.liquidity and item.liquidity.usd else 0.0
        volume_h24 = item.volume.h24 if item.volume and item.volume.h24 else 0.0
        return liquidity_usd, volume_h24

    return sorted(pairs, key=calculate_pair_score, reverse=True)[0]


def calculate_trending_rank_score(item: DexscreenerTokenInformation) -> tuple[float, float]:
    volume_h24 = item.volume.h24 if item.volume and item.volume.h24 else 0.0
    liquidity_usd = item.liquidity.usd if item.liquidity and item.liquidity.usd else 0.0
    return volume_h24, liquidity_usd
