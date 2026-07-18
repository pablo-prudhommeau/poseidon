from __future__ import annotations

from typing import Optional, Protocol

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelBlockExchangeRateMemoEntry,
    AaveSentinelBlockTimestampMemoEntry,
    AaveSentinelCapitalFlowValuationContext,
    AaveSentinelCapitalFlowValuationMemo,
    AaveSentinelDateExchangeRateMemoEntry,
    AaveSentinelHistoricalAssetPriceLookupKey,
    AaveSentinelHistoricalAssetPriceMemoEntry,
)


class AaveSentinelCapitalFlowUsdValuationResolver(Protocol):
    def resolve_amount_usd(self, valuation_context: AaveSentinelCapitalFlowValuationContext) -> float:
        ...


def create_empty_capital_flow_valuation_memo() -> AaveSentinelCapitalFlowValuationMemo:
    return AaveSentinelCapitalFlowValuationMemo()


def build_historical_asset_price_lookup_key(
        block_number: int,
        contract_address: str,
) -> AaveSentinelHistoricalAssetPriceLookupKey:
    return AaveSentinelHistoricalAssetPriceLookupKey(
        block_number=block_number,
        contract_address=contract_address.lower(),
    )


def resolve_valuation_memo_block_exchange_rate(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
) -> Optional[float]:
    for memo_entry in valuation_memo.block_exchange_rates:
        if memo_entry.block_number == block_number:
            return memo_entry.exchange_rate
    return None


def remember_valuation_memo_block_exchange_rate(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        exchange_rate: float,
) -> None:
    if resolve_valuation_memo_block_exchange_rate(
            valuation_memo=valuation_memo,
            block_number=block_number,
    ) is not None:
        return
    valuation_memo.block_exchange_rates.append(
        AaveSentinelBlockExchangeRateMemoEntry(
            block_number=block_number,
            exchange_rate=exchange_rate,
        )
    )


def resolve_valuation_memo_date_exchange_rate(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        exchange_rate_date: str,
) -> Optional[float]:
    for memo_entry in valuation_memo.date_exchange_rates:
        if memo_entry.exchange_rate_date == exchange_rate_date:
            return memo_entry.exchange_rate
    return None


def remember_valuation_memo_date_exchange_rate(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        exchange_rate_date: str,
        exchange_rate: float,
) -> None:
    if resolve_valuation_memo_date_exchange_rate(
            valuation_memo=valuation_memo,
            exchange_rate_date=exchange_rate_date,
    ) is not None:
        return
    valuation_memo.date_exchange_rates.append(
        AaveSentinelDateExchangeRateMemoEntry(
            exchange_rate_date=exchange_rate_date,
            exchange_rate=exchange_rate,
        )
    )


def resolve_valuation_memo_historical_asset_price_usd(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        lookup_key: AaveSentinelHistoricalAssetPriceLookupKey,
) -> Optional[float]:
    for memo_entry in valuation_memo.historical_asset_prices:
        if memo_entry.lookup_key == lookup_key:
            return memo_entry.asset_price_usd
    return None


def remember_valuation_memo_historical_asset_price_usd(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        lookup_key: AaveSentinelHistoricalAssetPriceLookupKey,
        asset_price_usd: float,
) -> None:
    if resolve_valuation_memo_historical_asset_price_usd(
            valuation_memo=valuation_memo,
            lookup_key=lookup_key,
    ) is not None:
        return
    valuation_memo.historical_asset_prices.append(
        AaveSentinelHistoricalAssetPriceMemoEntry(
            lookup_key=lookup_key,
            asset_price_usd=asset_price_usd,
        )
    )


def resolve_valuation_memo_block_timestamp_seconds(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
) -> Optional[int]:
    for memo_entry in valuation_memo.block_timestamps:
        if memo_entry.block_number == block_number:
            return memo_entry.timestamp_seconds
    return None


def remember_valuation_memo_block_timestamp_seconds(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        timestamp_seconds: int,
) -> None:
    if resolve_valuation_memo_block_timestamp_seconds(
            valuation_memo=valuation_memo,
            block_number=block_number,
    ) is not None:
        return
    valuation_memo.block_timestamps.append(
        AaveSentinelBlockTimestampMemoEntry(
            block_number=block_number,
            timestamp_seconds=timestamp_seconds,
        )
    )
