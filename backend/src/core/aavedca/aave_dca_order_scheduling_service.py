from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavedca.aave_dca_helpers import calculate_dynamic_allocation, create_empty_pipeline_operations
from src.core.aavedca.aave_dca_notification_service import publish_dca_order_telegram_message
from src.core.aavedca.aave_dca_pipeline_service import AaveDcaPipelineService
from src.core.aavedca.aave_dca_structures import (
    AaveDcaAllocationDecision,
    AaveDcaOrderStatus,
    AaveDcaStrategyStatus,
)
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.binance.binance_client import fetch_exponential_moving_average_and_price
from src.integrations.telegram.telegram_client import send_alert
from src.logging.logger import get_application_logger
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)


class AaveDcaOrderSchedulingService:
    def __init__(
            self,
            database_session: Session,
            dca_order_dao: AaveDcaOrderDao,
            dca_strategy_dao: AaveDcaStrategyDao,
            aave_executor: AaveExecutor,
            pipeline_service: AaveDcaPipelineService,
    ) -> None:
        self.database_session = database_session
        self.dca_order_dao = dca_order_dao
        self.dca_strategy_dao = dca_strategy_dao
        self.aave_executor = aave_executor
        self.pipeline_service = pipeline_service

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
                "[AAVEDCA][SCHEDULING][RESUME] Resuming in-flight pipeline for order identifier %s at status %s",
                dca_order.id,
                dca_order.order_status,
            )
            await self.pipeline_service.execute_onchain_defi_routing_pipeline(dca_order, dca_strategy)
            return

        logger.info("[AAVEDCA][SCHEDULING][EVALUATE] Evaluating scheduled order identifier %s for strategy identifier %s", dca_order.id, dca_strategy.id)

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
                    "[AAVEDCA][SCHEDULING][YIELD] Yield accrued: +$%0.4f (APY: %0.2f%% over %0.2f days)",
                    accrued_yield_amount,
                    current_supply_annual_percentage_yield * 100,
                    elapsed_seconds / 86400,
                )

        dca_strategy.last_yield_calculation_timestamp = current_local_time
        self.database_session.commit()

        blockchain = BlockchainNetwork(dca_strategy.blockchain_network.lower())
        is_conflicting_debt_detected = await self.aave_executor.verify_active_debt(blockchain, dca_strategy.target_asset_address)
        if is_conflicting_debt_detected:
            logger.error("[AAVEDCA][SCHEDULING][DEBT] Conflicting borrow position detected for target asset. Suspending strategy safety first.")
            dca_strategy.strategy_status = AaveDcaStrategyStatus.PAUSED
            self.database_session.commit()
            send_alert(
                f"[{dca_strategy.target_asset_symbol}] Stratégie Suspendue",
                f"🪙 Actif: {dca_strategy.target_asset_symbol}\n"
                f"🛑 Raison: Position d'emprunt (Debt) active détectée sur Aave. Suspension de sécurité.",
                "⛔",
            )
            return

        if dca_order.order_status == AaveDcaOrderStatus.PENDING:
            ema_warmup_limit = settings.AAVE_DCA_EMA50_WARMUP_KLINES
            market_data = await fetch_exponential_moving_average_and_price(dca_strategy.binance_trading_pair, "1h", ema_warmup_limit)

            allocation_verdict = calculate_dynamic_allocation(
                nominal_investment_amount=dca_order.planned_source_asset_amount,
                current_dry_powder_reserve=dca_strategy.available_dry_powder,
                current_market_price=market_data.latest_closing_price,
                current_macro_ema=market_data.exponential_moving_average,
                current_average_purchase_price=dca_strategy.average_purchase_price,
                price_elasticity_aggressiveness=dca_strategy.average_unit_price_elasticity_factor,
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
                "[AAVEDCA][SCHEDULING][ALLOCATION] Decision resolved [%s]: Planned=%0.2f, Actual=%0.2f, DryPowder Delta=%0.2f",
                allocation_verdict.allocation_decision.value,
                dca_order.planned_source_asset_amount,
                dca_order.executed_source_asset_amount,
                allocation_verdict.dry_powder_delta,
            )

            if not dca_strategy.bypass_security_approval:
                logger.info("[AAVEDCA][SCHEDULING][APPROVAL] Order identifier %s requires user authorization before proceeding", dca_order.id)
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
                self.pipeline_service.finalize_skipped_order(
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

        await self.pipeline_service.execute_onchain_defi_routing_pipeline(dca_order, dca_strategy)
