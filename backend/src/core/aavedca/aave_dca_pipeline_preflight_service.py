from __future__ import annotations

import asyncio
import time

from src.configuration.config import settings
from src.core.aavedca.aave_dca_structures import (
    AaveDcaBlockingPipelineError,
    AaveDcaOrderStatus,
    AaveDcaPipelinePreflightFailureReason,
    AaveDcaPipelinePreflightResult,
)
from src.core.structures.structures import BlockchainNetwork
from src.integrations.aave.aave_executor import AaveExecutor
from src.logging.logger import get_application_logger
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)


class AaveDcaPipelinePreflightService:
    def __init__(self, aave_executor: AaveExecutor) -> None:
        self.aave_executor = aave_executor

    async def run_live_pipeline_preflight_checks(
        self,
        blockchain: BlockchainNetwork,
        order_status: AaveDcaOrderStatus,
        source_asset_address: str,
        source_asset_decimals: int,
        required_execution_amount_base_units: int,
        minimum_native_gas_reserve_avax: float,
    ) -> AaveDcaPipelinePreflightResult:
        if required_execution_amount_base_units <= 0:
            return AaveDcaPipelinePreflightResult(
                is_successful=False,
                failure_reason=AaveDcaPipelinePreflightFailureReason.INVALID_EXECUTION_AMOUNT,
                required_execution_amount_base_units=required_execution_amount_base_units,
            )

        native_gas_balance_avax: float = await self.aave_executor.fetch_native_gas_balance_avax(blockchain)
        if native_gas_balance_avax < minimum_native_gas_reserve_avax:
            return AaveDcaPipelinePreflightResult(
                is_successful=False,
                failure_reason=AaveDcaPipelinePreflightFailureReason.INSUFFICIENT_NATIVE_GAS_BALANCE,
                native_gas_balance_avax=native_gas_balance_avax,
                required_execution_amount_base_units=required_execution_amount_base_units,
            )

        if order_status == AaveDcaOrderStatus.AWAITING_SUPPLY:
            return AaveDcaPipelinePreflightResult(
                is_successful=True,
                native_gas_balance_avax=native_gas_balance_avax,
                required_execution_amount_base_units=required_execution_amount_base_units,
            )

        required_balance: float = required_execution_amount_base_units / float(10 ** source_asset_decimals)

        if order_status == AaveDcaOrderStatus.AWAITING_WITHDRAW:
            aave_supply_balance: float = await self.aave_executor.fetch_token_balance(blockchain, source_asset_address)
            if aave_supply_balance < required_balance:
                return AaveDcaPipelinePreflightResult(
                    is_successful=False,
                    failure_reason=AaveDcaPipelinePreflightFailureReason.INSUFFICIENT_AAVE_SUPPLY_BALANCE,
                    native_gas_balance_avax=native_gas_balance_avax,
                    aave_supply_balance=aave_supply_balance,
                    required_execution_amount_base_units=required_execution_amount_base_units,
                )

            return AaveDcaPipelinePreflightResult(
                is_successful=True,
                native_gas_balance_avax=native_gas_balance_avax,
                aave_supply_balance=aave_supply_balance,
                required_execution_amount_base_units=required_execution_amount_base_units,
            )

        wallet_source_balance_wei: int = await self.aave_executor.fetch_erc20_balance(blockchain, source_asset_address)
        wallet_source_balance: float = wallet_source_balance_wei / float(10 ** source_asset_decimals)
        if wallet_source_balance < required_balance:
            return AaveDcaPipelinePreflightResult(
                is_successful=False,
                failure_reason=AaveDcaPipelinePreflightFailureReason.INSUFFICIENT_WALLET_SOURCE_BALANCE,
                native_gas_balance_avax=native_gas_balance_avax,
                wallet_source_balance=wallet_source_balance,
                required_execution_amount_base_units=required_execution_amount_base_units,
            )

        return AaveDcaPipelinePreflightResult(
            is_successful=True,
            native_gas_balance_avax=native_gas_balance_avax,
            wallet_source_balance=wallet_source_balance,
            required_execution_amount_base_units=required_execution_amount_base_units,
        )

    async def run_live_pipeline_preflight(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            blockchain: BlockchainNetwork,
            amount_in_base_units: int,
            order_status: AaveDcaOrderStatus,
    ) -> None:
        preflight_result = await self.run_live_pipeline_preflight_checks(
            blockchain=blockchain,
            order_status=order_status,
            source_asset_address=dca_strategy.source_asset_address,
            source_asset_decimals=dca_strategy.source_asset_decimals,
            required_execution_amount_base_units=amount_in_base_units,
            minimum_native_gas_reserve_avax=settings.AAVE_DCA_MINIMUM_NATIVE_GAS_RESERVE_AVAX,
        )

        if preflight_result.is_successful:
            logger.debug(
                "[AAVEDCA][PREFLIGHT] Checks passed for order_id=%s status=%s native_gas_balance_avax=%s aave_supply_balance=%s wallet_source_balance=%s required_amount_base_units=%s",
                dca_order.id,
                order_status.value,
                preflight_result.native_gas_balance_avax,
                preflight_result.aave_supply_balance,
                preflight_result.wallet_source_balance,
                preflight_result.required_execution_amount_base_units,
            )
            return

        failure_reason: str = (
            preflight_result.failure_reason.value
            if preflight_result.failure_reason is not None
            else "UNKNOWN"
        )
        logger.warning(
            "[AAVEDCA][PREFLIGHT] Live pipeline preflight failed for order_id=%s status=%s failure_reason=%s native_gas_balance_avax=%s aave_supply_balance=%s wallet_source_balance=%s required_amount_base_units=%s minimum_native_gas_reserve_avax=%s",
            dca_order.id,
            order_status.value,
            failure_reason,
            preflight_result.native_gas_balance_avax,
            preflight_result.aave_supply_balance,
            preflight_result.wallet_source_balance,
            preflight_result.required_execution_amount_base_units,
            settings.AAVE_DCA_MINIMUM_NATIVE_GAS_RESERVE_AVAX,
        )
        raise AaveDcaBlockingPipelineError(
            failure_reason,
            f"Live pipeline preflight failed for order {dca_order.id}: {failure_reason}",
        )

    async def poll_target_asset_balance_after_swap(
        self,
        blockchain: BlockchainNetwork,
        token_address: str,
        minimum_balance_wei: int,
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> int:
        deadline_timestamp: float = time.monotonic() + timeout_seconds
        poll_attempt_count: int = 0
        last_observed_balance_wei: int = 0

        while time.monotonic() < deadline_timestamp:
            poll_attempt_count += 1
            last_observed_balance_wei = await self.aave_executor.fetch_erc20_balance(blockchain, token_address)
            if last_observed_balance_wei >= minimum_balance_wei:
                logger.debug(
                    "[AAVEDCA][PREFLIGHT][SETTLEMENT] Target token balance reflects swap settlement — token_address=%s poll_attempt_count=%d balance_wei=%d minimum_balance_wei=%d",
                    token_address,
                    poll_attempt_count,
                    last_observed_balance_wei,
                    minimum_balance_wei,
                )
                return last_observed_balance_wei
            await asyncio.sleep(poll_interval_seconds)

        logger.warning(
            "[AAVEDCA][PREFLIGHT][SETTLEMENT] Target token balance polling timed out — token_address=%s poll_attempt_count=%d last_balance_wei=%d minimum_balance_wei=%d timeout_seconds=%s",
            token_address,
            poll_attempt_count,
            last_observed_balance_wei,
            minimum_balance_wei,
            timeout_seconds,
        )
        return last_observed_balance_wei
