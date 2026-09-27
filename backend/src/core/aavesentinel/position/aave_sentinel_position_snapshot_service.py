from __future__ import annotations

import asyncio
from typing import Final, Optional

from eth_abi import decode
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_constants import WAVAX_CONTRACT_ADDRESS
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetSnapshot,
    AaveSentinelPositionSnapshot,
    AaveSentinelReserveAsset,
    AaveSentinelReserveRegistry,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    convert_ray_to_annual_percentage_yield,
    decode_aave_reserve_liquidation_threshold,
)
from src.core.aavesentinel.position.aave_sentinel_position_reserve_registry_service import load_aave_sentinel_reserve_registry
from src.core.aavesentinel.position.aave_sentinel_position_strategy_helpers import resolve_active_strategies
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_abis import (
    AAVE_ORACLE_ABI,
    AAVE_POOL_ABI,
    AAVE_RESERVE_DATA_ABI_TYPES,
    ADDRESS_PROVIDER_ABI,
    ERC20_ABI,
)
from src.integrations.blockchain.blockchain_rpc_registry import (
    BlockchainRpcRateLimitedError,
    resolve_async_web3_provider_for_chain,
)
from src.integrations.blockchain.evm.blockchain_evm_multicall_reader import (
    AVALANCHE_MULTICALL3_CONTRACT_ADDRESS,
    BlockchainEvmMulticallCall,
    BlockchainEvmMulticallResult,
    build_multicall3_contract,
    execute_multicall3_aggregate,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

Account.enable_unaudited_hdwallet_features()

_POSITION_MULTICALL_CALLS_PER_RESERVE: Final[int] = 5
_SUPPLY_BALANCE_CALL_OFFSET: Final[int] = 0
_DEBT_BALANCE_CALL_OFFSET: Final[int] = 1
_WALLET_BALANCE_CALL_OFFSET: Final[int] = 2
_ASSET_PRICE_CALL_OFFSET: Final[int] = 3
_RESERVE_DATA_CALL_OFFSET: Final[int] = 4
_ORACLE_PRICE_DECIMAL_DIVISOR: Final[float] = 1e8


def _normalize_contract_call_data(encoded_call_data: str | bytes) -> bytes:
    if isinstance(encoded_call_data, bytes):
        return encoded_call_data
    if encoded_call_data.startswith("0x"):
        return bytes.fromhex(encoded_call_data[2:])
    return bytes.fromhex(encoded_call_data)


def _decode_uint256_return_data(return_data: bytes) -> int:
    decoded_values = decode(["uint256"], return_data)
    return int(decoded_values[0])


def _decode_successful_uint256(multicall_result: BlockchainEvmMulticallResult) -> Optional[int]:
    if not multicall_result.is_success or len(multicall_result.return_data) == 0:
        return None
    return _decode_uint256_return_data(multicall_result.return_data)


def build_asset_snapshots_from_multicall_results(
        reserve_assets: list[AaveSentinelReserveAsset],
        reserve_multicall_results: list[BlockchainEvmMulticallResult],
        native_balance_raw: Optional[int],
) -> list[AaveSentinelAssetSnapshot]:
    expected_result_count = len(reserve_assets) * _POSITION_MULTICALL_CALLS_PER_RESERVE
    if len(reserve_multicall_results) != expected_result_count:
        raise ValueError(
            "Position multicall result count does not match the reserve registry "
            f"(expected={expected_result_count}, actual={len(reserve_multicall_results)})",
        )

    asset_snapshots: list[AaveSentinelAssetSnapshot] = []
    for reserve_index, reserve_asset in enumerate(reserve_assets):
        result_offset = reserve_index * _POSITION_MULTICALL_CALLS_PER_RESERVE
        raw_supply_balance = _decode_successful_uint256(
            reserve_multicall_results[result_offset + _SUPPLY_BALANCE_CALL_OFFSET],
        )
        raw_debt_balance = _decode_successful_uint256(
            reserve_multicall_results[result_offset + _DEBT_BALANCE_CALL_OFFSET],
        )
        raw_wallet_balance = _decode_successful_uint256(
            reserve_multicall_results[result_offset + _WALLET_BALANCE_CALL_OFFSET],
        )
        raw_asset_price = _decode_successful_uint256(
            reserve_multicall_results[result_offset + _ASSET_PRICE_CALL_OFFSET],
        )
        reserve_data_result = reserve_multicall_results[result_offset + _RESERVE_DATA_CALL_OFFSET]
        if (
                raw_supply_balance is None
                or raw_debt_balance is None
                or raw_wallet_balance is None
                or raw_asset_price is None
                or not reserve_data_result.is_success
                or len(reserve_data_result.return_data) == 0
        ):
            continue

        if (
                reserve_asset.underlying_address.lower() == WAVAX_CONTRACT_ADDRESS.lower()
                and native_balance_raw is not None
        ):
            raw_wallet_balance += native_balance_raw

        if raw_supply_balance == 0 and raw_debt_balance == 0 and raw_wallet_balance == 0:
            continue

        reserve_data = decode(AAVE_RESERVE_DATA_ABI_TYPES, reserve_data_result.return_data)
        configuration_bitmap = int(reserve_data[0])
        liquidity_rate_ray = int(reserve_data[2])
        variable_borrow_rate_ray = int(reserve_data[4])
        normalization_scale = 10 ** reserve_asset.decimal_count
        normalized_supply_amount = raw_supply_balance / normalization_scale
        normalized_debt_amount = raw_debt_balance / normalization_scale
        normalized_wallet_amount = raw_wallet_balance / normalization_scale
        asset_price_usd = raw_asset_price / _ORACLE_PRICE_DECIMAL_DIVISOR

        asset_snapshots.append(
            AaveSentinelAssetSnapshot(
                symbol=reserve_asset.symbol,
                underlying_address=reserve_asset.underlying_address,
                supply_amount=normalized_supply_amount,
                debt_amount=normalized_debt_amount,
                wallet_amount=normalized_wallet_amount,
                supply_value_usd=normalized_supply_amount * asset_price_usd,
                debt_value_usd=normalized_debt_amount * asset_price_usd,
                wallet_value_usd=normalized_wallet_amount * asset_price_usd,
                supply_annual_percentage_yield=convert_ray_to_annual_percentage_yield(liquidity_rate_ray),
                borrow_annual_percentage_yield=convert_ray_to_annual_percentage_yield(variable_borrow_rate_ray),
                liquidation_threshold=decode_aave_reserve_liquidation_threshold(
                    configuration_bitmap=configuration_bitmap,
                ),
            ),
        )

    asset_snapshots.sort(
        key=lambda asset_snapshot: asset_snapshot.supply_value_usd + asset_snapshot.wallet_value_usd,
        reverse=True,
    )
    return asset_snapshots


class AaveSentinelSnapshotService:
    def __init__(self) -> None:
        self._web3_client: Optional[AsyncWeb3] = None
        self._pool_contract: Optional[AsyncContract] = None
        self._oracle_contract: Optional[AsyncContract] = None
        self._wallet_address: str = ""
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
            total_collateral_usd = account_metrics[0] / _ORACLE_PRICE_DECIMAL_DIVISOR
            total_debt_usd = account_metrics[1] / _ORACLE_PRICE_DECIMAL_DIVISOR
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

            reserve_registry = await load_aave_sentinel_reserve_registry()
            active_assets = await self._fetch_asset_snapshots(
                reserve_registry=reserve_registry,
                wallet_checksum_address=wallet_checksum_address,
            )
            for asset_snapshot in active_assets:
                logger.debug(
                    "[AAVESENTINEL][SCAN] Asset resolved %s supply=$%0.2f debt=$%0.2f wallet=$%0.2f",
                    asset_snapshot.symbol,
                    asset_snapshot.supply_value_usd,
                    asset_snapshot.debt_value_usd,
                    asset_snapshot.wallet_value_usd,
                )

            active_strategies = resolve_active_strategies(
                detected_assets=active_assets,
                reserve_registry=reserve_registry,
            )

            return AaveSentinelPositionSnapshot(
                health_factor=normalized_health_factor,
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                strategies=active_strategies,
                assets=active_assets,
            )
        except BlockchainRpcRateLimitedError:
            logger.warning(
                "[AAVESENTINEL][SNAPSHOT] Snapshot acquisition skipped because the RPC endpoint is rate limited",
            )
            raise
        except Exception as exception:
            logger.exception("[AAVESENTINEL][SNAPSHOT] Snapshot acquisition failed: %s", exception)
            return None

    async def _fetch_asset_snapshots(
            self,
            reserve_registry: AaveSentinelReserveRegistry,
            wallet_checksum_address: str,
    ) -> list[AaveSentinelAssetSnapshot]:
        reserve_assets = list(reserve_registry.reserve_assets)
        if (
                len(reserve_assets) == 0
                or self._web3_client is None
                or self._pool_contract is None
                or self._oracle_contract is None
        ):
            return []

        erc20_contract = self._web3_client.eth.contract(
            address=AsyncWeb3.to_checksum_address(reserve_assets[0].underlying_address),
            abi=ERC20_ABI,
        )
        multicall_contract = build_multicall3_contract(web3_client=self._web3_client)
        multicall_calls: list[BlockchainEvmMulticallCall] = []
        for reserve_asset in reserve_assets:
            underlying_checksum_address = AsyncWeb3.to_checksum_address(reserve_asset.underlying_address)
            supply_balance_call_data = erc20_contract.encode_abi(
                abi_element_identifier="balanceOf",
                args=[wallet_checksum_address],
            )
            debt_balance_call_data = erc20_contract.encode_abi(
                abi_element_identifier="balanceOf",
                args=[wallet_checksum_address],
            )
            wallet_balance_call_data = erc20_contract.encode_abi(
                abi_element_identifier="balanceOf",
                args=[wallet_checksum_address],
            )
            asset_price_call_data = self._oracle_contract.encode_abi(
                abi_element_identifier="getAssetPrice",
                args=[underlying_checksum_address],
            )
            reserve_data_call_data = self._pool_contract.encode_abi(
                abi_element_identifier="getReserveData",
                args=[underlying_checksum_address],
            )
            multicall_calls.append(
                BlockchainEvmMulticallCall(
                    target_address=reserve_asset.a_token_address,
                    call_data=_normalize_contract_call_data(supply_balance_call_data),
                    allow_failure=True,
                ),
            )
            multicall_calls.append(
                BlockchainEvmMulticallCall(
                    target_address=reserve_asset.variable_debt_token_address,
                    call_data=_normalize_contract_call_data(debt_balance_call_data),
                    allow_failure=True,
                ),
            )
            multicall_calls.append(
                BlockchainEvmMulticallCall(
                    target_address=reserve_asset.underlying_address,
                    call_data=_normalize_contract_call_data(wallet_balance_call_data),
                    allow_failure=True,
                ),
            )
            multicall_calls.append(
                BlockchainEvmMulticallCall(
                    target_address=str(self._oracle_contract.address),
                    call_data=_normalize_contract_call_data(asset_price_call_data),
                    allow_failure=True,
                ),
            )
            multicall_calls.append(
                BlockchainEvmMulticallCall(
                    target_address=str(self._pool_contract.address),
                    call_data=_normalize_contract_call_data(reserve_data_call_data),
                    allow_failure=True,
                ),
            )

        native_balance_call_data = multicall_contract.encode_abi(
            abi_element_identifier="getEthBalance",
            args=[wallet_checksum_address],
        )
        multicall_calls.append(
            BlockchainEvmMulticallCall(
                target_address=AVALANCHE_MULTICALL3_CONTRACT_ADDRESS,
                call_data=_normalize_contract_call_data(native_balance_call_data),
                allow_failure=True,
            ),
        )

        multicall_results = await execute_multicall3_aggregate(
            web3_client=self._web3_client,
            multicall_calls=multicall_calls,
        )
        native_balance_result = multicall_results[-1]
        native_balance_raw = _decode_successful_uint256(native_balance_result)
        if native_balance_raw is None:
            logger.warning("[AAVESENTINEL][SCAN] Native AVAX balance lookup failed and will be omitted")

        return build_asset_snapshots_from_multicall_results(
            reserve_assets=reserve_assets,
            reserve_multicall_results=multicall_results[:-1],
            native_balance_raw=native_balance_raw,
        )

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
