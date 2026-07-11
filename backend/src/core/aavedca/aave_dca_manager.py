from __future__ import annotations

import asyncio
import html
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavedca.aave_dca_allocation_engine import AaveDcaAllocationEngine
from src.core.aavedca.aave_dca_helpers import (
    append_completed_pipeline_operation,
    convert_token_amount_to_base_units,
    create_empty_pipeline_operations,
    poll_erc20_balance_until_minimum,
    resolve_allocation_decision_display_title,
    run_aave_dca_live_pipeline_preflight_checks,
    validate_lifi_swap_price_against_binance_reference,
    compute_pipeline_next_attempt_at,
)
from src.core.aavedca.aave_dca_notification_service import publish_dca_order_telegram_message
from src.core.aavedca.aave_dca_structures import (
    AaveDcaAllocationDecision,
    AaveDcaBlockingPipelineError,
    AaveDcaOrderStatus,
    AaveDcaPipelineOperation,
    AaveDcaPipelineOperationStatus,
    AaveDcaPipelineOperationStep,
    AaveDcaPipelinePreflightFailureReason,
    AaveDcaStrategyStatus,
    AaveDcaTransientPipelineError,
)
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
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
from src.integrations.telegram.telegram_client import send_alert
from src.logging.logger import get_application_logger
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)


class AaveDcaManager:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session
        self.dca_strategy_dao = AaveDcaStrategyDao(database_session)
        self.dca_order_dao = AaveDcaOrderDao(database_session)
        self.aave_executor = AaveExecutor()

    def _resolve_allocation_decision(self, dca_order: AaveDcaOrder) -> Optional[AaveDcaAllocationDecision]:
        if dca_order.allocation_decision is None:
            return None
        return AaveDcaAllocationDecision(dca_order.allocation_decision)

    def _finalize_skipped_order(
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
        self._reset_pipeline_recovery_state(dca_order)
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
        self._publish_order_telegram_message(dca_order, dca_strategy, status_note=status_note)

    def _record_pipeline_operation(
            self,
            dca_order: AaveDcaOrder,
            pipeline_step: AaveDcaPipelineOperationStep,
            pipeline_status: AaveDcaPipelineOperationStatus,
            transaction_hash: Optional[str] = None,
            route_tool: Optional[str] = None,
            source_amount_base_units: Optional[int] = None,
            expected_output_base_units: Optional[int] = None,
            minimum_output_base_units: Optional[int] = None,
    ) -> None:
        current_timestamp_iso: str = get_current_local_datetime().isoformat()
        pipeline_operation = AaveDcaPipelineOperation(
            step=pipeline_step,
            status=pipeline_status,
            started_at=current_timestamp_iso,
            completed_at=current_timestamp_iso,
            transaction_hash=transaction_hash,
            route_tool=route_tool,
            source_amount_base_units=source_amount_base_units,
            expected_output_base_units=expected_output_base_units,
            minimum_output_base_units=minimum_output_base_units,
        )
        dca_order.pipeline_operations = append_completed_pipeline_operation(
            dca_order.pipeline_operations,
            pipeline_operation,
        )

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

    async def process_scheduled_dca_order(self, dca_order: AaveDcaOrder, dca_strategy: AaveDcaStrategy) -> None:
        pipeline_resume_statuses = (
            AaveDcaOrderStatus.AWAITING_WITHDRAW,
            AaveDcaOrderStatus.AWAITING_SWAP,
            AaveDcaOrderStatus.AWAITING_SUPPLY,
        )
        if dca_order.order_status in pipeline_resume_statuses:
            logger.info(
                "[AAVEDCA][MANAGER][RESUME] Resuming in-flight pipeline for order identifier %s at status %s",
                dca_order.id,
                dca_order.order_status,
            )
            await self.execute_onchain_defi_routing_pipeline(dca_order, dca_strategy)
            return

        logger.info("[AAVEDCA][MANAGER][EVALUATE] Evaluating scheduled order identifier %s for strategy identifier %s", dca_order.id, dca_strategy.id)

        current_local_time = get_current_local_datetime()
        unspent_investment_budget = dca_strategy.total_allocated_budget - dca_strategy.total_deployed_amount

        if unspent_investment_budget > 0:
            last_calculation_timestamp = dca_strategy.last_yield_calculation_timestamp.astimezone()
            elapsed_seconds = (current_local_time - last_calculation_timestamp).total_seconds()

            if elapsed_seconds > 0:
                year_fraction = elapsed_seconds / 31536000.0
                blockchain = BlockchainNetwork(dca_strategy.blockchain_network.lower())
                current_supply_annual_percentage_yield = await self.aave_executor.fetch_supply_apy(blockchain, dca_strategy.source_asset_address)
                accrued_yield_amount = unspent_investment_budget * current_supply_annual_percentage_yield * year_fraction
                dca_strategy.realized_aave_yield_amount += accrued_yield_amount
                logger.info(
                    "[AAVEDCA][MANAGER][YIELD] Yield accrued: +$%0.4f (APY: %0.2f%% over %0.2f days)",
                    accrued_yield_amount,
                    current_supply_annual_percentage_yield * 100,
                    elapsed_seconds / 86400
                )

        dca_strategy.last_yield_calculation_timestamp = current_local_time
        self.database_session.commit()

        blockchain = BlockchainNetwork(dca_strategy.blockchain_network.lower())
        is_conflicting_debt_detected = await self.aave_executor.verify_active_debt(blockchain, dca_strategy.target_asset_address)
        if is_conflicting_debt_detected:
            logger.error("[AAVEDCA][MANAGER][DEBT] Conflicting borrow position detected for target asset. Suspending strategy safety first.")
            dca_strategy.strategy_status = AaveDcaStrategyStatus.PAUSED
            self.database_session.commit()
            send_alert(
                f"[{dca_strategy.target_asset_symbol}] Stratégie Suspendue",
                f"🪙 Actif: {dca_strategy.target_asset_symbol}\n"
                f"🛑 Raison: Position d'emprunt (Debt) active détectée sur Aave. Suspension de sécurité.",
                "⛔"
            )
            return

        if dca_order.order_status == AaveDcaOrderStatus.PENDING:
            ema_warmup_limit = settings.AAVE_DCA_EMA50_WARMUP_KLINES
            market_data = await fetch_exponential_moving_average_and_price(dca_strategy.binance_trading_pair, "1h", ema_warmup_limit)

            allocation_verdict = AaveDcaAllocationEngine.calculate_dynamic_allocation(
                nominal_investment_amount=dca_order.planned_source_asset_amount,
                current_dry_powder_reserve=dca_strategy.available_dry_powder,
                current_market_price=market_data.latest_closing_price,
                current_macro_ema=market_data.exponential_moving_average,
                current_average_purchase_price=dca_strategy.average_purchase_price,
                price_elasticity_aggressiveness=dca_strategy.average_unit_price_elasticity_factor
            )

            dca_order.executed_source_asset_amount = allocation_verdict.spend_amount
            dca_order.allocation_decision = allocation_verdict.allocation_decision.value
            dca_order.allocation_multiplier = allocation_verdict.allocation_multiplier
            dca_order.dry_powder_delta = allocation_verdict.dry_powder_delta
            dca_order.reference_market_price = market_data.latest_closing_price
            dca_order.pipeline_operations = create_empty_pipeline_operations()
            if allocation_verdict.spend_amount > 0:
                dca_order.actual_execution_price = market_data.latest_closing_price
            else:
                dca_order.actual_execution_price = None
            self.dca_order_dao.save(dca_order)

            logger.info(
                "[AAVEDCA][MANAGER][ALLOCATION] Decision resolved [%s]: Planned=%0.2f, Actual=%0.2f, DryPowder Delta=%0.2f",
                allocation_verdict.allocation_decision.value,
                dca_order.planned_source_asset_amount,
                dca_order.executed_source_asset_amount,
                allocation_verdict.dry_powder_delta
            )

            if not dca_strategy.bypass_security_approval:
                logger.info("[AAVEDCA][MANAGER][APPROVAL] Order identifier %s requires user authorization before proceeding", dca_order.id)
                dca_order.order_status = AaveDcaOrderStatus.WAITING_USER_APPROVAL
                self.dca_order_dao.save(dca_order)
                self._publish_order_telegram_message(dca_order, dca_strategy)
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
                return

            if allocation_verdict.allocation_decision == AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT:
                pru_status_note = (
                    f"🛑 <b>Bouclier PRU activé</b> — prix marché supérieur au PRU "
                    f"(<code>${dca_strategy.average_purchase_price:.2f}</code>).\n"
                    f"Accumulation stoppée, <code>${dca_order.planned_source_asset_amount:.2f}</code> "
                    f"vers Dry powder."
                )
                self._finalize_skipped_order(
                    dca_order=dca_order,
                    dca_strategy=dca_strategy,
                    dry_powder_delta=allocation_verdict.dry_powder_delta,
                    status_note=pru_status_note,
                )
                return

            pru_status_note = None

            dca_order.order_status = AaveDcaOrderStatus.AWAITING_WITHDRAW
            self.dca_order_dao.save(dca_order)
            self._publish_order_telegram_message(dca_order, dca_strategy, status_note=pru_status_note)

        await self.execute_onchain_defi_routing_pipeline(dca_order, dca_strategy)

    def _reset_pipeline_recovery_state(self, dca_order: AaveDcaOrder) -> None:
        dca_order.pipeline_attempt_count = 0
        dca_order.next_attempt_at = None
        dca_order.suspension_reason = None

    def _suspend_order(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            suspension_reason: str,
    ) -> None:
        dca_order.suspension_reason = suspension_reason
        dca_order.next_attempt_at = None
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
        logger.warning(
            "[AAVEDCA][MANAGER][SUSPEND] Order_id=%s suspended at status=%s reason=%s",
            dca_order.id,
            dca_order.order_status,
            suspension_reason,
        )
        self._publish_order_telegram_message(dca_order, dca_strategy)

    def _schedule_transient_retry(
            self,
            dca_order: AaveDcaOrder,
            failure_message: str,
    ) -> None:
        dca_order.pipeline_attempt_count += 1
        if dca_order.pipeline_attempt_count > settings.AAVE_DCA_PIPELINE_MAX_RETRY_ATTEMPTS:
            logger.warning(
                "[AAVEDCA][MANAGER][RETRY] Order_id=%s exceeded max retry attempts (%s): %s",
                dca_order.id,
                settings.AAVE_DCA_PIPELINE_MAX_RETRY_ATTEMPTS,
                failure_message,
            )
            raise AaveDcaBlockingPipelineError(
                AaveDcaPipelinePreflightFailureReason.MAX_RETRIES_EXCEEDED.value,
                failure_message,
            )

        dca_order.next_attempt_at = compute_pipeline_next_attempt_at(dca_order.pipeline_attempt_count)
        self.dca_order_dao.save(dca_order)
        self.database_session.commit()
        cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
        logger.warning(
            "[AAVEDCA][MANAGER][RETRY] Order_id=%s transient failure at status=%s attempt=%s next_attempt_at=%s message=%s",
            dca_order.id,
            dca_order.order_status,
            dca_order.pipeline_attempt_count,
            dca_order.next_attempt_at,
            failure_message,
        )

    def _schedule_transient_retry_with_strategy(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            failure_message: str,
    ) -> None:
        self._schedule_transient_retry(dca_order, failure_message)
        self._publish_order_telegram_message(dca_order, dca_strategy)

    async def _run_live_pipeline_preflight(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy,
            blockchain: BlockchainNetwork,
            amount_in_base_units: int,
            order_status: AaveDcaOrderStatus,
    ) -> None:
        preflight_result = await run_aave_dca_live_pipeline_preflight_checks(
            aave_executor=self.aave_executor,
            blockchain=blockchain,
            order_status=order_status,
            source_asset_address=dca_strategy.source_asset_address,
            source_asset_decimals=dca_strategy.source_asset_decimals,
            required_execution_amount_base_units=amount_in_base_units,
            minimum_native_gas_reserve_avax=settings.AAVE_DCA_MINIMUM_NATIVE_GAS_RESERVE_AVAX,
        )

        if preflight_result.is_successful:
            logger.debug(
                "[AAVEDCA][MANAGER][PREFLIGHT] Checks passed for order_id=%s status=%s native_gas_balance_avax=%s aave_supply_balance=%s wallet_source_balance=%s required_amount_base_units=%s",
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
            "[AAVEDCA][MANAGER][PREFLIGHT] Live pipeline preflight failed for order_id=%s status=%s failure_reason=%s native_gas_balance_avax=%s aave_supply_balance=%s wallet_source_balance=%s required_amount_base_units=%s minimum_native_gas_reserve_avax=%s",
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

    async def execute_onchain_defi_routing_pipeline(
            self,
            dca_order: AaveDcaOrder,
            dca_strategy: AaveDcaStrategy
    ) -> None:
        dry_powder_delta = dca_order.planned_source_asset_amount - (dca_order.executed_source_asset_amount or 0.0)

        if settings.AAVE_DCA_PAPER_MODE:
            logger.info("[AAVEDCA][MANAGER][PAPER] Paper Mode active: initiating sequential simulation of technical routing pipeline")

            if dca_order.order_status == AaveDcaOrderStatus.WAITING_USER_APPROVAL:
                logger.info("[AAVEDCA][MANAGER][APPROVAL] Order identifier %s is still waiting for user approval. Skipping for this cycle.", dca_order.id)
                return

            if dca_order.order_status == AaveDcaOrderStatus.REJECTED:
                logger.warning("[AAVEDCA][MANAGER][APPROVAL] Order identifier %s was rejected. Skipping for this cycle.", dca_order.id)
                return

            try:
                if dca_order.executed_source_asset_amount == 0.0:
                    logger.info("[AAVEDCA][MANAGER][PAPER] Execution bypass: Amount is 0 (PRU Protection active). Finalizing accounting only.")
                    self._finalize_skipped_order(
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
                    "[AAVEDCA][MANAGER][PAPER][ERROR] Pipeline execution failed at status %s for order identifier %s",
                    dca_order.order_status,
                    dca_order.id
                )
                dca_order.order_status = AaveDcaOrderStatus.FAILED
                self.dca_order_dao.save(dca_order)
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
                self._publish_order_telegram_message(
                    dca_order,
                    dca_strategy,
                    status_note=f"⚠️ <b>Erreur:</b> <code>{html.escape(str(exception))}</code>",
                )
            return

        try:
            current_order_status: AaveDcaOrderStatus = dca_order.order_status

            if current_order_status == AaveDcaOrderStatus.WAITING_USER_APPROVAL:
                logger.info("[AAVEDCA][MANAGER][APPROVAL] Order identifier %s is still waiting for user approval. Skipping for this cycle.", dca_order.id)
                return

            if current_order_status == AaveDcaOrderStatus.REJECTED:
                logger.warning("[AAVEDCA][MANAGER][APPROVAL] Order identifier %s was rejected. Skipping for this cycle.", dca_order.id)
                return

            if dca_order.executed_source_asset_amount == 0.0:
                logger.info("[AAVEDCA][MANAGER][PIPELINE] Execution bypass: Amount is 0 (Protection active). Finalizing accounting only.")
                self._finalize_skipped_order(
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

            amount_in_base_units: int = convert_token_amount_to_base_units(
                token_amount=dca_order.executed_source_asset_amount or 0.0,
                token_decimals=dca_strategy.source_asset_decimals,
            )
            blockchain = BlockchainNetwork(dca_strategy.blockchain_network.lower())
            minimum_target_balance_wei: int = 1

            await self._run_live_pipeline_preflight(
                dca_order=dca_order,
                dca_strategy=dca_strategy,
                blockchain=blockchain,
                amount_in_base_units=amount_in_base_units,
                order_status=current_order_status,
            )

            if current_order_status == AaveDcaOrderStatus.AWAITING_WITHDRAW:
                logger.debug("[AAVEDCA][MANAGER][PIPELINE] Step 1/3: Withdrawing %s liquidity from Aave lending pool", dca_strategy.source_asset_symbol)
                try:
                    withdrawal_transaction_hash = await self.aave_executor.execute_withdrawal(
                        blockchain,
                        dca_strategy.source_asset_address,
                        amount_in_base_units,
                    )
                except Exception as onchain_error:
                    raise AaveDcaBlockingPipelineError(
                        AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
                        str(onchain_error),
                    ) from onchain_error
                if not withdrawal_transaction_hash:
                    raise AaveDcaTransientPipelineError("Aave withdrawal transaction not confirmed")

                self._record_pipeline_operation(
                    dca_order=dca_order,
                    pipeline_step=AaveDcaPipelineOperationStep.WITHDRAW,
                    pipeline_status=AaveDcaPipelineOperationStatus.COMPLETED,
                    transaction_hash=withdrawal_transaction_hash,
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
                    "[AAVEDCA][MANAGER][PIPELINE] Step 2/3: Ensuring LI.FI allowance, fetching reference price, then requesting a fresh swap quote"
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
                    "[AAVEDCA][MANAGER][PIPELINE] Guaranteed minimum output for swap: %d units expected output: %d units tool=%s",
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
                        "[AAVEDCA][MANAGER][SWAP][PRICE] LI.FI quote rejected for order_id=%s tool=%s binance_price_usd=%s implied_expected_price_usd=%s implied_minimum_price_usd=%s deviation_expected_percent=%s deviation_minimum_percent=%s maximum_deviation_percent=%s alternative_route_count=%s",
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
                        "[AAVEDCA][MANAGER][SWAP][PRICE] Alternative LI.FI routes for order_id=%s: %s",
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

                try:
                    swap_transaction_hash = await self.aave_executor.execute_raw_evm_transaction(
                        chain=blockchain,
                        to_address=transaction_request.to,
                        transaction_calldata=transaction_request.data,
                        transaction_value_wei=transaction_value_in_wei,
                        gas_limit=swap_gas_limit,
                    )
                except Exception as onchain_error:
                    raise AaveDcaBlockingPipelineError(
                        AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
                        str(onchain_error),
                    ) from onchain_error
                if not swap_transaction_hash:
                    raise AaveDcaTransientPipelineError("DeFi routed swap transaction not confirmed")

                self._record_pipeline_operation(
                    dca_order=dca_order,
                    pipeline_step=AaveDcaPipelineOperationStep.SWAP,
                    pipeline_status=AaveDcaPipelineOperationStatus.COMPLETED,
                    transaction_hash=swap_transaction_hash,
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
                logger.debug("[AAVEDCA][MANAGER][PIPELINE] Step 3/3: Supplying newly acquired asset back to Aave lending pool")
                target_asset_balance_wei = await poll_erc20_balance_until_minimum(
                    aave_executor=self.aave_executor,
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
                    supply_transaction_hash = await self.aave_executor.execute_supply(
                        blockchain,
                        dca_strategy.target_asset_address,
                        target_asset_balance_wei,
                    )
                except Exception as onchain_error:
                    raise AaveDcaBlockingPipelineError(
                        AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
                        str(onchain_error),
                    ) from onchain_error
                if not supply_transaction_hash:
                    raise AaveDcaTransientPipelineError("Aave supply transaction not confirmed")

                self._record_pipeline_operation(
                    dca_order=dca_order,
                    pipeline_step=AaveDcaPipelineOperationStep.SUPPLY,
                    pipeline_status=AaveDcaPipelineOperationStatus.COMPLETED,
                    transaction_hash=supply_transaction_hash,
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
                self._reset_pipeline_recovery_state(dca_order)
                self.dca_order_dao.save(dca_order)
                cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
                self._publish_order_telegram_message(dca_order, dca_strategy)

        except AaveDcaBlockingPipelineError as blocking_error:
            self._suspend_order(dca_order, dca_strategy, blocking_error.reason)
        except AaveDcaTransientPipelineError as transient_error:
            try:
                self._schedule_transient_retry_with_strategy(dca_order, dca_strategy, str(transient_error))
            except AaveDcaBlockingPipelineError as max_retries_error:
                self._suspend_order(dca_order, dca_strategy, max_retries_error.reason)
        except LifiQuoteUnavailableError as quote_unavailable_error:
            logger.warning(
                "[AAVEDCA][MANAGER][SWAP][LIFI] No LI.FI route for order_id=%s status=%s source_amount_base_units=%s message=%s",
                dca_order.id,
                dca_order.order_status,
                amount_in_base_units,
                quote_unavailable_error.response_message or str(quote_unavailable_error),
            )
            self._suspend_order(
                dca_order,
                dca_strategy,
                AaveDcaPipelinePreflightFailureReason.LIFI_QUOTE_INVALID.value,
            )
        except (ValidationError, LifiRouteNormalizationError, ValueError) as integration_error:
            logger.warning(
                "[AAVEDCA][MANAGER][INTEGRATION] Non-retryable LI.FI integration failure at status %s for order_id=%s: %s",
                dca_order.order_status,
                dca_order.id,
                integration_error,
            )
            self._suspend_order(
                dca_order,
                dca_strategy,
                AaveDcaPipelinePreflightFailureReason.LIFI_QUOTE_INVALID.value,
            )
        except Exception as unexpected_error:
            logger.exception(
                "[AAVEDCA][MANAGER][ERROR] Unexpected pipeline failure at status %s for order_id=%s",
                dca_order.order_status,
                dca_order.id,
            )
            self._suspend_order(
                dca_order,
                dca_strategy,
                AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED.value,
            )
