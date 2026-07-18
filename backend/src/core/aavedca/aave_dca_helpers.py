from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.core.aavedca.aave_dca_structures import (
    AllocationResult,
    AaveDcaAllocationDecision,
    AaveDcaBacktestMetadata,
    AaveDcaBacktestPayload,
    AaveDcaBacktestSeriesPoint,
    AaveDcaOrderStatus,
    AaveDcaOrderPipelineOperations,
    AaveDcaPipelineOnchainFailureClassification,
    AaveDcaPipelineOnchainFailureRetryPolicy,
    AaveDcaPipelineOnchainRevertRule,
    AaveDcaPipelineOperation,
    AaveDcaPipelinePreflightFailureReason,
    AaveDcaSwapPriceValidationResult,
)
from src.core.aavedca.aave_dca_utils import (
    compute_implied_swap_price_usd,
    compute_price_deviation_percent,
    resolve_closest_market_timestamp,
)
from src.core.utils.date_utils import convert_epoch_to_local_datetime, get_current_local_datetime
from src.integrations.aave.aave_structures import AaveEvmTransactionConfirmationFailureKind
from src.integrations.binance.binance_client import fetch_bulk_historical_candlesticks
from src.integrations.binance.binance_structures import CandlestickData
from src.logging.logger import get_application_logger
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)

AAVE_DCA_PIPELINE_KNOWN_ONCHAIN_REVERT_RULES: tuple[AaveDcaPipelineOnchainRevertRule, ...] = (
    AaveDcaPipelineOnchainRevertRule(
        onchain_revert_reason="QUOTE_SWAP_AMOUNT_TOO_SMALL",
        retry_policy=AaveDcaPipelineOnchainFailureRetryPolicy.BLOCKING,
        suspension_reason=AaveDcaPipelinePreflightFailureReason.SWAP_AMOUNT_BELOW_ROUTE_MINIMUM,
    ),
)


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


def append_pipeline_operation(
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


def classify_aave_dca_pipeline_onchain_failure(
        confirmation_failure_kind: Optional[AaveEvmTransactionConfirmationFailureKind],
        onchain_revert_reason: Optional[str],
) -> AaveDcaPipelineOnchainFailureClassification:
    if confirmation_failure_kind == AaveEvmTransactionConfirmationFailureKind.CONFIRMATION_TIMEOUT:
        return AaveDcaPipelineOnchainFailureClassification(
            onchain_revert_reason=onchain_revert_reason,
            retry_policy=AaveDcaPipelineOnchainFailureRetryPolicy.TRANSIENT,
            suspension_reason=AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED,
        )

    if onchain_revert_reason is None or not onchain_revert_reason.strip():
        return AaveDcaPipelineOnchainFailureClassification(
            onchain_revert_reason=onchain_revert_reason,
            retry_policy=AaveDcaPipelineOnchainFailureRetryPolicy.BLOCKING,
            suspension_reason=AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED,
        )

    normalized_onchain_revert_reason: str = onchain_revert_reason.strip()
    for known_revert_rule in AAVE_DCA_PIPELINE_KNOWN_ONCHAIN_REVERT_RULES:
        if normalized_onchain_revert_reason == known_revert_rule.onchain_revert_reason:
            return AaveDcaPipelineOnchainFailureClassification(
                onchain_revert_reason=normalized_onchain_revert_reason,
                retry_policy=known_revert_rule.retry_policy,
                suspension_reason=known_revert_rule.suspension_reason,
            )

    return AaveDcaPipelineOnchainFailureClassification(
        onchain_revert_reason=normalized_onchain_revert_reason,
        retry_policy=AaveDcaPipelineOnchainFailureRetryPolicy.BLOCKING,
        suspension_reason=AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED,
    )


def calculate_dynamic_allocation(
        nominal_investment_amount: float,
        current_dry_powder_reserve: float,
        current_market_price: float,
        current_macro_ema: float,
        current_average_purchase_price: float,
        price_elasticity_aggressiveness: float,
) -> AllocationResult:
    logger.debug(
        "[AAVEDCA][ALLOCATION][CHECK] Nominal: %s | DryPowder: %s | Price: %s | PRU: %s",
        nominal_investment_amount,
        current_dry_powder_reserve,
        current_market_price,
        current_average_purchase_price,
    )

    if current_average_purchase_price > 0 and current_market_price > current_average_purchase_price:
        logger.debug("[AAVEDCA][ALLOCATION][SKIP] Kill-switch active: market price is above average purchase price")
        return AllocationResult(
            spend_amount=0.0,
            dry_powder_delta=nominal_investment_amount,
            allocation_decision=AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT,
            allocation_multiplier=1.0,
        )

    investment_multiplier = 1.0
    if current_average_purchase_price > 0 and current_market_price <= current_average_purchase_price:
        distance_from_pru_percent = (current_average_purchase_price - current_market_price) / current_average_purchase_price
        investment_multiplier = 1.0 + (distance_from_pru_percent * price_elasticity_aggressiveness)
        logger.debug("[AAVEDCA][ALLOCATION][SCALING] Elasticity multiplier calculated: %s", investment_multiplier)

    if current_macro_ema > 0 and current_market_price > current_macro_ema:
        base_allocation_amount = nominal_investment_amount * 0.5
        target_spend_amount = base_allocation_amount * investment_multiplier
        allocation_decision = AaveDcaAllocationDecision.CONSERVATIVE_RETENTION_SCALED
    elif current_macro_ema > 0 and current_market_price <= current_macro_ema:
        base_allocation_amount = nominal_investment_amount + (current_dry_powder_reserve * 0.5)
        target_spend_amount = base_allocation_amount * investment_multiplier
        allocation_decision = AaveDcaAllocationDecision.AGGRESSIVE_DIP_ACCUMULATION_SCALED
    else:
        target_spend_amount = nominal_investment_amount * investment_multiplier
        allocation_decision = AaveDcaAllocationDecision.FALLBACK_NOMINAL_STRATEGY

    max_available_liquidity = nominal_investment_amount + current_dry_powder_reserve
    actual_spend_amount = min(target_spend_amount, max_available_liquidity)
    dry_powder_delta = nominal_investment_amount - actual_spend_amount

    logger.debug(
        "[AAVEDCA][ALLOCATION][RESULT] Decision: %s | Spend: %s | Multiplier: %s",
        allocation_decision.value,
        actual_spend_amount,
        investment_multiplier,
    )

    return AllocationResult(
        spend_amount=actual_spend_amount,
        dry_powder_delta=dry_powder_delta,
        allocation_decision=allocation_decision,
        allocation_multiplier=investment_multiplier,
    )


def generate_linear_execution_calendar(dca_strategy: AaveDcaStrategy) -> list[AaveDcaOrder]:
    scheduled_orders_collection: list[AaveDcaOrder] = []

    system_local_timezone = get_current_local_datetime().tzinfo

    strategy_start_date_local = dca_strategy.strategy_start_date
    if strategy_start_date_local.tzinfo is None:
        strategy_start_date_local = strategy_start_date_local.replace(tzinfo=system_local_timezone)

    strategy_end_date_local = dca_strategy.strategy_end_date
    if strategy_end_date_local.tzinfo is None:
        strategy_end_date_local = strategy_end_date_local.replace(tzinfo=system_local_timezone)

    total_strategy_duration_in_seconds = (strategy_end_date_local - strategy_start_date_local).total_seconds()

    if total_strategy_duration_in_seconds <= 0 or dca_strategy.total_planned_executions <= 0:
        logger.warning(
            "[AAVEDCA][CALENDAR][VALIDATION] Aborting calendar generation: invalid duration (%s s) or execution count (%s) for strategy id %s",
            total_strategy_duration_in_seconds,
            dca_strategy.total_planned_executions,
            dca_strategy.id,
        )
        return scheduled_orders_collection

    time_interval_between_executions_in_seconds = total_strategy_duration_in_seconds / dca_strategy.total_planned_executions
    current_iterative_timestamp = strategy_start_date_local.timestamp()

    logger.debug(
        "[AAVEDCA][CALENDAR][COMPUTE] Generating %s orders with an interval of %0.2f seconds",
        dca_strategy.total_planned_executions,
        time_interval_between_executions_in_seconds,
    )

    for execution_index in range(dca_strategy.total_planned_executions):
        calculated_scheduled_date = datetime.fromtimestamp(current_iterative_timestamp, tz=system_local_timezone)

        new_dca_order = AaveDcaOrder(
            strategy_id=dca_strategy.id,
            planned_execution_date=calculated_scheduled_date,
            planned_source_asset_amount=dca_strategy.amount_per_execution_order,
            executed_source_asset_amount=None,
            executed_target_asset_amount=None,
            order_status=AaveDcaOrderStatus.PENDING,
            actual_execution_price=None,
            executed_at=None,
            allocation_decision=None,
            allocation_multiplier=None,
            dry_powder_delta=None,
            reference_market_price=None,
            pipeline_operations=None,
            pipeline_attempt_count=0,
            next_attempt_at=None,
            suspension_reason=None,
            telegram_message_id=None,
        )
        scheduled_orders_collection.append(new_dca_order)

        current_iterative_timestamp += time_interval_between_executions_in_seconds

    logger.info(
        "[AAVEDCA][CALENDAR][SUCCESS] Successfully generated %d linear execution orders for strategy id %s",
        len(scheduled_orders_collection),
        dca_strategy.id,
    )
    return scheduled_orders_collection


async def generate_comparative_snapshot(
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        total_budget: float,
        total_execution_cycles: int,
        price_elasticity_aggressiveness: float,
) -> AaveDcaBacktestPayload:
    logger.info(
        "[AAVEDCA][BACKTEST][START] Initiating comparative simulation for %s with %d cycles",
        symbol,
        total_execution_cycles,
    )

    if total_execution_cycles <= 0 or total_budget <= 0.0:
        logger.error("[AAVEDCA][BACKTEST][VALIDATION] Total budget and execution cycles must be strictly positive")
        raise ValueError("Simulation parameters must be strictly positive")

    historical_candlesticks: list[CandlestickData] = await fetch_bulk_historical_candlesticks(
        symbol=symbol,
        start_time=start_date,
        end_time=end_date,
    )

    if not historical_candlesticks:
        logger.error("[AAVEDCA][BACKTEST][DATA] Failed to retrieve historical market data for %s", symbol)
        raise RuntimeError(f"Backtest aborted: No market data available for {symbol}")

    ema_calculations_map: dict[int, float] = {}
    market_price_map: dict[int, float] = {}

    current_exponential_moving_average = historical_candlesticks[0].closing_price
    ema_window_hours = 1200
    smoothing_factor = 2.0 / (ema_window_hours + 1.0)

    for candlestick in historical_candlesticks:
        current_exponential_moving_average = (
                (candlestick.closing_price - current_exponential_moving_average) * smoothing_factor
                + current_exponential_moving_average
        )
        ema_calculations_map[candlestick.closing_timestamp_milliseconds] = current_exponential_moving_average
        market_price_map[candlestick.closing_timestamp_milliseconds] = candlestick.closing_price

    start_timestamp_milliseconds = int(start_date.timestamp() * 1000)
    valid_market_timestamps = [
        candlestick.closing_timestamp_milliseconds
        for candlestick in historical_candlesticks
        if candlestick.closing_timestamp_milliseconds >= start_timestamp_milliseconds
    ]

    if not valid_market_timestamps:
        logger.error("[AAVEDCA][BACKTEST][DATA] Simulation window contains no valid market timestamps")
        raise RuntimeError("Simulation window is outside of available market data range")

    end_timestamp_milliseconds = int(end_date.timestamp() * 1000)
    cycle_interval_milliseconds = (end_timestamp_milliseconds - start_timestamp_milliseconds) / total_execution_cycles
    scheduled_execution_timestamps = [
        start_timestamp_milliseconds + int(index * cycle_interval_milliseconds)
        for index in range(total_execution_cycles)
    ]

    budget_per_execution_cycle = total_budget / total_execution_cycles

    standard_dca_series: list[AaveDcaBacktestSeriesPoint] = []
    dynamic_dca_series: list[AaveDcaBacktestSeriesPoint] = []

    standard_cumulative_spent = 0.0
    standard_accumulated_asset_units = 0.0

    dynamic_cumulative_spent = 0.0
    dynamic_accumulated_asset_units = 0.0
    dynamic_dry_powder_reserve = 0.0
    dynamic_average_purchase_price = 0.0
    total_market_overheat_preventions = 0

    for cycle_index, target_timestamp in enumerate(scheduled_execution_timestamps):
        actual_execution_timestamp = resolve_closest_market_timestamp(
            valid_market_timestamps,
            target_timestamp,
        )

        execution_date_iso = convert_epoch_to_local_datetime(actual_execution_timestamp).isoformat()
        current_market_price = market_price_map[actual_execution_timestamp]
        current_macro_ema = ema_calculations_map[actual_execution_timestamp]

        standard_cumulative_spent += budget_per_execution_cycle
        if current_market_price > 0.0:
            standard_accumulated_asset_units += budget_per_execution_cycle / current_market_price

        standard_average_purchase_price = (
            standard_cumulative_spent / standard_accumulated_asset_units
            if standard_accumulated_asset_units > 0.0
            else 0.0
        )

        standard_dca_series.append(
            AaveDcaBacktestSeriesPoint(
                timestamp_iso=execution_date_iso,
                execution_price=current_market_price,
                average_purchase_price=standard_average_purchase_price,
                cumulative_spent=standard_cumulative_spent,
                dry_powder_remaining=0.0,
            )
        )

        allocation_verdict = calculate_dynamic_allocation(
            nominal_investment_amount=budget_per_execution_cycle,
            current_dry_powder_reserve=dynamic_dry_powder_reserve,
            current_market_price=current_market_price,
            current_macro_ema=current_macro_ema,
            current_average_purchase_price=dynamic_average_purchase_price,
            price_elasticity_aggressiveness=price_elasticity_aggressiveness,
        )

        cycle_spend_amount = allocation_verdict.spend_amount
        dynamic_dry_powder_reserve += allocation_verdict.dry_powder_delta

        if allocation_verdict.allocation_decision == AaveDcaAllocationDecision.CONSERVATIVE_RETENTION_SCALED:
            total_market_overheat_preventions += 1

        dynamic_cumulative_spent += cycle_spend_amount
        if current_market_price > 0.0:
            dynamic_accumulated_asset_units += cycle_spend_amount / current_market_price

        dynamic_average_purchase_price = (
            dynamic_cumulative_spent / dynamic_accumulated_asset_units
            if dynamic_accumulated_asset_units > 0.0
            else 0.0
        )

        logger.debug(
            "[AAVEDCA][BACKTEST][STEP] [%s] Price: %s | Action: %s | Spent: %s | PRU: %s",
            execution_date_iso,
            current_market_price,
            allocation_verdict.allocation_decision.value,
            cycle_spend_amount,
            dynamic_average_purchase_price,
        )

        dynamic_dca_series.append(
            AaveDcaBacktestSeriesPoint(
                timestamp_iso=execution_date_iso,
                execution_price=current_market_price,
                average_purchase_price=dynamic_average_purchase_price,
                cumulative_spent=dynamic_cumulative_spent,
                dry_powder_remaining=dynamic_dry_powder_reserve,
            )
        )

    final_standard_pru = standard_dca_series[-1].average_purchase_price if standard_dca_series else 0.0
    final_dynamic_pru = dynamic_dca_series[-1].average_purchase_price if dynamic_dca_series else 0.0

    logger.info(
        "[AAVEDCA][BACKTEST][FINISH] Completed for %s. Standard PRU: %s | Dynamic PRU: %s",
        symbol,
        final_standard_pru,
        final_dynamic_pru,
    )

    return AaveDcaBacktestPayload(
        metadata=AaveDcaBacktestMetadata(
            source_asset_symbol=symbol,
            total_allocated_budget=total_budget,
            total_planned_executions=total_execution_cycles,
            final_dumb_average_unit_price=final_standard_pru,
            final_smart_average_unit_price=final_dynamic_pru,
            total_overheat_retentions=total_market_overheat_preventions,
        ),
        dumb_dca_series=standard_dca_series,
        smart_dca_series=dynamic_dca_series,
    )
