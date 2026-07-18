from __future__ import annotations

import asyncio
from typing import Optional

from web3 import AsyncWeb3
from web3.contract import AsyncContract

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_constants import EURO_STABLECOIN_SYMBOLS
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelReserveAsset,
    AaveSentinelReserveRegistry,
)
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_abis import (
    AAVE_POOL_ABI,
    ERC20_ABI,
)
from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_cached_reserve_registry: Optional[AaveSentinelReserveRegistry] = None
_reserve_registry_lock = asyncio.Lock()


async def load_aave_sentinel_reserve_registry(force_refresh: bool = False) -> AaveSentinelReserveRegistry:
    global _cached_reserve_registry

    if _cached_reserve_registry is not None and not force_refresh:
        return _cached_reserve_registry

    async with _reserve_registry_lock:
        if _cached_reserve_registry is not None and not force_refresh:
            return _cached_reserve_registry

        loaded_registry = await _build_aave_sentinel_reserve_registry()
        _cached_reserve_registry = loaded_registry
        return loaded_registry


async def _build_aave_sentinel_reserve_registry() -> AaveSentinelReserveRegistry:
    try:
        web3_client = resolve_async_web3_provider_for_chain(BlockchainNetwork.AVALANCHE)
        pool_contract_address = AsyncWeb3.to_checksum_address(settings.AAVE_POOL_V3_ADDRESS)
        pool_contract = web3_client.eth.contract(address=pool_contract_address, abi=AAVE_POOL_ABI)

        reserve_underlying_addresses = await pool_contract.functions.getReservesList().call()
        reserve_assets: list[AaveSentinelReserveAsset] = []

        for reserve_underlying_address in reserve_underlying_addresses:
            reserve_asset = await _load_aave_reserve_asset(
                reserve_underlying_address=reserve_underlying_address,
                pool_contract=pool_contract,
                web3_client=web3_client,
            )
            if reserve_asset is not None:
                reserve_assets.append(reserve_asset)

        logger.debug(
            "[AAVESENTINEL][RESERVES] Loaded %d Aave reserve assets (%d euro stable)",
            len(reserve_assets),
            sum(1 for reserve_asset in reserve_assets if reserve_asset.requires_euro_conversion),
        )
        return AaveSentinelReserveRegistry(reserve_assets=tuple(reserve_assets))
    except Exception as exception:
        logger.exception("[AAVESENTINEL][RESERVES] Failed to load Aave reserve registry: %s", exception)
        return AaveSentinelReserveRegistry()


async def _load_aave_reserve_asset(
        reserve_underlying_address: str,
        pool_contract: AsyncContract,
        web3_client: AsyncWeb3,
) -> AaveSentinelReserveAsset | None:
    try:
        underlying_checksum_address = AsyncWeb3.to_checksum_address(reserve_underlying_address)
        reserve_data = await pool_contract.functions.getReserveData(underlying_checksum_address).call()
        underlying_token_contract = web3_client.eth.contract(address=underlying_checksum_address, abi=ERC20_ABI)

        asset_symbol, decimal_count = await asyncio.gather(
            underlying_token_contract.functions.symbol().call(),
            underlying_token_contract.functions.decimals().call(),
        )

        return AaveSentinelReserveAsset(
            underlying_address=underlying_checksum_address.lower(),
            symbol=str(asset_symbol),
            decimal_count=int(decimal_count),
            requires_euro_conversion=str(asset_symbol).strip().upper() in EURO_STABLECOIN_SYMBOLS,
            a_token_address=str(reserve_data[8]).lower(),
            stable_debt_token_address=str(reserve_data[9]).lower(),
            variable_debt_token_address=str(reserve_data[10]).lower(),
        )
    except Exception as exception:
        logger.debug(
            "[AAVESENTINEL][RESERVES] Failed to load reserve asset %s: %s",
            reserve_underlying_address,
            exception,
        )
        return None
