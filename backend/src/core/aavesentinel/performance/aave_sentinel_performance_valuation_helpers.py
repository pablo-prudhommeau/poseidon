from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowValuationMemo,
    AaveSentinelReserveRegistry,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_valuation_memo_helpers import (
    build_historical_asset_price_lookup_key,
    remember_valuation_memo_block_exchange_rate,
    remember_valuation_memo_block_timestamp_seconds,
    remember_valuation_memo_date_exchange_rate,
    remember_valuation_memo_historical_asset_price_usd,
    resolve_valuation_memo_block_exchange_rate,
    resolve_valuation_memo_date_exchange_rate,
    resolve_valuation_memo_historical_asset_price_usd,
)
from src.integrations.aave.aave_protocol_reader import AaveProtocolReader
from src.integrations.chainlink.chainlink_client import ChainlinkClient
from src.integrations.frankfurter.frankfurter_client import FrankfurterClient
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


async def resolve_oracle_asset_price_usd(
        aave_protocol_reader: AaveProtocolReader,
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        contract_address: str,
) -> Optional[float]:
    asset_price_usd_by_contract = await resolve_oracle_asset_prices_usd_batch(
        aave_protocol_reader=aave_protocol_reader,
        valuation_memo=valuation_memo,
        block_number=block_number,
        contract_addresses=[contract_address],
    )
    return asset_price_usd_by_contract.get(contract_address.lower())


async def resolve_oracle_asset_prices_usd_batch(
        aave_protocol_reader: AaveProtocolReader,
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        contract_addresses: list[str],
) -> dict[str, float]:
    asset_price_usd_by_contract: dict[str, float] = {}
    unresolved_contract_addresses: list[str] = []
    for contract_address in contract_addresses:
        price_lookup_key = build_historical_asset_price_lookup_key(
            block_number=block_number,
            contract_address=contract_address,
        )
        cached_price = resolve_valuation_memo_historical_asset_price_usd(
            valuation_memo=valuation_memo,
            lookup_key=price_lookup_key,
        )
        if cached_price is not None:
            asset_price_usd_by_contract[contract_address.lower()] = cached_price
            continue
        unresolved_contract_addresses.append(contract_address)

    if len(unresolved_contract_addresses) == 0:
        return asset_price_usd_by_contract

    fetched_asset_price_usd_snapshots = await aave_protocol_reader.fetch_asset_prices_usd_at_block_batch(
        contract_addresses=unresolved_contract_addresses,
        block_number=block_number,
    )
    for fetched_asset_price_usd_snapshot in fetched_asset_price_usd_snapshots:
        price_lookup_key = build_historical_asset_price_lookup_key(
            block_number=block_number,
            contract_address=fetched_asset_price_usd_snapshot.contract_address,
        )
        remember_valuation_memo_historical_asset_price_usd(
            valuation_memo=valuation_memo,
            lookup_key=price_lookup_key,
            asset_price_usd=fetched_asset_price_usd_snapshot.asset_price_usd,
        )
        asset_price_usd_by_contract[fetched_asset_price_usd_snapshot.contract_address] = (
            fetched_asset_price_usd_snapshot.asset_price_usd
        )
    return asset_price_usd_by_contract


async def resolve_euro_to_usd_rate(
        chainlink_client: ChainlinkClient,
        frankfurter_client: FrankfurterClient,
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        timestamp_seconds: int,
) -> Optional[float]:
    remember_valuation_memo_block_timestamp_seconds(
        valuation_memo=valuation_memo,
        block_number=block_number,
        timestamp_seconds=timestamp_seconds,
    )
    cached_block_rate = resolve_valuation_memo_block_exchange_rate(
        valuation_memo=valuation_memo,
        block_number=block_number,
    )
    if cached_block_rate is not None:
        return cached_block_rate

    exchange_rate_date = datetime.fromtimestamp(timestamp_seconds).astimezone().strftime("%Y-%m-%d")
    cached_date_rate = resolve_valuation_memo_date_exchange_rate(
        valuation_memo=valuation_memo,
        exchange_rate_date=exchange_rate_date,
    )
    if cached_date_rate is not None:
        remember_valuation_memo_block_exchange_rate(
            valuation_memo=valuation_memo,
            block_number=block_number,
            exchange_rate=cached_date_rate,
        )
        return cached_date_rate

    chainlink_rate = await chainlink_client.fetch_euro_to_usd_rate_at_block(
        block_number=block_number,
    )
    if chainlink_rate is not None:
        remember_valuation_memo_block_exchange_rate(
            valuation_memo=valuation_memo,
            block_number=block_number,
            exchange_rate=chainlink_rate,
        )
        remember_valuation_memo_date_exchange_rate(
            valuation_memo=valuation_memo,
            exchange_rate_date=exchange_rate_date,
            exchange_rate=chainlink_rate,
        )
        return chainlink_rate

    try:
        frankfurter_rate = await frankfurter_client.fetch_euro_to_usd_rate_for_date(
            exchange_rate_date=exchange_rate_date,
        )
        remember_valuation_memo_date_exchange_rate(
            valuation_memo=valuation_memo,
            exchange_rate_date=exchange_rate_date,
            exchange_rate=frankfurter_rate,
        )
        remember_valuation_memo_block_exchange_rate(
            valuation_memo=valuation_memo,
            block_number=block_number,
            exchange_rate=frankfurter_rate,
        )
        return frankfurter_rate
    except Exception:
        logger.exception(
            "[AAVE_SENTINEL][PERFORMANCE][FX] Failed to fetch Frankfurter EUR/USD rate for date=%s",
            exchange_rate_date,
        )
        return None


async def resolve_asset_prices_usd_for_underlyings(
        aave_protocol_reader: AaveProtocolReader,
        chainlink_client: ChainlinkClient,
        frankfurter_client: FrankfurterClient,
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        timestamp_seconds: int,
        underlying_addresses: list[str],
        reserve_registry: AaveSentinelReserveRegistry,
) -> dict[str, float]:
    asset_price_usd_by_underlying: dict[str, float] = {}
    oracle_contract_addresses: list[str] = []
    for underlying_address in underlying_addresses:
        reserve_asset = None
        for candidate_reserve_asset in reserve_registry.reserve_assets:
            if candidate_reserve_asset.underlying_address == underlying_address.lower():
                reserve_asset = candidate_reserve_asset
                break
        if reserve_asset is None:
            oracle_contract_addresses.append(underlying_address)
            continue

        if reserve_asset.requires_euro_conversion:
            euro_to_usd_rate = await resolve_euro_to_usd_rate(
                chainlink_client=chainlink_client,
                frankfurter_client=frankfurter_client,
                valuation_memo=valuation_memo,
                block_number=block_number,
                timestamp_seconds=timestamp_seconds,
            )
            if euro_to_usd_rate is None:
                continue
            asset_price_usd_by_underlying[underlying_address.lower()] = euro_to_usd_rate
            continue

        oracle_contract_addresses.append(underlying_address)

    oracle_asset_price_usd_by_contract = await resolve_oracle_asset_prices_usd_batch(
        aave_protocol_reader=aave_protocol_reader,
        valuation_memo=valuation_memo,
        block_number=block_number,
        contract_addresses=oracle_contract_addresses,
    )
    asset_price_usd_by_underlying.update(oracle_asset_price_usd_by_contract)
    return asset_price_usd_by_underlying


async def resolve_forensic_asset_prices_usd(
        aave_protocol_reader: AaveProtocolReader,
        chainlink_client: ChainlinkClient,
        frankfurter_client: FrankfurterClient,
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        timestamp_seconds: int,
        contract_addresses: list[str],
        reserve_registry: AaveSentinelReserveRegistry,
) -> dict[str, float]:
    asset_price_usd_by_contract = await resolve_asset_prices_usd_for_underlyings(
        aave_protocol_reader=aave_protocol_reader,
        chainlink_client=chainlink_client,
        frankfurter_client=frankfurter_client,
        valuation_memo=valuation_memo,
        block_number=block_number,
        timestamp_seconds=timestamp_seconds,
        underlying_addresses=contract_addresses,
        reserve_registry=reserve_registry,
    )
    unresolved_contract_addresses: list[str] = [
        contract_address
        for contract_address in contract_addresses
        if contract_address.lower() not in asset_price_usd_by_contract
    ]
    if len(unresolved_contract_addresses) == 0:
        return asset_price_usd_by_contract

    oracle_asset_price_usd_by_contract = await resolve_oracle_asset_prices_usd_batch(
        aave_protocol_reader=aave_protocol_reader,
        valuation_memo=valuation_memo,
        block_number=block_number,
        contract_addresses=unresolved_contract_addresses,
    )
    asset_price_usd_by_contract.update(oracle_asset_price_usd_by_contract)
    return asset_price_usd_by_contract
