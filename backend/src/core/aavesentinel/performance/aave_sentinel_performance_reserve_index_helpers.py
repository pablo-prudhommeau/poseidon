from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelHistoricalAssetPriceLookupKey,
    AaveSentinelReserveIndexMemoEntry,
    AaveSentinelReserveIndexSnapshot,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_valuation_memo_helpers import (
    build_historical_asset_price_lookup_key,
)
from src.integrations.aave.aave_protocol_reader import AaveProtocolReader


def resolve_reserve_index_memo_snapshot(
        reserve_index_memo_entries: list[AaveSentinelReserveIndexMemoEntry],
        lookup_key: AaveSentinelHistoricalAssetPriceLookupKey,
) -> Optional[AaveSentinelReserveIndexSnapshot]:
    for memo_entry in reserve_index_memo_entries:
        if memo_entry.lookup_key == lookup_key:
            return memo_entry.reserve_index_snapshot
    return None


def remember_reserve_index_memo_snapshot(
        reserve_index_memo_entries: list[AaveSentinelReserveIndexMemoEntry],
        lookup_key: AaveSentinelHistoricalAssetPriceLookupKey,
        reserve_index_snapshot: AaveSentinelReserveIndexSnapshot,
) -> None:
    if resolve_reserve_index_memo_snapshot(
            reserve_index_memo_entries=reserve_index_memo_entries,
            lookup_key=lookup_key,
    ) is not None:
        return
    reserve_index_memo_entries.append(
        AaveSentinelReserveIndexMemoEntry(
            lookup_key=lookup_key,
            reserve_index_snapshot=reserve_index_snapshot,
        )
    )


async def fetch_reserve_index_snapshot_at_block(
        aave_protocol_reader: AaveProtocolReader,
        block_number: int,
        underlying_address: str,
) -> Optional[AaveSentinelReserveIndexSnapshot]:
    reserve_index_snapshot = await aave_protocol_reader.fetch_reserve_index_snapshot_at_block(
        underlying_address=underlying_address,
        block_number=block_number,
    )
    if reserve_index_snapshot is None:
        return None
    return AaveSentinelReserveIndexSnapshot(
        underlying_address=reserve_index_snapshot.underlying_address,
        liquidity_index=reserve_index_snapshot.liquidity_index,
        variable_borrow_index=reserve_index_snapshot.variable_borrow_index,
    )


async def fetch_reserve_index_snapshots(
        aave_protocol_reader: AaveProtocolReader,
        reserve_index_memo_entries: list[AaveSentinelReserveIndexMemoEntry],
        block_number: int,
        underlying_addresses: list[str],
) -> list[AaveSentinelReserveIndexSnapshot]:
    reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot] = []
    unresolved_underlying_addresses: list[str] = []
    for underlying_address in underlying_addresses:
        lookup_key = build_historical_asset_price_lookup_key(
            block_number=block_number,
            contract_address=underlying_address,
        )
        cached_snapshot = resolve_reserve_index_memo_snapshot(
            reserve_index_memo_entries=reserve_index_memo_entries,
            lookup_key=lookup_key,
        )
        if cached_snapshot is not None:
            reserve_index_snapshots.append(cached_snapshot)
            continue
        unresolved_underlying_addresses.append(underlying_address)

    if len(unresolved_underlying_addresses) == 0:
        return reserve_index_snapshots

    fetched_reserve_index_snapshots = (
        await aave_protocol_reader.fetch_reserve_index_snapshots_at_block_batch(
            underlying_addresses=unresolved_underlying_addresses,
            block_number=block_number,
        )
    )
    for underlying_address in unresolved_underlying_addresses:
        reserve_index_snapshot = None
        normalized_underlying_address = underlying_address.lower()
        for fetched_reserve_index_snapshot in fetched_reserve_index_snapshots:
            if fetched_reserve_index_snapshot.underlying_address == normalized_underlying_address:
                reserve_index_snapshot = fetched_reserve_index_snapshot
                break
        if reserve_index_snapshot is None:
            continue
        sentinel_reserve_index_snapshot = AaveSentinelReserveIndexSnapshot(
            underlying_address=reserve_index_snapshot.underlying_address,
            liquidity_index=reserve_index_snapshot.liquidity_index,
            variable_borrow_index=reserve_index_snapshot.variable_borrow_index,
        )
        lookup_key = build_historical_asset_price_lookup_key(
            block_number=block_number,
            contract_address=underlying_address,
        )
        remember_reserve_index_memo_snapshot(
            reserve_index_memo_entries=reserve_index_memo_entries,
            lookup_key=lookup_key,
            reserve_index_snapshot=sentinel_reserve_index_snapshot,
        )
        reserve_index_snapshots.append(sentinel_reserve_index_snapshot)
    return reserve_index_snapshots
