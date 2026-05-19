from __future__ import annotations

from typing import Dict, Iterable, List, Union

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.trading_structures import TradingDexMarketSnapshot
from src.integrations.dexscreener.dexscreener_constants import JSON
from src.integrations.dexscreener.dexscreener_structures import (
    DexscreenerLiquidityStatistics,
    DexscreenerPriceChangeStatistics,
    DexscreenerTokenInformation,
    DexscreenerTransactionActivity,
    DexscreenerTransactionCount,
    DexscreenerVolumeStatistics,
)


def chunk_strings(items: List[str], size: int) -> List[List[str]]:
    limit = max(1, int(size or 1))
    return [items[index: index + limit] for index in range(0, len(items), limit)]


def split_tokens_into_address_chunks(tokens: List[Token], chunk_size: int) -> List[List[str]]:
    chunks: List[List[str]] = []
    for index in range(0, len(tokens), chunk_size):
        chunk = [token.token_address for token in tokens[index: index + chunk_size]]
        chunks.append(chunk)
    return chunks


def split_token_addresses_into_chunks(items: List[str], chunk_size: int) -> List[List[str]]:
    effective_size = max(1, int(chunk_size or 1))
    return [items[index: index + effective_size] for index in range(0, len(items), effective_size)]


def deduplicate_tokens_preserving_order(values: Iterable[Token]) -> List[Token]:
    seen: set[tuple[str, str, str, str]] = set()
    deduplicated: List[Token] = []
    for token in values:
        identifier = (token.symbol, token.chain, token.token_address, token.pair_address)
        if identifier not in seen:
            seen.add(identifier)
            deduplicated.append(token)
    return deduplicated


def deduplicate_token_addresses_preserving_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    unique: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def extract_addresses(payload: Union[Dict[str, JSON], List[JSON], None]) -> List[str]:
    addresses: List[str] = []

    def pull_address_from_item(item: Dict[str, JSON]) -> None:
        candidate = (item.get("tokenAddress") or item.get("address") or "")
        if not isinstance(candidate, str) or not candidate:
            base = item.get("baseToken") or item.get("token") or {}
            if isinstance(base, dict):
                base_address = base.get("address") or ""
                if isinstance(base_address, str):
                    candidate = base_address
        if isinstance(candidate, str):
            trimmed = candidate.strip()
            if trimmed and trimmed.isalnum() and len(trimmed) >= 20:
                addresses.append(trimmed)

    if payload is None:
        return addresses

    if isinstance(payload, list):
        for element in payload:
            if isinstance(element, dict):
                pull_address_from_item(element)
        return addresses

    if isinstance(payload, dict):
        for key in ("data", "tokens", "profiles", "pairs"):
            maybe_items = payload.get(key)
            if isinstance(maybe_items, list):
                for item in maybe_items:
                    if isinstance(item, dict):
                        pull_address_from_item(item)
        return addresses

    return addresses


def require_float(value: float | None, field_name: str) -> float:
    if value is None:
        raise ValueError(f"Missing required float field: {field_name}")
    return value


def require_transaction_count(
        transaction_bucket: DexscreenerTransactionCount | None,
        field_name: str,
) -> int:
    if transaction_bucket is None:
        raise ValueError(f"Missing required transaction bucket: {field_name}")
    return transaction_bucket.total_transactions


def require_dexscreener_market_statistics(
        token_information: DexscreenerTokenInformation,
) -> tuple[
    DexscreenerVolumeStatistics,
    DexscreenerLiquidityStatistics,
    DexscreenerPriceChangeStatistics,
    DexscreenerTransactionActivity,
]:
    volume = token_information.volume
    liquidity = token_information.liquidity
    price_change = token_information.price_change
    transactions = token_information.transactions
    if volume is None:
        raise ValueError("Missing volume statistics for dex market snapshot")
    if liquidity is None:
        raise ValueError("Missing liquidity statistics for dex market snapshot")
    if price_change is None:
        raise ValueError("Missing price change statistics for dex market snapshot")
    if transactions is None:
        raise ValueError("Missing transaction activity for dex market snapshot")
    return volume, liquidity, price_change, transactions


def compute_buy_to_sell_ratio_from_transactions(transactions: DexscreenerTransactionActivity) -> float:
    reference_bucket = transactions.h1 if transactions.h1 is not None else transactions.h24
    if reference_bucket is None:
        raise ValueError("Missing h1/h24 transaction bucket for buy_to_sell_ratio")
    total_transaction_count = reference_bucket.buys + reference_bucket.sells
    if total_transaction_count <= 0:
        raise ValueError("Transaction bucket has zero total transactions for buy_to_sell_ratio")
    return reference_bucket.buys / total_transaction_count


def build_dexscreener_token_lookup_key(
        chain: BlockchainNetwork,
        token_address: str,
        pair_address: str,
) -> tuple[BlockchainNetwork, str, str]:
    return chain, token_address, pair_address


def index_dexscreener_token_information_list(
        token_information_list: list[DexscreenerTokenInformation],
) -> dict[tuple[BlockchainNetwork, str, str], DexscreenerTokenInformation]:
    indexed: dict[tuple[BlockchainNetwork, str, str], DexscreenerTokenInformation] = {}
    for token_information in token_information_list:
        lookup_key = build_dexscreener_token_lookup_key(
            token_information.chain_id,
            token_information.base_token.address,
            token_information.pair_address,
        )
        indexed[lookup_key] = token_information
    return indexed


def resolve_dexscreener_token_information_for_token(
        indexed_token_information: dict[tuple[BlockchainNetwork, str, str], DexscreenerTokenInformation],
        token: Token,
) -> DexscreenerTokenInformation | None:
    preferred_key = build_dexscreener_token_lookup_key(token.chain, token.token_address, token.pair_address)
    if preferred_key in indexed_token_information:
        return indexed_token_information[preferred_key]

    for lookup_key, token_information in indexed_token_information.items():
        if lookup_key[0] == token.chain and lookup_key[1] == token.token_address:
            return token_information
    return None


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
        fully_diluted_valuation_usd=require_float(token_information.fully_diluted_valuation, "fully_diluted_valuation_usd"),
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
