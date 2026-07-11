from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from src.configuration.config import settings
from src.core.aavedca.aave_dca_structures import (
    AaveDcaAllocationDecision,
    AaveDcaOrderStatus,
    AaveDcaOrderPipelineOperations,
    AaveDcaPipelineOperation,
    AaveDcaPipelineOperationStatus,
    AaveDcaPipelineOperationStep,
    AaveDcaPipelinePreflightFailureReason,
    AaveDcaPipelinePreflightResult,
    AaveDcaSwapPriceValidationResult,
)
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def convert_token_amount_to_base_units(token_amount: float, token_decimals: int) -> int:
    decimal_amount: Decimal = Decimal(str(token_amount))
    scale_factor: Decimal = Decimal(10) ** token_decimals
    base_units: Decimal = decimal_amount * scale_factor
    return int(base_units)


def compute_implied_swap_price_usd(
        source_amount_base_units: int,
        target_amount_base_units: int,
        source_asset_decimals: int,
        target_asset_decimals: int,
) -> float:
    source_amount_decimal: Decimal = Decimal(source_amount_base_units) / Decimal(10) ** source_asset_decimals
    target_amount_decimal: Decimal = Decimal(target_amount_base_units) / Decimal(10) ** target_asset_decimals
    if target_amount_decimal <= Decimal(0):
        return 0.0
    return float(source_amount_decimal / target_amount_decimal)


def compute_price_deviation_percent(reference_price_usd: float, implied_price_usd: float) -> float:
    if reference_price_usd <= 0 or implied_price_usd <= 0:
        return 100.0
    return abs(implied_price_usd - reference_price_usd) / reference_price_usd * 100.0


def validate_lifi_swap_price_against_binance_reference(
    binance_reference_price_usd: float,
    lifi_expected_output_amount_base_units: int,
    lifi_minimum_output_amount_base_units: int,
    source_amount_base_units: int,
    source_asset_decimals: int,
    target_asset_decimals: int,
    maximum_deviation_percent: float,
) -> AaveDcaSwapPriceValidationResult:
    if binance_reference_price_usd <= 0:
        return AaveDcaSwapPriceValidationResult(
            is_acceptable=False,
            deviation_expected_percent=100.0,
            deviation_minimum_percent=100.0,
            binance_reference_price_usd=binance_reference_price_usd,
            implied_expected_price_usd=0.0,
            implied_minimum_price_usd=0.0,
        )

    implied_expected_price_usd: float = compute_implied_swap_price_usd(
        source_amount_base_units=source_amount_base_units,
        target_amount_base_units=lifi_expected_output_amount_base_units,
        source_asset_decimals=source_asset_decimals,
        target_asset_decimals=target_asset_decimals,
    )
    implied_minimum_price_usd: float = compute_implied_swap_price_usd(
        source_amount_base_units=source_amount_base_units,
        target_amount_base_units=lifi_minimum_output_amount_base_units,
        source_asset_decimals=source_asset_decimals,
        target_asset_decimals=target_asset_decimals,
    )

    deviation_expected_percent: float = compute_price_deviation_percent(
        reference_price_usd=binance_reference_price_usd,
        implied_price_usd=implied_expected_price_usd,
    )
    deviation_minimum_percent: float = compute_price_deviation_percent(
        reference_price_usd=binance_reference_price_usd,
        implied_price_usd=implied_minimum_price_usd,
    )

    return AaveDcaSwapPriceValidationResult(
        is_acceptable=deviation_expected_percent <= maximum_deviation_percent,
        deviation_expected_percent=deviation_expected_percent,
        deviation_minimum_percent=deviation_minimum_percent,
        binance_reference_price_usd=binance_reference_price_usd,
        implied_expected_price_usd=implied_expected_price_usd,
        implied_minimum_price_usd=implied_minimum_price_usd,
    )


def compute_pipeline_backoff_delay_seconds(attempt_count: int) -> int:
    exponential_delay_seconds: int = settings.AAVE_DCA_PIPELINE_BASE_BACKOFF_SECONDS * (2 ** max(attempt_count - 1, 0))
    return min(exponential_delay_seconds, settings.AAVE_DCA_PIPELINE_MAX_BACKOFF_SECONDS)


def compute_pipeline_next_attempt_at(attempt_count: int) -> datetime:
    delay_seconds: int = compute_pipeline_backoff_delay_seconds(attempt_count)
    return get_current_local_datetime() + timedelta(seconds=delay_seconds)


async def run_aave_dca_live_pipeline_preflight_checks(
    aave_executor: AaveExecutor,
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

    native_gas_balance_avax: float = await aave_executor.fetch_native_gas_balance_avax(blockchain)
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
        aave_supply_balance: float = await aave_executor.fetch_token_balance(blockchain, source_asset_address)
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

    wallet_source_balance_wei: int = await aave_executor.fetch_erc20_balance(blockchain, source_asset_address)
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


def resolve_pipeline_step_descriptor(order_status: AaveDcaOrderStatus) -> Optional[tuple[int, str]]:
    if order_status == AaveDcaOrderStatus.AWAITING_WITHDRAW:
        return 1, "Withdraw Aave"
    if order_status == AaveDcaOrderStatus.AWAITING_SWAP:
        return 2, "Swap LI.FI"
    if order_status == AaveDcaOrderStatus.AWAITING_SUPPLY:
        return 3, "Supply Aave"
    return None


async def poll_erc20_balance_until_minimum(
    aave_executor: AaveExecutor,
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
        last_observed_balance_wei = await aave_executor.fetch_erc20_balance(blockchain, token_address)
        if last_observed_balance_wei >= minimum_balance_wei:
            logger.debug(
                "[AAVEDCA][HELPERS][SETTLEMENT] Target token balance reflects swap settlement — token_address=%s poll_attempt_count=%d balance_wei=%d minimum_balance_wei=%d",
                token_address,
                poll_attempt_count,
                last_observed_balance_wei,
                minimum_balance_wei,
            )
            return last_observed_balance_wei
        await asyncio.sleep(poll_interval_seconds)

    logger.warning(
        "[AAVEDCA][HELPERS][SETTLEMENT] Target token balance polling timed out — token_address=%s poll_attempt_count=%d last_balance_wei=%d minimum_balance_wei=%d timeout_seconds=%s",
        token_address,
        poll_attempt_count,
        last_observed_balance_wei,
        minimum_balance_wei,
        timeout_seconds,
    )
    return last_observed_balance_wei


def resolve_allocation_decision_display_title(allocation_decision: AaveDcaAllocationDecision) -> str:
    if allocation_decision == AaveDcaAllocationDecision.AGGRESSIVE_DIP_ACCUMULATION_SCALED:
        return "Accumulation Agressive 🚀"
    if allocation_decision == AaveDcaAllocationDecision.CONSERVATIVE_RETENTION_SCALED:
        return "Accumulation Prudente 🛡️"
    if allocation_decision == AaveDcaAllocationDecision.FALLBACK_NOMINAL_STRATEGY:
        return "Stratégie Nominale ⚖️"
    if allocation_decision == AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT:
        return "Protection PRU [Halt] 🛑"
    return "Exécution Stratégique"


def format_allocation_decision_label(
        allocation_decision: AaveDcaAllocationDecision,
        allocation_multiplier: Optional[float],
) -> str:
    if allocation_multiplier is not None and allocation_multiplier != 1.0:
        return f"{allocation_decision.value} (×{allocation_multiplier:.2f})"
    return allocation_decision.value


def create_empty_pipeline_operations() -> dict[str, object]:
    current_timestamp_iso: str = get_current_local_datetime().isoformat()
    empty_pipeline_operations = AaveDcaOrderPipelineOperations(
        initialized_at=current_timestamp_iso,
        last_updated_at=current_timestamp_iso,
        pipeline_operations=[],
    )
    return empty_pipeline_operations.model_dump(mode="json")


def deserialize_pipeline_operations(
        raw_pipeline_operations: Optional[dict[str, object]],
) -> AaveDcaOrderPipelineOperations:
    if raw_pipeline_operations is None:
        return AaveDcaOrderPipelineOperations(
            initialized_at=None,
            last_updated_at=None,
            pipeline_operations=[],
        )
    return AaveDcaOrderPipelineOperations.model_validate(raw_pipeline_operations)


def serialize_pipeline_operations(
        pipeline_operations: AaveDcaOrderPipelineOperations,
) -> dict[str, object]:
    return pipeline_operations.model_dump(mode="json")


def append_completed_pipeline_operation(
        existing_pipeline_operations: Optional[dict[str, object]],
        pipeline_operation: AaveDcaPipelineOperation,
) -> dict[str, object]:
    pipeline_operations_container = deserialize_pipeline_operations(existing_pipeline_operations)
    updated_pipeline_operations: list[AaveDcaPipelineOperation] = list(pipeline_operations_container.pipeline_operations)
    updated_pipeline_operations.append(pipeline_operation)
    current_timestamp_iso: str = get_current_local_datetime().isoformat()
    updated_container = AaveDcaOrderPipelineOperations(
        initialized_at=pipeline_operations_container.initialized_at or current_timestamp_iso,
        last_updated_at=current_timestamp_iso,
        pipeline_operations=updated_pipeline_operations,
    )
    return serialize_pipeline_operations(updated_container)

