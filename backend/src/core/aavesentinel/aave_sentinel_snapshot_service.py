from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Awaitable, Optional, TypeVar

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3
from web3.contract import AsyncContract
from web3.types import TxParams

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetSnapshot,
    AaveSentinelPositionSnapshot,
    AaveSentinelRescueExecutionResult,
    AaveSentinelRescueExecutionStatus,
    AaveSentinelStrategyDirection,
)
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_abis import (
    ADDRESS_PROVIDER_ABI,
    AAVE_ORACLE_ABI,
    AAVE_POOL_ABI,
    ERC20_ABI,
    RAY_UNITS,
    SECONDS_PER_YEAR,
)
from src.integrations.blockchain.blockchain_rpc_registry import resolve_async_web3_provider_for_chain
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

Account.enable_unaudited_hdwallet_features()

STABLECOIN_SYMBOLS: set[str] = {"USDC", "USDC.e", "USDT", "USDt", "DAI", "FRAX", "MIM", "BUSD"}
ProtectedCallResult = TypeVar("ProtectedCallResult")


class AaveSentinelSnapshotService:
    def __init__(self) -> None:
        self._web3_client: Optional[AsyncWeb3] = None
        self._pool_contract: Optional[AsyncContract] = None
        self._usdc_contract: Optional[AsyncContract] = None
        self._oracle_contract: Optional[AsyncContract] = None
        self._wallet_address: str = ""
        self._private_key: str = ""
        self._scan_semaphore = asyncio.Semaphore(settings.AAVE_MAX_CONCURRENT_ASSET_SCANS)

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    async def initialize(self) -> None:
        if not self._private_key:
            self._derive_credentials()

        if self._web3_client is not None:
            return

        self._web3_client = resolve_async_web3_provider_for_chain(BlockchainNetwork.AVALANCHE)

        pool_contract_address = AsyncWeb3.to_checksum_address(settings.AAVE_POOL_V3_ADDRESS)
        self._pool_contract = self._web3_client.eth.contract(address=pool_contract_address, abi=AAVE_POOL_ABI)

        usdc_contract_address = AsyncWeb3.to_checksum_address(settings.AAVE_USDC_ADDRESS)
        self._usdc_contract = self._web3_client.eth.contract(address=usdc_contract_address, abi=ERC20_ABI)

        try:
            addresses_provider_address = await self._pool_contract.functions.ADDRESSES_PROVIDER().call()
            addresses_provider_contract = self._web3_client.eth.contract(
                address=addresses_provider_address,
                abi=ADDRESS_PROVIDER_ABI,
            )
            oracle_contract_address = await addresses_provider_contract.functions.getPriceOracle().call()
            self._oracle_contract = self._web3_client.eth.contract(address=oracle_contract_address, abi=AAVE_ORACLE_ABI)
            logger.debug("[AAVE][SENTINEL][INITIALIZATION] Oracle contract loaded at %s", oracle_contract_address)
        except Exception as exception:
            logger.exception("[AAVE][SENTINEL][INITIALIZATION] Failed to initialize oracle contract: %s", exception)

    async def fetch_position_snapshot(self) -> Optional[AaveSentinelPositionSnapshot]:
        try:
            await self.initialize()
            if not self._wallet_address or self._pool_contract is None:
                logger.error("[AAVE][SENTINEL][SNAPSHOT] Snapshot aborted because initialization is incomplete")
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
                "[AAVE][SENTINEL][SNAPSHOT] Core metrics resolved: health_factor=%0.2f collateral=$%0.2f debt=$%0.2f",
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

            strategy_direction, main_asset_symbol, main_asset_price_usd, liquidation_price_usd = (
                self._resolve_strategy_snapshot(active_assets, normalized_health_factor)
            )

            return AaveSentinelPositionSnapshot(
                health_factor=normalized_health_factor,
                total_collateral_usd=total_collateral_usd,
                total_debt_usd=total_debt_usd,
                strategy_direction=strategy_direction,
                main_asset_symbol=main_asset_symbol,
                main_asset_price_usd=main_asset_price_usd,
                liquidation_price_usd=liquidation_price_usd,
                assets=active_assets,
            )
        except Exception as exception:
            logger.exception("[AAVE][SENTINEL][SNAPSHOT] Snapshot acquisition failed: %s", exception)
            return None

    async def trigger_emergency_rescue(self) -> AaveSentinelRescueExecutionResult:
        logger.critical("[AAVE][SENTINEL][RESCUE] Emergency rescue protocol requested")

        if self._web3_client is None or self._usdc_contract is None or self._pool_contract is None:
            await self.initialize()

        if self._web3_client is None or self._usdc_contract is None or self._pool_contract is None:
            logger.error("[AAVE][SENTINEL][RESCUE] Emergency rescue aborted because on-chain resources are unavailable")
            return AaveSentinelRescueExecutionResult(
                status=AaveSentinelRescueExecutionStatus.FAILED,
                message="Emergency rescue aborted because on-chain resources are unavailable.",
            )

        if not self._private_key:
            logger.warning("[AAVE][SENTINEL][RESCUE] Emergency rescue aborted because wallet credentials are missing")
            return AaveSentinelRescueExecutionResult(
                status=AaveSentinelRescueExecutionStatus.SKIPPED,
                message="Emergency rescue aborted because wallet credentials are missing.",
            )

        rescue_signer_account: LocalAccount = self._web3_client.eth.account.from_key(self._private_key)
        rescue_sender_address = rescue_signer_account.address

        try:
            account_metrics = await self._pool_contract.functions.getUserAccountData(rescue_sender_address).call()
            total_liabilities_base_units = float(account_metrics[1])

            available_usdc_balance_wei = await self._usdc_contract.functions.balanceOf(rescue_sender_address).call()
            available_usdc_balance = available_usdc_balance_wei / 1e6

            required_rescue_collateral_base_units = (settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT * total_liabilities_base_units) / settings.AAVE_RESCUE_USDC_LIQUIDATION_THRESHOLD
            required_liquidity_injection_usdc = (required_rescue_collateral_base_units / 100.0) * 1.01
            calculated_injection_amount_usdc = min(
                required_liquidity_injection_usdc,
                available_usdc_balance,
                settings.AAVE_RESCUE_MAX_CAP_USDC,
            )

            if calculated_injection_amount_usdc < settings.AAVE_RESCUE_MIN_AMOUNT_USDC:
                logger.warning(
                    "[AAVE][SENTINEL][RESCUE] Rescue aborted because computed amount %0.2f USDC is below minimum threshold",
                    calculated_injection_amount_usdc,
                )
                return AaveSentinelRescueExecutionResult(
                    status=AaveSentinelRescueExecutionStatus.SKIPPED,
                    message="Emergency rescue amount is below the configured minimum threshold.",
                    amount_usdc=calculated_injection_amount_usdc,
                )

            injection_amount_wei = int(calculated_injection_amount_usdc * 1e6)

            if settings.PAPER_MODE:
                logger.info(
                    "[AAVE][SENTINEL][RESCUE] Paper mode active, simulated injection amount=%0.2f available=%0.2f target_hf_delta=%0.2f",
                    calculated_injection_amount_usdc,
                    available_usdc_balance,
                    settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT,
                )
                return AaveSentinelRescueExecutionResult(
                    status=AaveSentinelRescueExecutionStatus.SIMULATED,
                    message=(
                        "Paper mode active.\n"
                        f"Injection calculée : <b>{calculated_injection_amount_usdc:.2f} USDC</b>\n"
                        f"(Cible: +{settings.AAVE_RESCUE_TARGET_HF_IMPROVEMENT} HF | "
                        f"Dispo: {available_usdc_balance:.2f} USDC)"
                    ),
                    amount_usdc=calculated_injection_amount_usdc,
                )

            current_nonce = await self._web3_client.eth.get_transaction_count(rescue_sender_address)
            market_gas_price = await self._web3_client.eth.gas_price
            aggressive_gas_price = int(market_gas_price * 1.1)

            approval_transaction: TxParams = await self._usdc_contract.functions.approve(
                settings.AAVE_POOL_V3_ADDRESS,
                injection_amount_wei,
            ).build_transaction({
                "from": rescue_sender_address,
                "nonce": current_nonce,
                "gas": 80000,
                "gasPrice": aggressive_gas_price,
            })
            signed_approval_transaction = self._web3_client.eth.account.sign_transaction(
                approval_transaction,
                self._private_key,
            )
            await self._web3_client.eth.send_raw_transaction(signed_approval_transaction.rawTransaction)

            await asyncio.sleep(2)

            supply_transaction: TxParams = await self._pool_contract.functions.supply(
                settings.AAVE_USDC_ADDRESS,
                injection_amount_wei,
                rescue_sender_address,
                0,
            ).build_transaction({
                "from": rescue_sender_address,
                "nonce": current_nonce + 1,
                "gas": 350000,
                "gasPrice": aggressive_gas_price,
            })
            signed_supply_transaction = self._web3_client.eth.account.sign_transaction(
                supply_transaction,
                self._private_key,
            )
            transaction_hash = await self._web3_client.eth.send_raw_transaction(signed_supply_transaction.rawTransaction)

            logger.info("[AAVE][SENTINEL][RESCUE] Rescue supply transaction broadcast: %s", transaction_hash.hex())
            return AaveSentinelRescueExecutionResult(
                status=AaveSentinelRescueExecutionStatus.EXECUTED,
                message=(
                    f"Injection de <b>{calculated_injection_amount_usdc:.2f} USDC</b> exécutée avec succès.\n"
                    f"TX: <code>{transaction_hash.hex()}</code>"
                ),
                amount_usdc=calculated_injection_amount_usdc,
                transaction_hash=transaction_hash.hex(),
            )
        except Exception as exception:
            logger.exception("[AAVE][SENTINEL][RESCUE] Emergency rescue execution failed: %s", exception)
            return AaveSentinelRescueExecutionResult(
                status=AaveSentinelRescueExecutionStatus.FAILED,
                message=f"Emergency rescue failed: {exception}",
            )

    def _derive_credentials(self) -> None:
        if not settings.WALLET_MNEMONIC:
            logger.warning("[AAVE][SENTINEL][CREDENTIALS] Wallet mnemonic is not configured, sentinel is read-only")
            return

        try:
            account_instance: LocalAccount = Account.from_mnemonic(
                mnemonic=settings.WALLET_MNEMONIC,
                account_path=f"m/44'/60'/0'/0/{settings.WALLET_DERIVATION_INDEX}",
            )
            self._private_key = account_instance.key.hex()
            self._wallet_address = account_instance.address
            logger.info("[AAVE][SENTINEL][CREDENTIALS] Wallet loaded for sentinel: %s", self._wallet_address)
        except Exception as exception:
            logger.exception("[AAVE][SENTINEL][CREDENTIALS] Wallet derivation failed: %s", exception)

    def _convert_ray_to_annual_percentage_yield(self, ray_value: int) -> float:
        if ray_value == 0:
            return 0.0

        interest_rate_per_second = Decimal(ray_value) / RAY_UNITS / Decimal(SECONDS_PER_YEAR)
        return float((Decimal(1) + interest_rate_per_second) ** Decimal(SECONDS_PER_YEAR) - Decimal(1))

    async def _perform_protected_onchain_call(
            self,
            coroutine_operation: Awaitable[ProtectedCallResult],
            fallback_default_value: ProtectedCallResult,
            operation_label: str,
    ) -> ProtectedCallResult:
        try:
            return await coroutine_operation
        except Exception as exception:
            logger.debug("[AAVE][SENTINEL][RPC] On-chain call failed for %s: %s", operation_label, exception)
            return fallback_default_value

    async def _scan_asset_snapshot(
            self,
            asset_contract_address: str,
            target_user_address: str,
    ) -> Optional[AaveSentinelAssetSnapshot]:
        async with self._scan_semaphore:
            try:
                if self._pool_contract is None or self._web3_client is None or self._oracle_contract is None:
                    logger.error("[AAVE][SENTINEL][SCAN] Asset scan aborted because contracts are not initialized")
                    return None

                asset_checksum_address = AsyncWeb3.to_checksum_address(asset_contract_address)
                reserve_configuration = await self._pool_contract.functions.getReserveData(asset_checksum_address).call()
                liquidity_rate_ray = reserve_configuration[2]
                variable_borrow_rate_ray = reserve_configuration[4]
                a_token_contract_address = reserve_configuration[8]
                variable_debt_token_contract_address = reserve_configuration[10]

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
                        logger.exception("[AAVE][SENTINEL][SCAN] Failed to aggregate native AVAX balance: %s", exception)

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
                    "[AAVE][SENTINEL][SCAN] Asset resolved %s supply=$%0.2f debt=$%0.2f wallet=$%0.2f",
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
                    supply_annual_percentage_yield=self._convert_ray_to_annual_percentage_yield(liquidity_rate_ray),
                    borrow_annual_percentage_yield=self._convert_ray_to_annual_percentage_yield(variable_borrow_rate_ray),
                )
            except Exception as exception:
                logger.exception(
                    "[AAVE][SENTINEL][SCAN] Asset scan failed for %s and will be skipped: %s",
                    asset_contract_address,
                    exception,
                )
                return None

    def _resolve_strategy_snapshot(
            self,
            detected_assets: list[AaveSentinelAssetSnapshot],
            current_health_factor: float,
    ) -> tuple[AaveSentinelStrategyDirection, Optional[str], Optional[float], Optional[float]]:
        aggregate_supply_value_usd = sum(asset.supply_value_usd for asset in detected_assets)
        aggregate_debt_value_usd = sum(asset.debt_value_usd for asset in detected_assets)

        if aggregate_supply_value_usd == 0 or aggregate_debt_value_usd == 0:
            return AaveSentinelStrategyDirection.NEUTRAL, None, None, None

        stablecoin_debt_value_usd = sum(
            asset.debt_value_usd
            for asset in detected_assets
            if asset.symbol in STABLECOIN_SYMBOLS
        )
        volatile_asset_debt_value_usd = aggregate_debt_value_usd - stablecoin_debt_value_usd
        is_long_biased_strategy = stablecoin_debt_value_usd > volatile_asset_debt_value_usd
        strategy_direction = (
            AaveSentinelStrategyDirection.LONG
            if is_long_biased_strategy
            else AaveSentinelStrategyDirection.SHORT
        )

        if is_long_biased_strategy:
            eligible_assets = [
                asset
                for asset in detected_assets
                if asset.symbol not in STABLECOIN_SYMBOLS and asset.supply_value_usd > 0
            ]
            if not eligible_assets:
                return AaveSentinelStrategyDirection.NEUTRAL, None, None, None

            main_asset = max(eligible_assets, key=lambda asset_snapshot: asset_snapshot.supply_value_usd)
            if main_asset.supply_amount == 0:
                return strategy_direction, main_asset.symbol, 0.0, 0.0

            current_price_usd = main_asset.supply_value_usd / main_asset.supply_amount
            liquidation_price_usd = current_price_usd / current_health_factor if current_health_factor > 0 else 0.0
            return strategy_direction, main_asset.symbol, current_price_usd, liquidation_price_usd

        eligible_assets = [
            asset
            for asset in detected_assets
            if asset.symbol not in STABLECOIN_SYMBOLS and asset.debt_value_usd > 0
        ]
        if not eligible_assets:
            return AaveSentinelStrategyDirection.NEUTRAL, None, None, None

        main_asset = max(eligible_assets, key=lambda asset_snapshot: asset_snapshot.debt_value_usd)
        if main_asset.debt_amount == 0:
            return strategy_direction, main_asset.symbol, 0.0, 0.0

        current_price_usd = main_asset.debt_value_usd / main_asset.debt_amount
        liquidation_price_usd = current_price_usd * current_health_factor
        return strategy_direction, main_asset.symbol, current_price_usd, liquidation_price_usd
