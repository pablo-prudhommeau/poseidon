from __future__ import annotations

import asyncio
from typing import Awaitable, Optional, TypeVar

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetSnapshot,
    AaveSentinelPositionSnapshot,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    convert_ray_to_annual_percentage_yield,
    decode_aave_reserve_liquidation_threshold,
)
from src.core.aavesentinel.position.aave_sentinel_position_reserve_registry_service import load_aave_sentinel_reserve_registry
from src.core.aavesentinel.position.aave_sentinel_position_strategy_helpers import resolve_active_strategies
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_abis import (
    ADDRESS_PROVIDER_ABI,
    AAVE_ORACLE_ABI,
    AAVE_POOL_ABI,
    ERC20_ABI,
)
from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

Account.enable_unaudited_hdwallet_features()

ProtectedCallResult = TypeVar("ProtectedCallResult")


class AaveSentinelSnapshotService:
    def __init__(self) -> None:
        self._web3_client: Optional[AsyncWeb3] = None
        self._pool_contract: Optional[AsyncContract] = None
        self._oracle_contract: Optional[AsyncContract] = None
        self._wallet_address: str = ""
        self._scan_semaphore = asyncio.Semaphore(settings.AAVE_SENTINEL_MAX_CONCURRENT_ASSET_SCANS)
        self._initialization_lock = asyncio.Lock()

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    def _is_fully_initialized(self) -> bool:
        return (
                self._web3_client is not None
                and self._pool_contract is not None
                and self._oracle_contract is not None
        )

    @property
    def is_initialized(self) -> bool:
        return self._is_fully_initialized()

    async def initialize(self) -> None:
        if self._is_fully_initialized():
            return

        async with self._initialization_lock:
            if self._is_fully_initialized():
                return

            if not self._wallet_address:
                self._derive_wallet_address()

            if self._web3_client is None:
                self._web3_client = resolve_async_web3_provider_for_chain(BlockchainNetwork.AVALANCHE)

            if self._pool_contract is None:
                pool_contract_address = AsyncWeb3.to_checksum_address(settings.AAVE_POOL_V3_ADDRESS)
                self._pool_contract = self._web3_client.eth.contract(
                    address=pool_contract_address,
                    abi=AAVE_POOL_ABI,
                )

            if self._oracle_contract is None:
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
                logger.debug(
                    "[AAVESENTINEL][INITIALIZATION] Oracle contract loaded at %s",
                    oracle_contract_address,
                )

    async def fetch_position_snapshot(self) -> Optional[AaveSentinelPositionSnapshot]:
        try:
            await self.initialize()
            if not self._wallet_address or not self._is_fully_initialized():
                logger.debug("[AAVESENTINEL][SNAPSHOT] Snapshot skipped because initialization is incomplete")
                return None

            wallet_checksum_address = AsyncWeb3.to_checksum_address(self._wallet_address)
            account_metrics = await self._pool_contract.functions.getUserAccountData(wallet_checksum_address).call()
            total_collateral_usd = account_metrics[0] / 1e8
            total_debt_usd = account_metrics[1] / 1e8
            raw_health_factor = account_metrics[5]

            normalized_health_factor = 999.0
            maximum_unbounded_health_factor = (2 ** 255) - 1
            if raw_health_factor < maximum_unbounded_health_factor:
                normalized_health_factor = raw_health_factor / 1e18

            logger.debug(
                "[AAVESENTINEL][SNAPSHOT] Core metrics resolved: health_factor=%0.2f collateral=$%0.2f debt=$%0.2f",
                normalized_health_factor,
                total_collateral_usd,
                total_debt_usd,
            )

            reserve_addresses = await self._pool_contract.functions.getReservesList().call()
            asset_scan_tasks = [
                self._scan_asset_snapshot(reserve_address, wallet_checksum_address)
                for reserve_address in reserve_addresses
            ]
            asset_scan_results = await asyncio.gather(*asset_scan_tasks)
            active_assets = [asset for asset in asset_scan_results if asset is not None]
            active_assets.sort(
                key=lambda asset_snapshot: asset_snapshot.supply_value_usd + asset_snapshot.wallet_value_usd,
                reverse=True,
            )

            active_strategies = resolve_active_strategies(
                detected_assets=active_assets,
                reserve_registry=await load_aave_sentinel_reserve_registry(),
            )

            return AaveSentinelPositionSnapshot(
                health_factor=normalized_health_factor,
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                strategies=active_strategies,
                assets=active_assets,
            )
        except Exception as exception:
            logger.exception("[AAVESENTINEL][SNAPSHOT] Snapshot acquisition failed: %s", exception)
            return None

    def _derive_wallet_address(self) -> None:
        wallet_mnemonic: str = settings.AAVE_SENTINEL_WALLET_MNEMONIC.strip()
        if not wallet_mnemonic:
            raise RuntimeError("AAVE_SENTINEL_WALLET_MNEMONIC is required to derive the sentinel wallet address")

        try:
            account_instance: LocalAccount = Account.from_mnemonic(
                mnemonic=wallet_mnemonic,
                account_path=f"m/44'/60'/0'/0/{settings.AAVE_SENTINEL_WALLET_DERIVATION_INDEX}",
            )
            self._wallet_address = account_instance.address
            logger.info("[AAVESENTINEL][CREDENTIALS] Wallet loaded for sentinel: %s", self._wallet_address)
        except Exception as exception:
            logger.exception("[AAVESENTINEL][CREDENTIALS] Wallet derivation failed: %s", exception)
            raise RuntimeError("Failed to derive the Aave sentinel wallet address from mnemonic") from exception

    async def _perform_protected_onchain_call(
            self,
            coroutine_operation: Awaitable[ProtectedCallResult],
            fallback_default_value: ProtectedCallResult,
            operation_label: str,
    ) -> ProtectedCallResult:
        try:
            return await coroutine_operation
        except Exception as exception:
            logger.debug("[AAVESENTINEL][RPC] On-chain call failed for %s: %s", operation_label, exception)
            return fallback_default_value

    async def _scan_asset_snapshot(
            self,
            asset_contract_address: str,
            target_user_address: str,
    ) -> Optional[AaveSentinelAssetSnapshot]:
        async with self._scan_semaphore:
            try:
                if self._pool_contract is None or self._web3_client is None or self._oracle_contract is None:
                    return None

                asset_checksum_address = AsyncWeb3.to_checksum_address(asset_contract_address)
                reserve_configuration = await self._pool_contract.functions.getReserveData(asset_checksum_address).call()
                reserve_configuration_bitmap = int(reserve_configuration[0])
                liquidity_rate_ray = reserve_configuration[2]
                variable_borrow_rate_ray = reserve_configuration[4]
                a_token_contract_address = reserve_configuration[8]
                variable_debt_token_contract_address = reserve_configuration[10]
                liquidation_threshold = decode_aave_reserve_liquidation_threshold(
                    configuration_bitmap=reserve_configuration_bitmap,
                )

                underlying_token_contract = self._web3_client.eth.contract(address=asset_checksum_address, abi=ERC20_ABI)
                a_token_contract = self._web3_client.eth.contract(address=a_token_contract_address, abi=ERC20_ABI)
                debt_token_contract = self._web3_client.eth.contract(
                    address=variable_debt_token_contract_address,
                    abi=ERC20_ABI,
                )

                asset_decimal_precision = await self._perform_protected_onchain_call(
                    underlying_token_contract.functions.decimals().call(),
                    18,
                    "fetch_asset_decimals",
                )

                raw_balances = await asyncio.gather(
                    a_token_contract.functions.balanceOf(target_user_address).call(),
                    debt_token_contract.functions.balanceOf(target_user_address).call(),
                    underlying_token_contract.functions.balanceOf(target_user_address).call(),
                    return_exceptions=True,
                )

                token_supply_balance = raw_balances[0] if not isinstance(raw_balances[0], Exception) else 0
                token_debt_balance = raw_balances[1] if not isinstance(raw_balances[1], Exception) else 0
                token_wallet_balance = raw_balances[2] if not isinstance(raw_balances[2], Exception) else 0

                asset_symbol = await self._perform_protected_onchain_call(
                    underlying_token_contract.functions.symbol().call(),
                    str(asset_checksum_address)[:6],
                    "fetch_asset_symbol",
                )
                raw_asset_price_base = await self._perform_protected_onchain_call(
                    self._oracle_contract.functions.getAssetPrice(asset_checksum_address).call(),
                    0,
                    "fetch_asset_price",
                )

                if asset_symbol == "WAVAX":
                    try:
                        native_balance = await self._web3_client.eth.get_balance(target_user_address)
                        token_wallet_balance += native_balance
                    except Exception as exception:
                        logger.exception("[AAVESENTINEL][SCAN] Failed to aggregate native AVAX balance: %s", exception)

                if token_supply_balance == 0 and token_debt_balance == 0 and token_wallet_balance == 0:
                    return None

                normalization_scale = 10 ** asset_decimal_precision
                normalized_supply_amount = token_supply_balance / normalization_scale
                normalized_debt_amount = token_debt_balance / normalization_scale
                normalized_wallet_amount = token_wallet_balance / normalization_scale
                asset_price_usd = raw_asset_price_base / 1e8

                supply_value_usd = normalized_supply_amount * asset_price_usd
                debt_value_usd = normalized_debt_amount * asset_price_usd
                wallet_value_usd = normalized_wallet_amount * asset_price_usd

                logger.debug(
                    "[AAVESENTINEL][SCAN] Asset resolved %s supply=$%0.2f debt=$%0.2f wallet=$%0.2f",
                    asset_symbol,
                    supply_value_usd,
                    debt_value_usd,
                    wallet_value_usd,
                )

                return AaveSentinelAssetSnapshot(
                    symbol=str(asset_symbol),
                    underlying_address=asset_checksum_address,
                    supply_amount=normalized_supply_amount,
                    debt_amount=normalized_debt_amount,
                    wallet_amount=normalized_wallet_amount,
                    supply_value_usd=supply_value_usd,
                    debt_value_usd=debt_value_usd,
                    wallet_value_usd=wallet_value_usd,
                    supply_annual_percentage_yield=convert_ray_to_annual_percentage_yield(liquidity_rate_ray),
                    borrow_annual_percentage_yield=convert_ray_to_annual_percentage_yield(variable_borrow_rate_ray),
                    liquidation_threshold=liquidation_threshold,
                )
            except Exception as exception:
                logger.exception(
                    "[AAVESENTINEL][SCAN] Asset scan failed for %s and will be skipped: %s",
                    asset_contract_address,
                    exception,
                )
                return None
