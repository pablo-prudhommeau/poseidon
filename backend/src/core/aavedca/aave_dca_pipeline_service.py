from __future__ import annotations

import asyncio
import html
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavedca.aave_dca_notification_service import publish_dca_order_telegram_message
from src.core.aavedca.aave_dca_pipeline_preflight_service import AaveDcaPipelinePreflightService
from src.core.aavedca.aave_dca_pipeline_recovery_service import AaveDcaPipelineRecoveryService
from src.core.aavedca.aave_dca_structures import (
    AaveDcaAllocationDecision,
    AaveDcaBlockingPipelineError,
    AaveDcaOrderStatus,
    AaveDcaPipelineOperationStep,
    AaveDcaPipelinePreflightFailureReason,
    AaveDcaTransientPipelineError,
)
from src.core.aavedca.aave_dca_helpers import validate_lifi_swap_price_against_binance_reference
from src.core.aavedca.aave_dca_utils import (
    convert_token_amount_to_base_units,
    resolve_allocation_decision_display_title,
)
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.aave.aave_structures import (
    AaveEvmTransactionConfirmationFailureKind,
    AaveEvmTransactionConfirmationOutcome,
)
from src.integrations.binance.binance_client import fetch_exponential_moving_average_and_price
from src.integrations.lifi.lifi_client import (
    fetch_alternative_token_to_token_route_summaries,
    generate_token_to_token_route,
)
from src.integrations.lifi.lifi_helpers import (
    LIFI_EVM_DIAMOND_CONTRACT_ADDRESS,
    parse_lifi_hex_or_decimal_integer,
    resolve_lifi_transaction_gas_limit_in_units,
)
from src.integrations.lifi.lifi_structures import LifiAlternativeRouteSummary, LifiQuoteUnavailableError, LifiRouteNormalizationError
from src.logging.logger import get_application_logger
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)


class AaveDcaPipelineService:
    def __init__(
            self,
            database_session: Session,
            dca_order_dao: AaveDcaOrderDao,
            dca_strategy_dao: AaveDcaStrategyDao,
            aave_executor: AaveExecutor,
            preflight_service: AaveDcaPipelinePreflightService,
            recovery_service: AaveDcaPipelineRecoveryService,
    ) -> None:
        self.database_session = database_session
        self.dca_order_dao = dca_order_dao
        self.dca_strategy_dao = dca_strategy_dao
        self.aave_executor = aave_executor
        self.preflight_service = preflight_service
        self.recovery_service = recovery_service

    def _resolve_allocation_decision(self, dca_order: AaveDcaOrder) -> Optional[AaveDcaAllocationDecision]:
        if dca_order.allocation_decision is None:
            return None
        return AaveDcaAllocationDecision(dca_order.allocation_decision)

    def _publish_order_telegram_message(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            status_note: Optional[str] = None,
    ) -> None:
        publish_dca_order_telegram_message(
            dca_order=dca_order,
            dca_strategy=dca_strategy,
            order_dao=self.dca_order_dao,
            status_note=status_note,
        )

    def finalize_skipped_order(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            dry_powder_delta: float,
            status_note: Optional[str],
    ) -> None:
        dca_order.order_status = AaveDcaOrderStatus.SKIPPED
        dca_order.executed_at = get_current_local_datetime()
        dca_order.executed_target_asset_amount = 0.0
        dca_order.dry_powder_delta = dry_powder_delta
        dca_strategy.available_dry_powder += dry_powder_delta
        self.dca_strategy_dao.update_strategy_execution_metrics(
            dca_strategy=dca_strategy,
            last_execution_source_amount=0.0,
        )
        self.recovery_service.reset_pipeline_recovery_state(dca_order)
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
        self._publish_order_telegram_message(dca_order, dca_strategy, status_note=status_note)

    async def execute_onchain_defi_routing_pipeline(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
    ) -> None:
        dry_powder_delta = dca_order.planned_source_asset_amount - (dca_order.executed_source_asset_amount or 0.0)

        if settings.AAVE_DCA_PAPER_MODE:
            await self._execute_paper_pipeline(dca_order, dca_strategy, dry_powder_delta)
            return

        await self._execute_live_pipeline(dca_order, dca_strategy, dry_powder_delta)

    async def _execute_paper_pipeline(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            dry_powder_delta: float,
    ) -> None:
        logger.info("[AAVEDCA][PIPELINE][PAPER] Paper Mode active: initiating sequential simulation of technical routing pipeline")

        if dca_order.order_status == AaveDcaOrderStatus.WAITING_USER_APPROVAL:
            logger.info("[AAVEDCA][PIPELINE][APPROVAL] Order identifier %s is still waiting for user approval. Skipping for this cycle.", dca_order.id)
            return

        if dca_order.order_status == AaveDcaOrderStatus.REJECTED:
            logger.warning("[AAVEDCA][PIPELINE][APPROVAL] Order identifier %s was rejected. Skipping for this cycle.", dca_order.id)
            return

        try:
            if dca_order.executed_source_asset_amount == 0.0:
                logger.info("[AAVEDCA][PIPELINE][PAPER] Execution bypass: Amount is 0 (PRU Protection active). Finalizing accounting only.")
                self.finalize_skipped_order(
                    dca_order=dca_order,
                    dca_strategy=dca_strategy,
                    dry_powder_delta=dry_powder_delta,
                    status_note=(
                        f"ℹ️ <b>Mode:</b> Paper\n"
                        f"🛡️ <b>PRU Protection:</b> <code>{dca_order.planned_source_asset_amount:.2f}</code> "
                        f"{dca_strategy.source_asset_symbol} routés vers Dry powder "
                        f"(<code>+{dry_powder_delta:.2f}</code>, total <code>${dca_strategy.available_dry_powder:.2f}</code>)"
                    ),
                )
                return

            dca_order.executed_at = get_current_local_datetime()

            if dca_order.order_status == AaveDcaOrderStatus.AWAITING_WITHDRAW:
                dca_order.order_status = AaveDcaOrderStatus.AWAITING_SWAP
                self.dca_order_dao.save(dca_order)
                self.database_session.commit()
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
                self._publish_order_telegram_message(dca_order, dca_strategy)
                await asyncio.sleep(2)

            if dca_order.order_status == AaveDcaOrderStatus.AWAITING_SWAP:
                dca_order.order_status = AaveDcaOrderStatus.AWAITING_SUPPLY
                self.dca_order_dao.save(dca_order)
                self.database_session.commit()
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
                self._publish_order_telegram_message(dca_order, dca_strategy)
                await asyncio.sleep(2)

            if dca_order.order_status == AaveDcaOrderStatus.AWAITING_SUPPLY:
                dca_order.order_status = AaveDcaOrderStatus.EXECUTED
                if dca_order.executed_source_asset_amount > 0 and dca_order.actual_execution_price > 0:
                    dca_order.executed_target_asset_amount = dca_order.executed_source_asset_amount / dca_order.actual_execution_price
                else:
                    dca_order.executed_target_asset_amount = 0.0

                dca_strategy.available_dry_powder += dry_powder_delta
                self.dca_strategy_dao.update_strategy_execution_metrics(
                    dca_strategy=dca_strategy,
                    last_execution_source_amount=dca_order.executed_source_asset_amount or 0.0,
                    last_execution_target_asset_amount=dca_order.executed_target_asset_amount,
                    last_execution_reference_price=dca_order.actual_execution_price,
                )
                self.dca_order_dao.save(dca_order)
                self.database_session.commit()
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)

            resolved_allocation_decision = self._resolve_allocation_decision(dca_order)
            display_title = (
                resolve_allocation_decision_display_title(resolved_allocation_decision)
                if resolved_allocation_decision is not None
                else "Exécution Stratégique"
            )
            self._publish_order_telegram_message(
                dca_order,
                dca_strategy,
                status_note=(
                    f"ℹ️ <b>Mode:</b> Paper — {display_title}\n"
                    f"🔄 <b>Échange:</b> <code>{dca_order.executed_source_asset_amount:.2f}</code> "
                    f"{dca_strategy.source_asset_symbol} ➔ {dca_strategy.target_asset_symbol}\n"
                    f"📦 <b>Dry powder:</b> <code>{'+' if dry_powder_delta >= 0 else '-'}${abs(dry_powder_delta):.2f}</code> "
                    f"(total <code>${dca_strategy.available_dry_powder:.2f}</code>)"
                ),
            )

        except Exception as exception:
            logger.exception(
                "[AAVEDCA][PIPELINE][PAPER][ERROR] Pipeline execution failed at status %s for order identifier %s",
                dca_order.order_status,
                dca_order.id,
            )
            dca_order.order_status = AaveDcaOrderStatus.FAILED
            self.dca_order_dao.save(dca_order)
            cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
            self._publish_order_telegram_message(
                dca_order,
                dca_strategy,
                status_note=f"⚠️ <b>Erreur:</b> <code>{html.escape(str(exception))}</code>",
            )

    async def _execute_live_pipeline(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            dry_powder_delta: float,
    ) -> None:
        amount_in_base_units: int = 0
        try:
            current_order_status: AaveDcaOrderStatus = dca_order.order_status

            if current_order_status == AaveDcaOrderStatus.WAITING_USER_APPROVAL:
                logger.info("[AAVEDCA][PIPELINE][APPROVAL] Order identifier %s is still waiting for user approval. Skipping for this cycle.", dca_order.id)
                return

            if current_order_status == AaveDcaOrderStatus.REJECTED:
                logger.warning("[AAVEDCA][PIPELINE][APPROVAL] Order identifier %s was rejected. Skipping for this cycle.", dca_order.id)
                return

            if dca_order.executed_source_asset_amount == 0.0:
                logger.info("[AAVEDCA][PIPELINE] Execution bypass: Amount is 0 (Protection active). Finalizing accounting only.")
                self.finalize_skipped_order(
                    dca_order=dca_order,
                    dca_strategy=dca_strategy,
                    dry_powder_delta=dry_powder_delta,
                    status_note=(
                        f"🛡️ <b>PRU Protection:</b> <code>{dca_order.planned_source_asset_amount:.2f}</code> "
                        f"{dca_strategy.source_asset_symbol} routés vers Dry powder "
                        f"(<code>+{dry_powder_delta:.2f}</code>, total <code>${dca_strategy.available_dry_powder:.2f}</code>)"
                    ),
                )
                return

            amount_in_base_units = convert_token_amount_to_base_units(
                token_amount=dca_order.executed_source_asset_amount or 0.0,
                token_decimals=dca_strategy.source_asset_decimals,
            )
            blockchain = BlockchainNetwork(dca_strategy.blockchain_network.lower())
            minimum_target_balance_wei: int = 1

            await self.preflight_service.run_live_pipeline_preflight(
                dca_order=dca_order,
                dca_strategy=dca_strategy,
                blockchain=blockchain,
                amount_in_base_units=amount_in_base_units,
                order_status=current_order_status,
            )

            if current_order_status == AaveDcaOrderStatus.AWAITING_WITHDRAW:
                logger.debug("[AAVEDCA][PIPELINE] Step 1/3: Withdrawing %s liquidity from Aave lending pool", dca_strategy.source_asset_symbol)
                try:
                    withdrawal_confirmation_outcome = await self.aave_executor.execute_withdrawal(
                        blockchain,
                        dca_strategy.source_asset_address,
                        amount_in_base_units,
                    )
                except Exception as onchain_error:
                    self.recovery_service.record_pre_broadcast_pipeline_failure(
                        dca_order=dca_order,
                        pipeline_step=AaveDcaPipelineOperationStep.WITHDRAW,
                        failure_message=str(onchain_error),
                        source_amount_base_units=amount_in_base_units,
                    )
                    raise AaveDcaBlockingPipelineError(
                        AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
                        str(onchain_error),
                    ) from onchain_error

                self.recovery_service.resolve_pipeline_step_onchain_outcome(
                    dca_order=dca_order,
                    pipeline_step=AaveDcaPipelineOperationStep.WITHDRAW,
                    pipeline_step_label="Aave withdrawal",
                    confirmation_outcome=withdrawal_confirmation_outcome,
                    source_amount_base_units=amount_in_base_units,
                )

                dca_order.order_status = AaveDcaOrderStatus.AWAITING_SWAP
                current_order_status = AaveDcaOrderStatus.AWAITING_SWAP
                self.dca_order_dao.save(dca_order)
                self.database_session.commit()
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
                self._publish_order_telegram_message(dca_order, dca_strategy)

            if current_order_status == AaveDcaOrderStatus.AWAITING_SWAP:
                logger.debug(
                    "[AAVEDCA][PIPELINE] Step 2/3: Ensuring LI.FI allowance, fetching reference price, then requesting a fresh swap quote"
                )
                await self.aave_executor._initialize_provider(blockchain)
                current_wallet_address = self.aave_executor.get_wallet_address()

                await self.aave_executor.ensure_erc20_allowance(
                    chain=blockchain,
                    token_address=dca_strategy.source_asset_address,
                    spender_address=LIFI_EVM_DIAMOND_CONTRACT_ADDRESS,
                    required_amount_wei=amount_in_base_units,
                )

                binance_market_data = await fetch_exponential_moving_average_and_price(
                    dca_strategy.binance_trading_pair,
                    "1h",
                    2,
                )

                swap_route = await asyncio.to_thread(
                    generate_token_to_token_route,
                    chain=blockchain,
                    source_address=current_wallet_address,
                    source_token_address=dca_strategy.source_asset_address,
                    destination_token_address=dca_strategy.target_asset_address,
                    source_amount_wei=amount_in_base_units,
                    slippage_tolerance=dca_strategy.slippage_tolerance,
                )

                minimum_expected_out_units: int = 0
                expected_out_units: int = 0
                selected_route_tool: Optional[str] = None
                if swap_route.estimate is not None:
                    selected_route_tool = swap_route.estimate.tool
                    if swap_route.estimate.to_amount is not None:
                        expected_out_units = parse_lifi_hex_or_decimal_integer(swap_route.estimate.to_amount)
                    if swap_route.estimate.to_amount_min is not None:
                        minimum_expected_out_units = parse_lifi_hex_or_decimal_integer(swap_route.estimate.to_amount_min)

                if expected_out_units <= 0:
                    raise AaveDcaTransientPipelineError("LI.FI routing quote returned no expected output amount")
                if minimum_expected_out_units <= 0:
                    raise AaveDcaTransientPipelineError("LI.FI routing quote returned no minimum output amount")

                logger.debug(
                    "[AAVEDCA][PIPELINE] Guaranteed minimum output for swap: %d units expected output: %d units tool=%s",
                    minimum_expected_out_units,
                    expected_out_units,
                    selected_route_tool,
                )

                minimum_target_balance_wei = minimum_expected_out_units

                swap_price_validation = validate_lifi_swap_price_against_binance_reference(
                    binance_reference_price_usd=binance_market_data.latest_closing_price,
                    lifi_expected_output_amount_base_units=expected_out_units,
                    lifi_minimum_output_amount_base_units=minimum_expected_out_units,
                    source_amount_base_units=amount_in_base_units,
                    source_asset_decimals=dca_strategy.source_asset_decimals,
                    target_asset_decimals=dca_strategy.target_asset_decimals,
                    maximum_deviation_percent=settings.AAVE_DCA_SWAP_PRICE_DEVIATION_MAX_PERCENT,
                )
                if not swap_price_validation.is_acceptable:
                    alternative_route_summaries: list[LifiAlternativeRouteSummary] = await asyncio.to_thread(
                        fetch_alternative_token_to_token_route_summaries,
                        blockchain,
                        current_wallet_address,
                        dca_strategy.source_asset_address,
                        dca_strategy.target_asset_address,
                        amount_in_base_units,
                        dca_strategy.slippage_tolerance,
                    )
                    logger.warning(
                        "[AAVEDCA][PIPELINE][SWAP][PRICE] LI.FI quote rejected for order_id=%s tool=%s binance_price_usd=%s implied_expected_price_usd=%s implied_minimum_price_usd=%s deviation_expected_percent=%s deviation_minimum_percent=%s maximum_deviation_percent=%s alternative_route_count=%s",
                        dca_order.id,
                        selected_route_tool,
                        swap_price_validation.binance_reference_price_usd,
                        swap_price_validation.implied_expected_price_usd,
                        swap_price_validation.implied_minimum_price_usd,
                        swap_price_validation.deviation_expected_percent,
                        swap_price_validation.deviation_minimum_percent,
                        settings.AAVE_DCA_SWAP_PRICE_DEVIATION_MAX_PERCENT,
                        len(alternative_route_summaries),
                    )
                    logger.debug(
                        "[AAVEDCA][PIPELINE][SWAP][PRICE] Alternative LI.FI routes for order_id=%s: %s",
                        dca_order.id,
                        alternative_route_summaries,
                    )
                    raise AaveDcaTransientPipelineError(
                        f"LI.FI swap quote price deviation {swap_price_validation.deviation_expected_percent:.2f}% "
                        f"exceeds maximum {settings.AAVE_DCA_SWAP_PRICE_DEVIATION_MAX_PERCENT:.2f}%"
                    )

                transaction_request = swap_route.transaction_request
                if transaction_request is None:
                    raise AaveDcaTransientPipelineError("LI.FI routing quote returned no EVM transaction request")

                transaction_value_in_wei: int = 0
                if transaction_request.value:
                    transaction_value_in_wei = parse_lifi_hex_or_decimal_integer(transaction_request.value)

                swap_gas_limit = resolve_lifi_transaction_gas_limit_in_units(transaction_request)

                pre_broadcast_revert_reason = await self.aave_executor.simulate_evm_transaction_before_broadcast(
                    chain=blockchain,
                    to_address=transaction_request.to,
                    transaction_calldata=transaction_request.data,
                    transaction_value_wei=transaction_value_in_wei,
                    gas_limit=swap_gas_limit,
                )
                if pre_broadcast_revert_reason is not None:
                    pre_broadcast_simulation_outcome = AaveEvmTransactionConfirmationOutcome(
                        transaction_hash=None,
                        is_confirmed=False,
                        confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.REVERTED,
                        onchain_revert_reason=pre_broadcast_revert_reason,
                    )
                    self.recovery_service.resolve_pipeline_step_onchain_outcome(
                        dca_order=dca_order,
                        pipeline_step=AaveDcaPipelineOperationStep.SWAP,
                        pipeline_step_label="DeFi routed swap",
                        confirmation_outcome=pre_broadcast_simulation_outcome,
                        route_tool=selected_route_tool,
                        source_amount_base_units=amount_in_base_units,
                        expected_output_base_units=expected_out_units,
                        minimum_output_base_units=minimum_expected_out_units,
                    )

                try:
                    swap_confirmation_outcome = await self.aave_executor.execute_raw_evm_transaction(
                        chain=blockchain,
                        to_address=transaction_request.to,
                        transaction_calldata=transaction_request.data,
                        transaction_value_wei=transaction_value_in_wei,
                        gas_limit=swap_gas_limit,
                    )
                except Exception as onchain_error:
                    self.recovery_service.record_pre_broadcast_pipeline_failure(
                        dca_order=dca_order,
                        pipeline_step=AaveDcaPipelineOperationStep.SWAP,
                        failure_message=str(onchain_error),
                        route_tool=selected_route_tool,
                        source_amount_base_units=amount_in_base_units,
                        expected_output_base_units=expected_out_units,
                        minimum_output_base_units=minimum_expected_out_units,
                    )
                    raise AaveDcaBlockingPipelineError(
                        AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
                        str(onchain_error),
                    ) from onchain_error

                self.recovery_service.resolve_pipeline_step_onchain_outcome(
                    dca_order=dca_order,
                    pipeline_step=AaveDcaPipelineOperationStep.SWAP,
                    pipeline_step_label="DeFi routed swap",
                    confirmation_outcome=swap_confirmation_outcome,
                    route_tool=selected_route_tool,
                    source_amount_base_units=amount_in_base_units,
                    expected_output_base_units=expected_out_units,
                    minimum_output_base_units=minimum_expected_out_units,
                )

                dca_order.order_status = AaveDcaOrderStatus.AWAITING_SUPPLY
                current_order_status = AaveDcaOrderStatus.AWAITING_SUPPLY
                self.dca_order_dao.save(dca_order)
                self.database_session.commit()
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
                self._publish_order_telegram_message(dca_order, dca_strategy)

            if current_order_status == AaveDcaOrderStatus.AWAITING_SUPPLY:
                logger.debug("[AAVEDCA][PIPELINE] Step 3/3: Supplying newly acquired asset back to Aave lending pool")
                target_asset_balance_wei = await self.preflight_service.poll_target_asset_balance_after_swap(
                    blockchain=blockchain,
                    token_address=dca_strategy.target_asset_address,
                    minimum_balance_wei=minimum_target_balance_wei,
                    poll_interval_seconds=settings.AAVE_DCA_SWAP_SETTLEMENT_POLL_INTERVAL_SECONDS,
                    timeout_seconds=settings.AAVE_DCA_SWAP_SETTLEMENT_POLL_TIMEOUT_SECONDS,
                )

                if target_asset_balance_wei < minimum_target_balance_wei:
                    raise AaveDcaTransientPipelineError(
                        f"Target asset balance not reflected after swap "
                        f"(balance_wei={target_asset_balance_wei}, minimum_wei={minimum_target_balance_wei})"
                    )

                try:
                    supply_confirmation_outcome = await self.aave_executor.execute_supply(
                        blockchain,
                        dca_strategy.target_asset_address,
                        target_asset_balance_wei,
                    )
                except Exception as onchain_error:
                    self.recovery_service.record_pre_broadcast_pipeline_failure(
                        dca_order=dca_order,
                        pipeline_step=AaveDcaPipelineOperationStep.SUPPLY,
                        failure_message=str(onchain_error),
                    )
                    raise AaveDcaBlockingPipelineError(
                        AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
                        str(onchain_error),
                    ) from onchain_error

                self.recovery_service.resolve_pipeline_step_onchain_outcome(
                    dca_order=dca_order,
                    pipeline_step=AaveDcaPipelineOperationStep.SUPPLY,
                    pipeline_step_label="Aave supply",
                    confirmation_outcome=supply_confirmation_outcome,
                )

                dca_order.order_status = AaveDcaOrderStatus.EXECUTED
                dca_order.executed_at = get_current_local_datetime()
                dca_order.executed_target_asset_amount = target_asset_balance_wei / (10 ** dca_strategy.target_asset_decimals)

                dca_strategy.available_dry_powder += dry_powder_delta
                self.dca_strategy_dao.update_strategy_execution_metrics(
                    dca_strategy=dca_strategy,
                    last_execution_source_amount=dca_order.executed_source_asset_amount or 0.0,
                    last_execution_target_asset_amount=dca_order.executed_target_asset_amount,
                    last_execution_reference_price=dca_order.actual_execution_price,
                )
                self.recovery_service.reset_pipeline_recovery_state(dca_order)
                self.dca_order_dao.save(dca_order)
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
                self._publish_order_telegram_message(dca_order, dca_strategy)

        except AaveDcaBlockingPipelineError as blocking_error:
            self.recovery_service.suspend_order(dca_order, dca_strategy, blocking_error.reason)
        except AaveDcaTransientPipelineError as transient_error:
            try:
                self.recovery_service.schedule_transient_retry_with_strategy(dca_order, dca_strategy, str(transient_error))
            except AaveDcaBlockingPipelineError as max_retries_error:
                self.recovery_service.suspend_order(dca_order, dca_strategy, max_retries_error.reason)
        except LifiQuoteUnavailableError as quote_unavailable_error:
            logger.warning(
                "[AAVEDCA][PIPELINE][SWAP][LIFI] No LI.FI route for order_id=%s status=%s source_amount_base_units=%s message=%s",
                dca_order.id,
                dca_order.order_status,
                amount_in_base_units,
                quote_unavailable_error.response_message or str(quote_unavailable_error),
            )
            self.recovery_service.suspend_order(
                dca_order,
                dca_strategy,
                AaveDcaPipelinePreflightFailureReason.LIFI_QUOTE_INVALID.value,
            )
        except (ValidationError, LifiRouteNormalizationError, ValueError) as integration_error:
            logger.warning(
                "[AAVEDCA][PIPELINE][INTEGRATION] Non-retryable LI.FI integration failure at status %s for order_id=%s: %s",
                dca_order.order_status,
                dca_order.id,
                integration_error,
            )
            self.recovery_service.suspend_order(
                dca_order,
                dca_strategy,
                AaveDcaPipelinePreflightFailureReason.LIFI_QUOTE_INVALID.value,
            )
        except Exception as unexpected_error:
            logger.exception(
                "[AAVEDCA][PIPELINE][ERROR] Unexpected pipeline failure at status %s for order_id=%s",
                dca_order.order_status,
                dca_order.id,
            )
            self.recovery_service.suspend_order(
                dca_order,
                dca_strategy,
                AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
            )
