from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import httpx
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_fiat_flow_structures import (
    AaveSentinelFiatFlowSummary,
    AaveSentinelTrackedStablecoin,
    build_default_tracked_stablecoins,
    create_empty_fiat_flow_summary,
)
from src.core.aavesentinel.aave_sentinel_fiat_flow_utils import (
    aggregate_fiat_flow_summary,
    build_universal_ledger,
    collect_pure_fiat_flow_events,
    convert_raw_fiat_flow_events_to_classified_flows,
)
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain
from src.integrations.chainlink.chainlink_abis import CHAINLINK_AGGREGATOR_V3_ABI
from src.integrations.routescan.routescan_client import RoutescanClient
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

AVALANCHE_EURC_USD_CHAINLINK_FEED_ADDRESS: str = "0x59728a5067d519b5F169c824c965eD684d5E5170"
FRANKFURTER_HISTORICAL_EXCHANGE_RATE_URL_TEMPLATE: str = "https://api.frankfurter.dev/v1/{exchange_rate_date}?from=EUR&to=USD"


class AaveSentinelFiatFlowService:
    def __init__(self, wallet_address: str) -> None:
        self._wallet_address: str = wallet_address.lower()
        self._routescan_client = RoutescanClient(wallet_address=self._wallet_address)
        self._tracked_stablecoins: list[AaveSentinelTrackedStablecoin] = build_default_tracked_stablecoins()
        self._cached_summary: AaveSentinelFiatFlowSummary = create_empty_fiat_flow_summary()
        self._refresh_lock = asyncio.Lock()
        self._background_refresh_task: Optional[asyncio.Task[None]] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._web3_client: Optional[AsyncWeb3] = None
        self._eurc_usd_chainlink_contract: Optional[AsyncContract] = None
        self._chainlink_price_decimal_count: Optional[int] = None
        self._exchange_rate_by_block_number: dict[int, float] = {}
        self._exchange_rate_by_date: dict[str, float] = {}

    async def close(self) -> None:
        if self._background_refresh_task is not None:
            self._background_refresh_task.cancel()
            try:
                await self._background_refresh_task
            except asyncio.CancelledError:
                pass
            self._background_refresh_task = None

        await self._routescan_client.close()
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def refresh_ledger(self) -> AaveSentinelFiatFlowSummary:
        async with self._refresh_lock:
            return await self._refresh_ledger_without_lock()

    async def get_summary(self) -> AaveSentinelFiatFlowSummary:
        if self._cached_summary.is_available and self._cached_summary.refreshed_at is not None:
            seconds_since_refresh = (
                get_current_local_datetime() - self._cached_summary.refreshed_at
            ).total_seconds()
            if seconds_since_refresh > settings.AAVE_SENTINEL_FIAT_FLOW_REFRESH_SECONDS:
                self._schedule_background_refresh()

        if not self._cached_summary.is_available:
            return await self.refresh_ledger()

        return self._cached_summary

    def _schedule_background_refresh(self) -> None:
        if self._background_refresh_task is not None and not self._background_refresh_task.done():
            return

        self._background_refresh_task = asyncio.create_task(self._run_background_refresh())

    async def _run_background_refresh(self) -> None:
        try:
            await self.refresh_ledger()
        except Exception as exception:
            logger.exception(
                "[AAVESENTINEL][FIATFLOW] Background refresh failed: %s",
                exception,
            )

    async def _refresh_ledger_without_lock(self) -> AaveSentinelFiatFlowSummary:
        refresh_started_at = get_current_local_datetime()
        logger.debug("[AAVESENTINEL][FIATFLOW] Ledger refresh started for wallet %s", self._wallet_address)

        normal_transactions = await self._routescan_client.fetch_all_normal_transactions()
        internal_transactions = await self._routescan_client.fetch_all_internal_transactions()
        token_transactions = await self._routescan_client.fetch_all_token_transactions()

        ledger_by_transaction_hash = build_universal_ledger(
            wallet_address=self._wallet_address,
            normal_transactions=normal_transactions,
            internal_transactions=internal_transactions,
            token_transactions=token_transactions,
        )

        raw_flow_events = collect_pure_fiat_flow_events(
            ledger_by_transaction_hash=ledger_by_transaction_hash,
            tracked_stablecoins=self._tracked_stablecoins,
        )

        euro_block_numbers: list[int] = []
        timestamp_seconds_by_block: dict[int, int] = {}
        for raw_flow_event in raw_flow_events:
            if not raw_flow_event.requires_euro_conversion:
                continue
            euro_block_numbers.append(raw_flow_event.block_number)
            timestamp_seconds_by_block[raw_flow_event.block_number] = raw_flow_event.timestamp_seconds

        await self.preload_euro_exchange_rates(
            block_numbers=euro_block_numbers,
            timestamp_seconds_by_block=timestamp_seconds_by_block,
        )

        classified_flows = convert_raw_fiat_flow_events_to_classified_flows(
            raw_flow_events=raw_flow_events,
            resolve_euro_to_usd_exchange_rate=self._resolve_euro_to_usd_exchange_rate,
        )

        aggregated_summary = aggregate_fiat_flow_summary(
            classified_flows=classified_flows,
            tracked_stablecoins=self._tracked_stablecoins,
            is_available=True,
        )
        aggregated_summary.refreshed_at = refresh_started_at
        self._cached_summary = aggregated_summary

        refresh_duration_seconds = (get_current_local_datetime() - refresh_started_at).total_seconds()
        logger.info(
            "[AAVESENTINEL][FIATFLOW] Ledger refresh completed in %0.2fs "
            "inflow_usd=%0.2f outflow_usd=%0.2f net_capital_usd=%0.2f classified_flow_count=%d",
            refresh_duration_seconds,
            aggregated_summary.total_inflow_usd,
            aggregated_summary.total_outflow_usd,
            aggregated_summary.net_capital_deployed_usd,
            len(classified_flows),
        )
        return aggregated_summary

    def _resolve_euro_to_usd_exchange_rate(
            self,
            block_number: int,
            timestamp_seconds: int,
    ) -> float:
        cached_block_rate = self._exchange_rate_by_block_number.get(block_number)
        if cached_block_rate is not None:
            return cached_block_rate

        exchange_rate_date = datetime.fromtimestamp(timestamp_seconds).astimezone().strftime("%Y-%m-%d")
        cached_date_rate = self._exchange_rate_by_date.get(exchange_rate_date)
        if cached_date_rate is not None:
            self._exchange_rate_by_block_number[block_number] = cached_date_rate
            return cached_date_rate

        raise RuntimeError(
            f"Missing EUR to USD exchange rate for block {block_number} date {exchange_rate_date}",
        )

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

    async def preload_euro_exchange_rates(self, block_numbers: list[int], timestamp_seconds_by_block: dict[int, int]) -> None:
        unique_block_numbers = sorted(set(block_numbers))
        for block_number in unique_block_numbers:
            if block_number in self._exchange_rate_by_block_number:
                continue

            timestamp_seconds = timestamp_seconds_by_block[block_number]
            exchange_rate_date = datetime.fromtimestamp(timestamp_seconds).astimezone().strftime("%Y-%m-%d")
            if exchange_rate_date in self._exchange_rate_by_date:
                self._exchange_rate_by_block_number[block_number] = self._exchange_rate_by_date[exchange_rate_date]
                continue

            chainlink_rate = await self._fetch_chainlink_euro_to_usd_rate_at_block(block_number=block_number)
            if chainlink_rate is not None:
                self._exchange_rate_by_block_number[block_number] = chainlink_rate
                self._exchange_rate_by_date[exchange_rate_date] = chainlink_rate
                continue

            frankfurter_rate = await self._fetch_frankfurter_euro_to_usd_rate_for_date(
                exchange_rate_date=exchange_rate_date,
            )
            self._exchange_rate_by_block_number[block_number] = frankfurter_rate
            self._exchange_rate_by_date[exchange_rate_date] = frankfurter_rate

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
                "[AAVESENTINEL][FIATFLOW][FX] Chainlink EURC/USD rate resolved block=%d rate=%0.6f",
                block_number,
                normalized_price,
            )
            return normalized_price
        except Exception as exception:
            logger.debug(
                "[AAVESENTINEL][FIATFLOW][FX] Chainlink historical lookup failed for block %d: %s",
                block_number,
                exception,
            )
            return None

    async def _fetch_frankfurter_euro_to_usd_rate_for_date(self, exchange_rate_date: str) -> float:
        cached_rate = self._exchange_rate_by_date.get(exchange_rate_date)
        if cached_rate is not None:
            return cached_rate

        request_url = FRANKFURTER_HISTORICAL_EXCHANGE_RATE_URL_TEMPLATE.format(
            exchange_rate_date=exchange_rate_date,
        )

        try:
            http_client = await self._get_http_client()
            response = await http_client.get(request_url)
            response.raise_for_status()
            response_payload = response.json()
            exchange_rate = float(response_payload["rates"]["USD"])
            self._exchange_rate_by_date[exchange_rate_date] = exchange_rate
            logger.debug(
                "[AAVESENTINEL][FIATFLOW][FX] Frankfurter EUR/USD rate resolved date=%s rate=%0.6f",
                exchange_rate_date,
                exchange_rate,
            )
            return exchange_rate
        except Exception as exception:
            logger.exception(
                "[AAVESENTINEL][FIATFLOW][FX] Frankfurter lookup failed for date %s: %s",
                exchange_rate_date,
                exception,
            )
            raise

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client
