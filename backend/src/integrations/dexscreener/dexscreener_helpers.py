from __future__ import annotations

from typing import Dict, List, Optional, Union

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.trading_structures import TradingDexMarketSnapshot
from src.integrations.dexscreener.dexscreener_constants import JSON
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation, is_blockchain_network_supported
from src.integrations.dexscreener.dexscreener_utils import (
    compute_buy_to_sell_ratio_from_transactions,
    require_dexscreener_market_statistics,
    require_float,
    require_transaction_count,
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


def calculate_base_per_chain_trending_quota(page_size: int, allowed_chain_count: int) -> int:
    return max(1, page_size // allowed_chain_count)


def select_ranked_tokens_for_base_per_chain_quota(
        candidates_by_chain: dict[BlockchainNetwork, List[DexscreenerTokenInformation]],
        allowed_blockchain_networks: List[BlockchainNetwork],
        base_quota_per_chain: int,
) -> tuple[List[DexscreenerTokenInformation], set[str], dict[BlockchainNetwork, int]]:
    selected_token_information: List[DexscreenerTokenInformation] = []
    selected_pair_addresses: set[str] = set()
    selected_count_by_chain: dict[BlockchainNetwork, int] = {}

    for blockchain_network in allowed_blockchain_networks:
        chain_candidates = candidates_by_chain.get(blockchain_network, [])
        accepted_for_chain = 0
        for token_information in chain_candidates:
            if accepted_for_chain >= base_quota_per_chain:
                break
            if token_information.pair_address in selected_pair_addresses:
                continue
            selected_token_information.append(token_information)
            selected_pair_addresses.add(token_information.pair_address)
            accepted_for_chain += 1
        selected_count_by_chain[blockchain_network] = accepted_for_chain

    return selected_token_information, selected_pair_addresses, selected_count_by_chain


def backfill_trending_selection_to_page_size(
        ranked_token_information: List[DexscreenerTokenInformation],
        allowed_blockchain_networks: List[BlockchainNetwork],
        page_size: int,
        selected_token_information: List[DexscreenerTokenInformation],
        selected_pair_addresses: set[str],
        selected_count_by_chain: dict[BlockchainNetwork, int],
) -> None:
    allowed_blockchain_network_set = set(allowed_blockchain_networks)
    for token_information in ranked_token_information:
        if len(selected_token_information) >= page_size:
            break
        if token_information.chain_id not in allowed_blockchain_network_set:
            continue
        if token_information.pair_address in selected_pair_addresses:
            continue
        selected_token_information.append(token_information)
        selected_pair_addresses.add(token_information.pair_address)
        selected_count_by_chain[token_information.chain_id] = (
            selected_count_by_chain.get(token_information.chain_id, 0) + 1
        )


def apply_per_chain_trending_quota(
        ranked_token_information: List[DexscreenerTokenInformation],
        page_size: int,
        allowed_blockchain_networks: List[BlockchainNetwork],
) -> List[DexscreenerTokenInformation]:
    if not ranked_token_information or page_size <= 0:
        return []

    if not allowed_blockchain_networks:
        return ranked_token_information[:page_size]

    candidates_by_chain: dict[BlockchainNetwork, List[DexscreenerTokenInformation]] = {}
    for token_information in ranked_token_information:
        candidates_by_chain.setdefault(token_information.chain_id, []).append(token_information)

    base_quota_per_chain = calculate_base_per_chain_trending_quota(
        page_size=page_size,
        allowed_chain_count=len(allowed_blockchain_networks),
    )
    selected_token_information, selected_pair_addresses, selected_count_by_chain = (
        select_ranked_tokens_for_base_per_chain_quota(
            candidates_by_chain=candidates_by_chain,
            allowed_blockchain_networks=allowed_blockchain_networks,
            base_quota_per_chain=base_quota_per_chain,
        )
    )

    if len(selected_token_information) < page_size:
        backfill_trending_selection_to_page_size(
            ranked_token_information=ranked_token_information,
            allowed_blockchain_networks=allowed_blockchain_networks,
            page_size=page_size,
            selected_token_information=selected_token_information,
            selected_pair_addresses=selected_pair_addresses,
            selected_count_by_chain=selected_count_by_chain,
        )

    selected_token_information.sort(key=calculate_trending_rank_score, reverse=True)

    logger.info(
        "[DEX][HTTP][TREND][QUOTA] Applied per-chain trending quota — page_size=%d base_quota_per_chain=%d "
        "allowed_chains=%s selected_by_chain=%s total_selected=%d source_ranked=%d",
        page_size,
        base_quota_per_chain,
        ",".join(blockchain_network.value for blockchain_network in allowed_blockchain_networks),
        ",".join(
            f"{blockchain_network.value}={count}"
            for blockchain_network, count in sorted(
                selected_count_by_chain.items(),
                key=lambda item: item[0].value,
            )
        ),
        len(selected_token_information),
        len(ranked_token_information),
    )
    return selected_token_information[:page_size]


def map_token_information_to_trading_market_snapshot(
        token_information: DexscreenerTokenInformation,
) -> TradingDexMarketSnapshot:
    if token_information.pair_created_at is None or token_information.pair_created_at <= 0:
        raise ValueError("Missing pair_created_at for token_age_hours")

    volume, liquidity, price_change, transactions = require_dexscreener_market_statistics(token_information)

    return TradingDexMarketSnapshot(
        price_usd=require_float(token_information.price_usd, "price_usd"),
        price_native=require_float(token_information.price_native, "price_native"),
        token_age_hours=token_information.age_hours,
        volume_m5_usd=require_float(volume.m5, "volume_m5_usd"),
        volume_h1_usd=require_float(volume.h1, "volume_h1_usd"),
        volume_h6_usd=require_float(volume.h6, "volume_h6_usd"),
        volume_h24_usd=require_float(volume.h24, "volume_h24_usd"),
        liquidity_usd=require_float(liquidity.usd, "liquidity_usd"),
        price_change_percentage_m5=require_float(price_change.m5, "price_change_percentage_m5"),
        price_change_percentage_h1=require_float(price_change.h1, "price_change_percentage_h1"),
        price_change_percentage_h6=require_float(price_change.h6, "price_change_percentage_h6"),
        price_change_percentage_h24=require_float(price_change.h24, "price_change_percentage_h24"),
        transaction_count_m5=require_transaction_count(transactions.m5, "transaction_count_m5"),
        transaction_count_h1=require_transaction_count(transactions.h1, "transaction_count_h1"),
        transaction_count_h6=require_transaction_count(transactions.h6, "transaction_count_h6"),
        transaction_count_h24=require_transaction_count(transactions.h24, "transaction_count_h24"),
        buy_to_sell_ratio=compute_buy_to_sell_ratio_from_transactions(transactions),
        market_cap_usd=require_float(token_information.market_cap, "market_cap_usd"),
        fully_diluted_valuation_usd=require_float(
            token_information.fully_diluted_valuation,
            "fully_diluted_valuation_usd",
        ),
        promotion_score=token_information.boost,
    )


def map_token_information_to_trading_token(token_information: DexscreenerTokenInformation) -> Token:
    return Token(
        symbol=token_information.base_token.symbol,
        chain=token_information.chain_id,
        token_address=token_information.base_token.address,
        pair_address=token_information.pair_address,
        dex_id=token_information.dex_id,
    )
