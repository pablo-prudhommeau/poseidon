from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import httpx
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_constants import (
    AVALANCHE_EURC_USD_CHAINLINK_FEED_ADDRESS,
    FRANKFURTER_HISTORICAL_EXCHANGE_RATE_URL_TEMPLATE,
    NATIVE_AVAX_ASSET_SYMBOL,
    WAVAX_CONTRACT_ADDRESS,
)
from src.core.aavesentinel.aave_sentinel_helpers import (
    aggregate_capital_flow_summary,
    build_historical_asset_price_lookup_key,
    build_universal_ledger,
    collect_pure_capital_flow_events,
    convert_raw_capital_flow_events_to_classified_flows,
    create_empty_capital_flow_summary,
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
from src.core.aavesentinel.aave_sentinel_reserve_registry_service import load_aave_sentinel_reserve_registry
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelCapitalFlowValuationContext,
    AaveSentinelCapitalFlowValuationMemo,
    AaveSentinelEuroConversionContext,
    AaveSentinelFrankfurterExchangeRateResponse,
    AaveSentinelHistoricalAssetPriceLookupKey,
    AaveSentinelReserveRegistry,
)
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_abis import AAVE_ORACLE_ABI, ADDRESS_PROVIDER_ABI, AAVE_POOL_ABI
from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain
from src.integrations.chainlink.chainlink_abis import CHAINLINK_AGGREGATOR_V3_ABI
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
    def __init__(self, wallet_address: str) -> None:
        self._wallet_address: str = wallet_address.lower()
        self._routescan_client = RoutescanClient(wallet_address=self._wallet_address)
        self._refresh_lock = asyncio.Lock()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._web3_client: Optional[AsyncWeb3] = None
        self._oracle_contract: Optional[AsyncContract] = None
        self._pool_contract: Optional[AsyncContract] = None
        self._eurc_usd_chainlink_contract: Optional[AsyncContract] = None
        self._chainlink_price_decimal_count: Optional[int] = None
        self._valuation_memo: AaveSentinelCapitalFlowValuationMemo = create_empty_capital_flow_valuation_memo()
        self._reserve_registry: Optional[AaveSentinelReserveRegistry] = None

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    async def close(self) -> None:
        await self._routescan_client.close()
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def build_capital_flow_summary(self) -> AaveSentinelCapitalFlowSummary:
        async with self._refresh_lock:
            return await self._build_capital_flow_summary_without_lock()

    async def _build_capital_flow_summary_without_lock(self) -> AaveSentinelCapitalFlowSummary:
        if not self._wallet_address:
            return create_empty_capital_flow_summary()

        refresh_started_at = get_current_local_datetime()
        logger.debug("[AAVESENTINEL][CAPITALFLOW] Ledger refresh started for wallet %s", self._wallet_address)

        normal_transactions = await self._routescan_client.fetch_all_normal_transactions()
        internal_transactions = await self._routescan_client.fetch_all_internal_transactions()
        token_transactions = await self._routescan_client.fetch_all_token_transactions()

        universal_ledger = build_universal_ledger(
            wallet_address=self._wallet_address,
            normal_transactions=normal_transactions,
            internal_transactions=internal_transactions,
            token_transactions=token_transactions,
        )

        reserve_registry = await self._resolve_reserve_registry()
        raw_flow_events = collect_pure_capital_flow_events(
            universal_ledger=universal_ledger,
            reserve_registry=reserve_registry,
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

        classified_flows = convert_raw_capital_flow_events_to_classified_flows(
            raw_flow_events=raw_flow_events,
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

            chainlink_rate = await self._fetch_chainlink_euro_to_usd_rate_at_block(block_number=block_number)
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

            frankfurter_rate = await self._fetch_frankfurter_euro_to_usd_rate_for_date(
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
        for price_lookup_key in unique_requests:
            if resolve_valuation_memo_historical_asset_price_usd(
                    valuation_memo=self._valuation_memo,
                    lookup_key=price_lookup_key,
            ) is not None:
                continue

            asset_price_usd = await self._fetch_aave_oracle_asset_price_usd_at_block(
                block_number=price_lookup_key.block_number,
                contract_address=price_lookup_key.contract_address,
            )
            if asset_price_usd is None:
                raise RuntimeError(
                    f"Failed to resolve Aave oracle price for {price_lookup_key.contract_address} "
                    f"at block {price_lookup_key.block_number}",
                )
            remember_valuation_memo_historical_asset_price_usd(
                valuation_memo=self._valuation_memo,
                lookup_key=price_lookup_key,
                asset_price_usd=asset_price_usd,
            )

    async def _ensure_aave_oracle_contract(self) -> None:
        if self._oracle_contract is not None:
            return

        await self._ensure_aave_pool_contract()
        if self._pool_contract is None or self._web3_client is None:
            return

        addresses_provider_address = await self._pool_contract.functions.ADDRESSES_PROVIDER().call()
        addresses_provider_contract = self._web3_client.eth.contract(
            address=addresses_provider_address,
            abi=ADDRESS_PROVIDER_ABI,
        )
        oracle_contract_address = await addresses_provider_contract.functions.getPriceOracle().call()
        self._oracle_contract = self._web3_client.eth.contract(
            address=oracle_contract_address,
            abi=AAVE_ORACLE_ABI,
        )

    async def _ensure_aave_pool_contract(self) -> None:
        if self._pool_contract is not None:
            return

        self._web3_client = resolve_async_web3_provider_for_chain(BlockchainNetwork.AVALANCHE)
        pool_contract_address = AsyncWeb3.to_checksum_address(settings.AAVE_POOL_V3_ADDRESS)
        self._pool_contract = self._web3_client.eth.contract(
            address=pool_contract_address,
            abi=AAVE_POOL_ABI,
        )

    async def _resolve_reserve_registry(self) -> AaveSentinelReserveRegistry:
        if self._reserve_registry is None:
            self._reserve_registry = await load_aave_sentinel_reserve_registry()
        return self._reserve_registry

    async def _fetch_aave_oracle_asset_price_usd_at_block(
            self,
            block_number: int,
            contract_address: str,
    ) -> Optional[float]:
        try:
            await self._ensure_aave_oracle_contract()
            if self._oracle_contract is None:
                return None

            checksum_contract_address = AsyncWeb3.to_checksum_address(contract_address)
            raw_asset_price_base = await self._oracle_contract.functions.getAssetPrice(
                checksum_contract_address,
            ).call(block_identifier=block_number)
            if int(raw_asset_price_base) <= 0:
                return None

            asset_price_usd = int(raw_asset_price_base) / 1e8
            logger.debug(
                "[AAVESENTINEL][CAPITALFLOW][ORACLE] Asset price resolved contract=%s block=%d price=%0.6f",
                contract_address,
                block_number,
                asset_price_usd,
            )
            return asset_price_usd
        except Exception as exception:
            logger.debug(
                "[AAVESENTINEL][CAPITALFLOW][ORACLE] Historical lookup failed contract=%s block=%d: %s",
                contract_address,
                block_number,
                exception,
            )
            return None

    async def _ensure_chainlink_contract(self) -> None:
        if self._eurc_usd_chainlink_contract is not None:
            return

        self._web3_client = resolve_async_web3_provider_for_chain(BlockchainNetwork.AVALANCHE)
        checksum_feed_address = AsyncWeb3.to_checksum_address(AVALANCHE_EURC_USD_CHAINLINK_FEED_ADDRESS)
        self._eurc_usd_chainlink_contract = self._web3_client.eth.contract(
            address=checksum_feed_address,
            abi=CHAINLINK_AGGREGATOR_V3_ABI,
        )
        self._chainlink_price_decimal_count = int(
            await self._eurc_usd_chainlink_contract.functions.decimals().call(),
        )

    async def _fetch_chainlink_euro_to_usd_rate_at_block(self, block_number: int) -> Optional[float]:
        try:
            await self._ensure_chainlink_contract()
            if self._eurc_usd_chainlink_contract is None or self._chainlink_price_decimal_count is None:
                return None

            round_data = await self._eurc_usd_chainlink_contract.functions.latestRoundData().call(
                block_identifier=block_number,
            )
            raw_price = int(round_data[1])
            if raw_price <= 0:
                return None

            normalized_price = raw_price / (10 ** self._chainlink_price_decimal_count)
            logger.debug(
                "[AAVESENTINEL][CAPITALFLOW][FX] Chainlink EURC/USD rate resolved block=%d rate=%0.6f",
                block_number,
                normalized_price,
            )
            return normalized_price
        except Exception as exception:
            logger.debug(
                "[AAVESENTINEL][CAPITALFLOW][FX] Chainlink historical lookup failed for block %d: %s",
                block_number,
                exception,
            )
            return None

    async def _fetch_frankfurter_euro_to_usd_rate_for_date(self, exchange_rate_date: str) -> float:
        cached_rate = resolve_valuation_memo_date_exchange_rate(
            valuation_memo=self._valuation_memo,
            exchange_rate_date=exchange_rate_date,
        )
        if cached_rate is not None:
            return cached_rate

        request_url = FRANKFURTER_HISTORICAL_EXCHANGE_RATE_URL_TEMPLATE.format(
            exchange_rate_date=exchange_rate_date,
        )

        try:
            http_client = await self._get_http_client()
            response = await http_client.get(request_url)
            response.raise_for_status()
            response_payload = AaveSentinelFrankfurterExchangeRateResponse.model_validate(response.json())
            if response_payload.rates.USD is None:
                raise RuntimeError(f"Frankfurter response missing USD rate for date {exchange_rate_date}")
            exchange_rate = response_payload.rates.USD
            remember_valuation_memo_date_exchange_rate(
                valuation_memo=self._valuation_memo,
                exchange_rate_date=exchange_rate_date,
                exchange_rate=exchange_rate,
            )
            logger.debug(
                "[AAVESENTINEL][CAPITALFLOW][FX] Frankfurter EUR/USD rate resolved date=%s rate=%0.6f",
                exchange_rate_date,
                exchange_rate,
            )
            return exchange_rate
        except Exception as exception:
            logger.exception(
                "[AAVESENTINEL][CAPITALFLOW][FX] Frankfurter lookup failed for date %s: %s",
                exchange_rate_date,
                exception,
            )
            raise

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

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
