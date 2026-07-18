from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import (
    NATIVE_AVAX_ASSET_SYMBOL,
    WAVAX_CONTRACT_ADDRESS,
)
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelCapitalFlowValuationContext,
    AaveSentinelCapitalFlowValuationMemo,
    AaveSentinelEuroConversionContext,
    AaveSentinelHistoricalAssetPriceLookupKey,
    AaveSentinelRawCapitalFlowEvent,
    AaveSentinelReserveRegistry,
    AaveSentinelUniversalLedger,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    aggregate_capital_flow_summary,
    collect_pure_capital_flow_events,
    convert_raw_capital_flow_events_to_classified_flows,
    create_empty_capital_flow_summary,
    filter_oracle_priceable_capital_flow_events,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_ledger_helpers import (
    build_universal_ledger,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_valuation_memo_helpers import (
    build_historical_asset_price_lookup_key,
    create_empty_capital_flow_valuation_memo,
    remember_valuation_memo_block_exchange_rate,
    remember_valuation_memo_block_timestamp_seconds,
    remember_valuation_memo_date_exchange_rate,
    remember_valuation_memo_historical_asset_price_usd,
    resolve_valuation_memo_block_exchange_rate,
    resolve_valuation_memo_block_timestamp_seconds,
    resolve_valuation_memo_date_exchange_rate,
    resolve_valuation_memo_historical_asset_price_usd,
)
from src.core.aavesentinel.position.aave_sentinel_position_reserve_registry_service import load_aave_sentinel_reserve_registry
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_protocol_reader import AaveProtocolReader
from src.integrations.chainlink.chainlink_client import ChainlinkClient
from src.integrations.frankfurter.frankfurter_client import FrankfurterClient
from src.integrations.routescan.routescan_client import RoutescanClient
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelCapitalFlowUsdValuationResolver:
    def __init__(self, valuation_memo: AaveSentinelCapitalFlowValuationMemo) -> None:
        self._valuation_memo = valuation_memo

    def resolve_amount_usd(self, valuation_context: AaveSentinelCapitalFlowValuationContext) -> float:
        if valuation_context.requires_euro_conversion:
            euro_conversion_context = AaveSentinelEuroConversionContext(
                block_number=valuation_context.block_number,
                timestamp_seconds=valuation_context.timestamp_seconds,
            )
            exchange_rate = self._resolve_euro_exchange_rate(
                conversion_context=euro_conversion_context,
            )
            return valuation_context.token_amount * exchange_rate

        oracle_contract_address = self._resolve_oracle_contract_address(
            contract_address=valuation_context.contract_address,
            asset_symbol=valuation_context.asset_symbol,
        )
        price_lookup_key = build_historical_asset_price_lookup_key(
            block_number=valuation_context.block_number,
            contract_address=oracle_contract_address,
        )
        asset_price_usd = resolve_valuation_memo_historical_asset_price_usd(
            valuation_memo=self._valuation_memo,
            lookup_key=price_lookup_key,
        )
        if asset_price_usd is None:
            raise RuntimeError(
                f"Missing USD price for asset {valuation_context.asset_symbol} "
                f"at block {valuation_context.block_number}",
            )
        return valuation_context.token_amount * asset_price_usd

    def _resolve_euro_exchange_rate(self, conversion_context: AaveSentinelEuroConversionContext) -> float:
        cached_block_rate = resolve_valuation_memo_block_exchange_rate(
            valuation_memo=self._valuation_memo,
            block_number=conversion_context.block_number,
        )
        if cached_block_rate is not None:
            return cached_block_rate

        exchange_rate_date = datetime.fromtimestamp(
            conversion_context.timestamp_seconds,
        ).astimezone().strftime("%Y-%m-%d")
        cached_date_rate = resolve_valuation_memo_date_exchange_rate(
            valuation_memo=self._valuation_memo,
            exchange_rate_date=exchange_rate_date,
        )
        if cached_date_rate is not None:
            remember_valuation_memo_block_exchange_rate(
                valuation_memo=self._valuation_memo,
                block_number=conversion_context.block_number,
                exchange_rate=cached_date_rate,
            )
            return cached_date_rate

        raise RuntimeError(
            f"Missing EUR to USD exchange rate for block {conversion_context.block_number} "
            f"date {exchange_rate_date}",
        )

    def _resolve_oracle_contract_address(
            self,
            contract_address: Optional[str],
            asset_symbol: str,
    ) -> str:
        if contract_address is not None:
            return contract_address
        if asset_symbol == NATIVE_AVAX_ASSET_SYMBOL:
            return WAVAX_CONTRACT_ADDRESS
        raise RuntimeError(f"Cannot resolve oracle contract address for asset {asset_symbol}")


class AaveSentinelCapitalFlowService:
    def __init__(
            self,
            wallet_address: str,
            valuation_memo: Optional[AaveSentinelCapitalFlowValuationMemo] = None,
            aave_protocol_reader: Optional[AaveProtocolReader] = None,
    ) -> None:
        self._wallet_address: str = wallet_address.lower()
        self._routescan_client = RoutescanClient(wallet_address=self._wallet_address)
        self._aave_protocol_reader = aave_protocol_reader if aave_protocol_reader is not None else AaveProtocolReader()
        self._owns_aave_protocol_reader: bool = aave_protocol_reader is None
        self._chainlink_client = ChainlinkClient()
        self._frankfurter_client = FrankfurterClient()
        self._refresh_lock = asyncio.Lock()
        self._valuation_memo: AaveSentinelCapitalFlowValuationMemo = (
            valuation_memo if valuation_memo is not None else create_empty_capital_flow_valuation_memo()
        )
        self._reserve_registry: Optional[AaveSentinelReserveRegistry] = None
        self._last_universal_ledger: Optional[AaveSentinelUniversalLedger] = None

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    @property
    def valuation_memo(self) -> AaveSentinelCapitalFlowValuationMemo:
        return self._valuation_memo

    @property
    def last_universal_ledger(self) -> Optional[AaveSentinelUniversalLedger]:
        return self._last_universal_ledger

    async def close(self) -> None:
        await self._routescan_client.close()
        if self._owns_aave_protocol_reader:
            await self._aave_protocol_reader.close()
        await self._chainlink_client.close()
        await self._frankfurter_client.close()

    async def build_capital_flow_summary(
            self,
            universal_ledger: Optional[AaveSentinelUniversalLedger] = None,
    ) -> AaveSentinelCapitalFlowSummary:
        async with self._refresh_lock:
            return await self._build_capital_flow_summary_without_lock(
                universal_ledger=universal_ledger,
            )

    async def _build_capital_flow_summary_without_lock(
            self,
            universal_ledger: Optional[AaveSentinelUniversalLedger] = None,
    ) -> AaveSentinelCapitalFlowSummary:
        if not self._wallet_address:
            return create_empty_capital_flow_summary()

        refresh_started_at = get_current_local_datetime()
        logger.debug("[AAVESENTINEL][CAPITALFLOW] Ledger refresh started for wallet %s", self._wallet_address)

        if universal_ledger is None:
            normal_transactions = await self._routescan_client.fetch_all_normal_transactions()
            internal_transactions = await self._routescan_client.fetch_all_internal_transactions()
            token_transactions = await self._routescan_client.fetch_all_token_transactions()
            universal_ledger = build_universal_ledger(
                wallet_address=self._wallet_address,
                normal_transactions=normal_transactions,
                internal_transactions=internal_transactions,
                token_transactions=token_transactions,
            )
        self._last_universal_ledger = universal_ledger

        reserve_registry = await self._resolve_reserve_registry()
        unfiltered_raw_flow_events = collect_pure_capital_flow_events(
            universal_ledger=universal_ledger,
            reserve_registry=reserve_registry,
        )
        raw_flow_events, excluded_flow_events = filter_oracle_priceable_capital_flow_events(
            raw_flow_events=unfiltered_raw_flow_events,
            reserve_registry=reserve_registry,
        )
        for excluded_flow_event in excluded_flow_events:
            logger.debug(
                "[AAVESENTINEL][CAPITALFLOW][ORACLE] Excluding non-oracle capital flow "
                "asset=%s contract=%s block=%d transaction=%s",
                excluded_flow_event.asset_symbol,
                excluded_flow_event.contract_address,
                excluded_flow_event.block_number,
                excluded_flow_event.transaction_hash,
            )

        euro_block_numbers: list[int] = []
        oracle_price_requests: list[AaveSentinelHistoricalAssetPriceLookupKey] = []

        for raw_flow_event in raw_flow_events:
            if raw_flow_event.requires_euro_conversion:
                euro_block_numbers.append(raw_flow_event.block_number)
                remember_valuation_memo_block_timestamp_seconds(
                    valuation_memo=self._valuation_memo,
                    block_number=raw_flow_event.block_number,
                    timestamp_seconds=raw_flow_event.timestamp_seconds,
                )
                continue

            oracle_contract_address = self._resolve_oracle_contract_address_for_raw_event(
                contract_address=raw_flow_event.contract_address,
                asset_symbol=raw_flow_event.asset_symbol,
            )
            oracle_price_requests.append(
                build_historical_asset_price_lookup_key(
                    block_number=raw_flow_event.block_number,
                    contract_address=oracle_contract_address,
                )
            )

        await self._preload_euro_exchange_rates(block_numbers=euro_block_numbers)
        await self._preload_oracle_asset_prices(oracle_price_requests=oracle_price_requests)

        valuation_resolver = AaveSentinelCapitalFlowUsdValuationResolver(
            valuation_memo=self._valuation_memo,
        )

        valued_raw_flow_events: list[AaveSentinelRawCapitalFlowEvent] = []
        for raw_flow_event in raw_flow_events:
            if raw_flow_event.requires_euro_conversion:
                valued_raw_flow_events.append(raw_flow_event)
                continue
            oracle_contract_address = self._resolve_oracle_contract_address_for_raw_event(
                contract_address=raw_flow_event.contract_address,
                asset_symbol=raw_flow_event.asset_symbol,
            )
            price_lookup_key = build_historical_asset_price_lookup_key(
                block_number=raw_flow_event.block_number,
                contract_address=oracle_contract_address,
            )
            if resolve_valuation_memo_historical_asset_price_usd(
                    valuation_memo=self._valuation_memo,
                    lookup_key=price_lookup_key,
            ) is None:
                logger.warning(
                    "[AAVESENTINEL][CAPITALFLOW][ORACLE] Dropping unpriced capital flow "
                    "asset=%s contract=%s block=%d",
                    raw_flow_event.asset_symbol,
                    raw_flow_event.contract_address,
                    raw_flow_event.block_number,
                )
                continue
            valued_raw_flow_events.append(raw_flow_event)

        classified_flows = convert_raw_capital_flow_events_to_classified_flows(
            raw_flow_events=valued_raw_flow_events,
            valuation_resolver=valuation_resolver,
        )

        aggregated_summary = aggregate_capital_flow_summary(
            classified_flows=classified_flows,
            is_available=True,
        )
        aggregated_summary.refreshed_at = refresh_started_at

        refresh_duration_seconds = (get_current_local_datetime() - refresh_started_at).total_seconds()
        logger.debug(
            "[AAVESENTINEL][CAPITALFLOW] Ledger refresh completed in %0.2fs "
            "inflow_usd=%0.2f outflow_usd=%0.2f net_capital_usd=%0.2f classified_flow_count=%d",
            refresh_duration_seconds,
            aggregated_summary.total_inflow_usd,
            aggregated_summary.total_outflow_usd,
            aggregated_summary.net_capital_deployed_usd,
            len(classified_flows),
        )
        return aggregated_summary

    async def _preload_euro_exchange_rates(self, block_numbers: list[int]) -> None:
        unique_block_numbers = sorted(set(block_numbers))
        for block_number in unique_block_numbers:
            if resolve_valuation_memo_block_exchange_rate(
                    valuation_memo=self._valuation_memo,
                    block_number=block_number,
            ) is not None:
                continue

            timestamp_seconds = resolve_valuation_memo_block_timestamp_seconds(
                valuation_memo=self._valuation_memo,
                block_number=block_number,
            )
            if timestamp_seconds is None:
                raise RuntimeError(f"Missing timestamp for block {block_number}")

            exchange_rate_date = datetime.fromtimestamp(timestamp_seconds).astimezone().strftime("%Y-%m-%d")
            cached_date_rate = resolve_valuation_memo_date_exchange_rate(
                valuation_memo=self._valuation_memo,
                exchange_rate_date=exchange_rate_date,
            )
            if cached_date_rate is not None:
                remember_valuation_memo_block_exchange_rate(
                    valuation_memo=self._valuation_memo,
                    block_number=block_number,
                    exchange_rate=cached_date_rate,
                )
                continue

            chainlink_rate = await self._chainlink_client.fetch_euro_to_usd_rate_at_block(
                block_number=block_number,
            )
            if chainlink_rate is not None:
                remember_valuation_memo_block_exchange_rate(
                    valuation_memo=self._valuation_memo,
                    block_number=block_number,
                    exchange_rate=chainlink_rate,
                )
                remember_valuation_memo_date_exchange_rate(
                    valuation_memo=self._valuation_memo,
                    exchange_rate_date=exchange_rate_date,
                    exchange_rate=chainlink_rate,
                )
                continue

            frankfurter_rate = await self._frankfurter_client.fetch_euro_to_usd_rate_for_date(
                exchange_rate_date=exchange_rate_date,
            )
            remember_valuation_memo_block_exchange_rate(
                valuation_memo=self._valuation_memo,
                block_number=block_number,
                exchange_rate=frankfurter_rate,
            )
            remember_valuation_memo_date_exchange_rate(
                valuation_memo=self._valuation_memo,
                exchange_rate_date=exchange_rate_date,
                exchange_rate=frankfurter_rate,
            )

    async def _preload_oracle_asset_prices(
            self,
            oracle_price_requests: list[AaveSentinelHistoricalAssetPriceLookupKey],
    ) -> None:
        unique_requests = sorted(
            set(oracle_price_requests),
            key=lambda lookup_key: (lookup_key.block_number, lookup_key.contract_address),
        )
        unresolved_price_lookup_keys: list[AaveSentinelHistoricalAssetPriceLookupKey] = []
        for price_lookup_key in unique_requests:
            if resolve_valuation_memo_historical_asset_price_usd(
                    valuation_memo=self._valuation_memo,
                    lookup_key=price_lookup_key,
            ) is not None:
                continue
            unresolved_price_lookup_keys.append(price_lookup_key)

        processed_block_numbers: list[int] = []
        for price_lookup_key in unresolved_price_lookup_keys:
            if price_lookup_key.block_number in processed_block_numbers:
                continue
            processed_block_numbers.append(price_lookup_key.block_number)
            contract_addresses: list[str] = [
                unresolved_price_lookup_key.contract_address
                for unresolved_price_lookup_key in unresolved_price_lookup_keys
                if unresolved_price_lookup_key.block_number == price_lookup_key.block_number
            ]
            fetched_asset_price_usd_snapshots = (
                await self._aave_protocol_reader.fetch_asset_prices_usd_at_block_batch(
                    contract_addresses=contract_addresses,
                    block_number=price_lookup_key.block_number,
                )
            )
            for contract_address in contract_addresses:
                asset_price_usd: Optional[float] = None
                normalized_contract_address = contract_address.lower()
                for fetched_asset_price_usd_snapshot in fetched_asset_price_usd_snapshots:
                    if fetched_asset_price_usd_snapshot.contract_address == normalized_contract_address:
                        asset_price_usd = fetched_asset_price_usd_snapshot.asset_price_usd
                        break
                if asset_price_usd is None:
                    logger.warning(
                        "[AAVESENTINEL][CAPITALFLOW][ORACLE] Skipping unresolved oracle price "
                        "contract=%s block=%d",
                        contract_address,
                        price_lookup_key.block_number,
                    )
                    continue
                remember_valuation_memo_historical_asset_price_usd(
                    valuation_memo=self._valuation_memo,
                    lookup_key=build_historical_asset_price_lookup_key(
                        block_number=price_lookup_key.block_number,
                        contract_address=contract_address,
                    ),
                    asset_price_usd=asset_price_usd,
                )

    async def _resolve_reserve_registry(self) -> AaveSentinelReserveRegistry:
        if self._reserve_registry is None:
            self._reserve_registry = await load_aave_sentinel_reserve_registry()
        return self._reserve_registry

    def _resolve_oracle_contract_address_for_raw_event(
            self,
            contract_address: Optional[str],
            asset_symbol: str,
    ) -> str:
        if contract_address is not None:
            return contract_address
        if asset_symbol == NATIVE_AVAX_ASSET_SYMBOL:
            return WAVAX_CONTRACT_ADDRESS
        raise RuntimeError(f"Cannot resolve oracle contract address for asset {asset_symbol}")
