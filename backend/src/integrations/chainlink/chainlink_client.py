from __future__ import annotations

from typing import Optional

from web3 import AsyncWeb3
from web3.contract import AsyncContract

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain
from src.integrations.chainlink.chainlink_abis import CHAINLINK_AGGREGATOR_V3_ABI
from src.integrations.chainlink.chainlink_constants import AVALANCHE_EURC_USD_CHAINLINK_FEED_ADDRESS
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class ChainlinkClient:
    def __init__(self) -> None:
        self._web3_client: Optional[AsyncWeb3] = None
        self._eurc_usd_chainlink_contract: Optional[AsyncContract] = None
        self._chainlink_price_decimal_count: Optional[int] = None

    async def close(self) -> None:
        self._web3_client = None
        self._eurc_usd_chainlink_contract = None
        self._chainlink_price_decimal_count = None

    async def fetch_euro_to_usd_rate_at_block(self, block_number: int) -> Optional[float]:
        try:
            await self._ensure_eurc_usd_contract()
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
                "[CHAINLINK][FX] EURC/USD rate resolved block=%d rate=%0.6f",
                block_number,
                normalized_price,
            )
            return normalized_price
        except Exception as exception:
            logger.debug(
                "[CHAINLINK][FX] Historical lookup failed for block %d: %s",
                block_number,
                exception,
            )
            return None

    async def _ensure_eurc_usd_contract(self) -> None:
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
