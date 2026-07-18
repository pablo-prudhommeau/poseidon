from __future__ import annotations

from typing import Optional

from eth_abi import decode
from web3 import AsyncWeb3
from web3.contract import AsyncContract

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_abis import (
    AAVE_ORACLE_ABI,
    AAVE_POOL_ABI,
    AAVE_RESERVE_DATA_ABI_TYPES,
    AAVE_SCALED_BALANCE_TOKEN_ABI,
    ADDRESS_PROVIDER_ABI,
)
from src.integrations.aave.aave_structures import (
    AaveAssetPriceUsdSnapshot,
    AaveReserveIndexSnapshot,
    AaveScaledBalanceBatchRequest,
    AaveScaledBalanceSnapshot,
)
from src.integrations.blockchain.evm.blockchain_evm_multicall_reader import (
    BlockchainEvmMulticallCall,
    execute_multicall3_aggregate,
)
from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _normalize_contract_call_data(encoded_call_data: str | bytes) -> bytes:
    if isinstance(encoded_call_data, bytes):
        return encoded_call_data
    if encoded_call_data.startswith("0x"):
        return bytes.fromhex(encoded_call_data[2:])
    return bytes.fromhex(encoded_call_data)


def _decode_uint256_return_data(return_data: bytes) -> int:
    decoded_values = decode(["uint256"], return_data)
    return int(decoded_values[0])


class AaveProtocolReader:
    def __init__(self) -> None:
        self._web3_client: Optional[AsyncWeb3] = None
        self._pool_contract: Optional[AsyncContract] = None
        self._oracle_contract: Optional[AsyncContract] = None

    async def close(self) -> None:
        self._web3_client = None
        self._pool_contract = None
        self._oracle_contract = None

    async def fetch_latest_block_number(self) -> int:
        await self._ensure_pool_contract()
        if self._web3_client is None:
            raise RuntimeError("Web3 client unavailable for latest block lookup")
        return int(await self._web3_client.eth.block_number)

    async def fetch_asset_price_usd_at_block(
            self,
            contract_address: str,
            block_number: int,
    ) -> Optional[float]:
        asset_price_usd_snapshots = await self.fetch_asset_prices_usd_at_block_batch(
            contract_addresses=[contract_address],
            block_number=block_number,
        )
        normalized_contract_address = contract_address.lower()
        for asset_price_usd_snapshot in asset_price_usd_snapshots:
            if asset_price_usd_snapshot.contract_address == normalized_contract_address:
                return asset_price_usd_snapshot.asset_price_usd
        return None

    async def fetch_asset_prices_usd_at_block_batch(
            self,
            contract_addresses: list[str],
            block_number: int,
    ) -> list[AaveAssetPriceUsdSnapshot]:
        if len(contract_addresses) == 0:
            return []

        try:
            await self._ensure_oracle_contract()
            if self._oracle_contract is None or self._web3_client is None:
                return []

            unique_contract_addresses: list[str] = []
            seen_contract_addresses: set[str] = set()
            for contract_address in contract_addresses:
                normalized_contract_address = contract_address.lower()
                if normalized_contract_address in seen_contract_addresses:
                    continue
                seen_contract_addresses.add(normalized_contract_address)
                unique_contract_addresses.append(contract_address)

            oracle_contract_address = self._oracle_contract.address
            multicall_calls: list[BlockchainEvmMulticallCall] = []
            for contract_address in unique_contract_addresses:
                checksum_contract_address = AsyncWeb3.to_checksum_address(contract_address)
                call_data = self._oracle_contract.encode_abi(
                    abi_element_identifier="getAssetPrice",
                    args=[checksum_contract_address],
                )
                multicall_calls.append(
                    BlockchainEvmMulticallCall(
                        target_address=str(oracle_contract_address),
                        call_data=_normalize_contract_call_data(call_data),
                        allow_failure=True,
                    )
                )

            multicall_results = await execute_multicall3_aggregate(
                web3_client=self._web3_client,
                multicall_calls=multicall_calls,
                block_number=block_number,
            )
            asset_price_usd_snapshots: list[AaveAssetPriceUsdSnapshot] = []
            for contract_address, multicall_result in zip(
                    unique_contract_addresses,
                    multicall_results,
                    strict=True,
            ):
                if not multicall_result.is_success or len(multicall_result.return_data) == 0:
                    continue
                raw_asset_price_base = _decode_uint256_return_data(multicall_result.return_data)
                if raw_asset_price_base <= 0:
                    continue
                asset_price_usd_snapshots.append(
                    AaveAssetPriceUsdSnapshot(
                        contract_address=contract_address.lower(),
                        asset_price_usd=raw_asset_price_base / 1e8,
                    )
                )
            return asset_price_usd_snapshots
        except Exception as exception:
            logger.exception(
                "[AAVE][READER][ORACLE] Historical batch lookup failed block=%d call_count=%d: %s",
                block_number,
                len(contract_addresses),
                exception,
            )
            return []

    async def fetch_reserve_index_snapshot_at_block(
            self,
            underlying_address: str,
            block_number: int,
    ) -> Optional[AaveReserveIndexSnapshot]:
        reserve_index_snapshots = await self.fetch_reserve_index_snapshots_at_block_batch(
            underlying_addresses=[underlying_address],
            block_number=block_number,
        )
        normalized_underlying_address = underlying_address.lower()
        for reserve_index_snapshot in reserve_index_snapshots:
            if reserve_index_snapshot.underlying_address == normalized_underlying_address:
                return reserve_index_snapshot
        return None

    async def fetch_reserve_index_snapshots_at_block_batch(
            self,
            underlying_addresses: list[str],
            block_number: int,
    ) -> list[AaveReserveIndexSnapshot]:
        if len(underlying_addresses) == 0:
            return []

        try:
            await self._ensure_pool_contract()
            if self._pool_contract is None or self._web3_client is None:
                return []

            unique_underlying_addresses: list[str] = []
            seen_underlying_addresses: set[str] = set()
            for underlying_address in underlying_addresses:
                normalized_underlying_address = underlying_address.lower()
                if normalized_underlying_address in seen_underlying_addresses:
                    continue
                seen_underlying_addresses.add(normalized_underlying_address)
                unique_underlying_addresses.append(underlying_address)

            pool_contract_address = self._pool_contract.address
            multicall_calls: list[BlockchainEvmMulticallCall] = []
            for underlying_address in unique_underlying_addresses:
                checksum_underlying_address = AsyncWeb3.to_checksum_address(underlying_address)
                call_data = self._pool_contract.encode_abi(
                    abi_element_identifier="getReserveData",
                    args=[checksum_underlying_address],
                )
                multicall_calls.append(
                    BlockchainEvmMulticallCall(
                        target_address=str(pool_contract_address),
                        call_data=_normalize_contract_call_data(call_data),
                        allow_failure=True,
                    )
                )

            multicall_results = await execute_multicall3_aggregate(
                web3_client=self._web3_client,
                multicall_calls=multicall_calls,
                block_number=block_number,
            )
            reserve_index_snapshots: list[AaveReserveIndexSnapshot] = []
            for underlying_address, multicall_result in zip(
                    unique_underlying_addresses,
                    multicall_results,
                    strict=True,
            ):
                if not multicall_result.is_success or len(multicall_result.return_data) == 0:
                    continue
                reserve_data = decode(AAVE_RESERVE_DATA_ABI_TYPES, multicall_result.return_data)
                liquidity_index = float(int(reserve_data[1]))
                variable_borrow_index = float(int(reserve_data[3]))
                if liquidity_index <= 0 or variable_borrow_index <= 0:
                    continue
                reserve_index_snapshots.append(
                    AaveReserveIndexSnapshot(
                        underlying_address=underlying_address.lower(),
                        liquidity_index=liquidity_index,
                        variable_borrow_index=variable_borrow_index,
                    )
                )
            return reserve_index_snapshots
        except Exception as exception:
            logger.exception(
                "[AAVE][READER][INDEX] Historical reserve index batch lookup failed block=%d call_count=%d: %s",
                block_number,
                len(underlying_addresses),
                exception,
            )
            return []

    async def fetch_scaled_balances_at_block(
            self,
            wallet_address: str,
            underlying_address: str,
            a_token_address: str,
            variable_debt_token_address: str,
            decimal_count: int,
            block_number: int,
    ) -> Optional[AaveScaledBalanceSnapshot]:
        scaled_balance_snapshots = await self.fetch_scaled_balances_at_block_batch(
            wallet_address=wallet_address,
            scaled_balance_batch_requests=[
                AaveScaledBalanceBatchRequest(
                    underlying_address=underlying_address,
                    a_token_address=a_token_address,
                    variable_debt_token_address=variable_debt_token_address,
                    decimal_count=decimal_count,
                )
            ],
            block_number=block_number,
        )
        normalized_underlying_address = underlying_address.lower()
        for scaled_balance_snapshot in scaled_balance_snapshots:
            if scaled_balance_snapshot.underlying_address == normalized_underlying_address:
                return scaled_balance_snapshot
        return None

    async def fetch_scaled_balances_at_block_batch(
            self,
            wallet_address: str,
            scaled_balance_batch_requests: list[AaveScaledBalanceBatchRequest],
            block_number: int,
    ) -> list[AaveScaledBalanceSnapshot]:
        if len(scaled_balance_batch_requests) == 0:
            return []

        try:
            await self._ensure_pool_contract()
            if self._web3_client is None:
                return []

            checksum_wallet_address = AsyncWeb3.to_checksum_address(wallet_address)
            scaled_balance_token_contract = self._web3_client.eth.contract(
                address=AsyncWeb3.to_checksum_address(scaled_balance_batch_requests[0].a_token_address),
                abi=AAVE_SCALED_BALANCE_TOKEN_ABI,
            )
            multicall_calls: list[BlockchainEvmMulticallCall] = []
            for scaled_balance_batch_request in scaled_balance_batch_requests:
                supply_call_data = scaled_balance_token_contract.encode_abi(
                    abi_element_identifier="scaledBalanceOf",
                    args=[checksum_wallet_address],
                )
                debt_call_data = scaled_balance_token_contract.encode_abi(
                    abi_element_identifier="scaledBalanceOf",
                    args=[checksum_wallet_address],
                )
                multicall_calls.append(
                    BlockchainEvmMulticallCall(
                        target_address=scaled_balance_batch_request.a_token_address,
                        call_data=_normalize_contract_call_data(supply_call_data),
                        allow_failure=True,
                    )
                )
                multicall_calls.append(
                    BlockchainEvmMulticallCall(
                        target_address=scaled_balance_batch_request.variable_debt_token_address,
                        call_data=_normalize_contract_call_data(debt_call_data),
                        allow_failure=True,
                    )
                )

            multicall_results = await execute_multicall3_aggregate(
                web3_client=self._web3_client,
                multicall_calls=multicall_calls,
                block_number=block_number,
            )
            scaled_balance_snapshots: list[AaveScaledBalanceSnapshot] = []
            for request_index, scaled_balance_batch_request in enumerate(scaled_balance_batch_requests):
                supply_result = multicall_results[request_index * 2]
                debt_result = multicall_results[request_index * 2 + 1]
                if not supply_result.is_success or not debt_result.is_success:
                    continue
                if len(supply_result.return_data) == 0 or len(debt_result.return_data) == 0:
                    continue
                raw_scaled_supply_balance = _decode_uint256_return_data(supply_result.return_data)
                raw_scaled_debt_balance = _decode_uint256_return_data(debt_result.return_data)
                decimal_divisor = 10 ** scaled_balance_batch_request.decimal_count
                scaled_balance_snapshots.append(
                    AaveScaledBalanceSnapshot(
                        underlying_address=scaled_balance_batch_request.underlying_address.lower(),
                        scaled_supply_balance=float(raw_scaled_supply_balance) / decimal_divisor,
                        scaled_debt_balance=float(raw_scaled_debt_balance) / decimal_divisor,
                    )
                )
            return scaled_balance_snapshots
        except Exception as exception:
            logger.exception(
                "[AAVE][READER][SCALED] Live scaled balance batch lookup failed block=%d call_count=%d: %s",
                block_number,
                len(scaled_balance_batch_requests),
                exception,
            )
            return []

    async def _ensure_oracle_contract(self) -> None:
        if self._oracle_contract is not None:
            return

        await self._ensure_pool_contract()
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

    async def _ensure_pool_contract(self) -> None:
        if self._pool_contract is not None:
            return

        self._web3_client = resolve_async_web3_provider_for_chain(BlockchainNetwork.AVALANCHE)
        pool_contract_address = AsyncWeb3.to_checksum_address(settings.AAVE_POOL_V3_ADDRESS)
        self._pool_contract = self._web3_client.eth.contract(
            address=pool_contract_address,
            abi=AAVE_POOL_ABI,
        )
