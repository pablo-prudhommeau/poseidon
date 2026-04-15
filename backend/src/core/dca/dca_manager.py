from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from src.api.websocket.websocket_hub import schedule_full_recompute_broadcast
from src.configuration.config import settings
from src.core.dca.dca_allocation_engine import DcaAllocationEngine
from src.core.structures.structures import DcaOrderStatus, DcaStrategyStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.binance.binance_client import fetch_exponential_moving_average_and_price
from src.integrations.lifi.lifi_client import generate_token_to_token_quote, resolve_lifi_chain_identifier
from src.integrations.telegram.telegram_client import send_alert
from src.integrations.telegram.telegram_structures import (
    TelegramInlineKeyboardButton,
    TelegramInlineKeyboardMarkup,
)
from src.logging.logger import get_application_logger
from src.persistence.dao.dca.dca_order_dao import DcaOrderDao
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao
from src.persistence.models import DcaOrder, DcaStrategy

logger = get_application_logger(__name__)


class DcaManager:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session
        self.dca_strategy_dao = DcaStrategyDao(database_session)
        self.dca_order_dao = DcaOrderDao(database_session)
        self.aave_executor = AaveExecutor()

    def _resolve_action_display_title(self, action_description: str) -> str:
        if "AGGRESSIVE_DIP_ACCUMULATION" in action_description:
            return "Accumulation Agressive 🚀"
        if "CONSERVATIVE_RETENTION" in action_description:
            return "Accumulation Prudente 🛡️"
        if "FINAL_FULL_DEPLOYMENT" in action_description:
            return "Déploiement Final 🏁"
        if "FALLBACK_NOMINAL_STRATEGY" in action_description:
            return "Stratégie Nominale ⚖️"
        if "AVERAGE_PRICE_PROTECTION" in action_description:
            return "Protection PRU [Halt] 🛑"
        return "Exécution Stratégique"

    async def process_scheduled_dca_order(self, dca_order: DcaOrder, dca_strategy: DcaStrategy) -> None:
        logger.info("[DCA][MANAGER][EVALUATE] Evaluating scheduled order identifier %s for strategy identifier %s", dca_order.id, dca_strategy.id)

        current_local_time = get_current_local_datetime()
        unspent_investment_budget = dca_strategy.total_allocated_budget - dca_strategy.total_deployed_amount

        if unspent_investment_budget > 0:
            last_calculation_timestamp = dca_strategy.last_yield_calculation_timestamp.astimezone()
            elapsed_seconds = (current_local_time - last_calculation_timestamp).total_seconds()

            if elapsed_seconds > 0:
                year_fraction = elapsed_seconds / 31536000.0
                current_supply_annual_percentage_yield = await self.aave_executor.fetch_supply_apy(dca_strategy.blockchain_network, dca_strategy.source_asset_address)
                accrued_yield_amount = unspent_investment_budget * current_supply_annual_percentage_yield * year_fraction
                dca_strategy.realized_aave_yield_amount += accrued_yield_amount
                logger.info(
                    "[DCA][MANAGER][YIELD] Yield accrued: +$%0.4f (APY: %0.2f%% over %0.2f days)",
                    accrued_yield_amount,
                    current_supply_annual_percentage_yield * 100,
                    elapsed_seconds / 86400
                )

        dca_strategy.last_yield_calculation_timestamp = current_local_time
        self.database_session.commit()

        is_conflicting_debt_detected = await self.aave_executor.verify_active_debt(dca_strategy.blockchain_network, dca_strategy.target_asset_address)
        if is_conflicting_debt_detected:
            logger.error("[DCA][MANAGER][DEBT] Conflicting borrow position detected for target asset. Suspending strategy safety first.")
            dca_strategy.strategy_status = DcaStrategyStatus.PAUSED
            self.database_session.commit()
            send_alert(
                f"[{dca_strategy.target_asset_symbol}] Stratégie Suspendue",
                f"🪙 Actif: {dca_strategy.target_asset_symbol}\n"
                f"🛑 Raison: Position d'emprunt (Debt) active détectée sur Aave. Suspension de sécurité.",
                "⛔"
            )
            return

        if dca_order.order_status == DcaOrderStatus.PENDING:
            ema_warmup_limit = settings.AAVE_DCA_EMA50_WARMUP_KLINES
            market_data = await fetch_exponential_moving_average_and_price(dca_strategy.binance_trading_pair, "1h", ema_warmup_limit)

            pending_orders = self.dca_order_dao.retrieve_pending_by_strategy(dca_strategy.id)
            remaining_orders_count = len(pending_orders)
            is_final_execution = (remaining_orders_count <= 1)

            allocation_verdict = DcaAllocationEngine.calculate_dynamic_allocation(
                nominal_investment_amount=dca_order.planned_source_asset_amount,
                current_dry_powder_reserve=dca_strategy.available_dry_powder,
                current_market_price=market_data.latest_closing_price,
                current_macro_ema=market_data.exponential_moving_average,
                current_average_purchase_price=dca_strategy.average_purchase_price,
                is_last_execution_cycle=is_final_execution,
                price_elasticity_aggressiveness=dca_strategy.average_unit_price_elasticity_factor
            )

            dca_order.executed_source_asset_amount = allocation_verdict.spend_amount
            dca_order.actual_execution_price = market_data.latest_closing_price
            dca_order.allocation_decision_description = allocation_verdict.action_description
            self.dca_order_dao.save(dca_order)

            logger.info(
                "[DCA][MANAGER][ALLOCATION] Decision resolved [%s]: Planned=%0.2f, Actual=%0.2f, DryPowder Delta=%0.2f",
                allocation_verdict.action_description,
                dca_order.planned_source_asset_amount,
                dca_order.executed_source_asset_amount,
                allocation_verdict.dry_powder_delta
            )

            if not dca_strategy.bypass_security_approval:
                logger.info("[DCA][MANAGER][APPROVAL] Order identifier %s requires user authorization before proceeding", dca_order.id)
                dca_order.order_status = DcaOrderStatus.WAITING_USER_APPROVAL
                self.dca_order_dao.save(dca_order)
                self._send_approval_request(dca_order, dca_strategy)
                schedule_full_recompute_broadcast()
                return

            if "AVERAGE_PRICE_PROTECTION" in allocation_verdict.action_description:
                send_alert(
                    f"[{dca_strategy.target_asset_symbol}] bouclier PRU Activé",
                    f"Prix de marché supérieur au PRU (${dca_strategy.average_purchase_price:.2f}).\n"
                    f"Accumulation stoppée. {dca_order.planned_source_asset_amount:.2f} {dca_strategy.source_asset_symbol} transférés vers le coffre (Dry Powder).",
                    "🛑"
                )

            dca_order.order_status = DcaOrderStatus.APPROVED
            self.dca_order_dao.save(dca_order)

        await self.execute_onchain_defi_routing_pipeline(dca_order, dca_strategy)

    async def execute_onchain_defi_routing_pipeline(
            self,
            dca_order: DcaOrder,
            dca_strategy: DcaStrategy
    ) -> None:
        dry_powder_delta = dca_order.planned_source_asset_amount - (dca_order.executed_source_asset_amount or 0.0)

        if settings.PAPER_MODE:
            logger.info("[DCA][MANAGER][PAPER] Paper Mode active: initiating sequential simulation of technical routing pipeline")

            if dca_order.order_status == DcaOrderStatus.WAITING_USER_APPROVAL:
                logger.info("[DCA][MANAGER][APPROVAL] Order identifier %s is still waiting for user approval. Skipping for this cycle.", dca_order.id)
                return

            if dca_order.order_status == DcaOrderStatus.REJECTED:
                logger.warning("[DCA][MANAGER][APPROVAL] Order identifier %s was rejected. Skipping for this cycle.", dca_order.id)
                return

            try:
                if dca_order.executed_source_asset_amount == 0.0:
                    logger.info("[DCA][MANAGER][PAPER] Execution bypass: Amount is 0 (PRU Protection active). Finalizing accounting only.")
                    dca_order.order_status = DcaOrderStatus.EXECUTED
                    dca_order.executed_at = get_current_local_datetime()
                    dca_order.executed_target_asset_amount = 0.0
                    dca_order.transaction_hash = "AVERAGE_PRICE_PROTECTION_BYPASS"

                    dca_strategy.available_dry_powder += dry_powder_delta
                    self.dca_strategy_dao.update_strategy_execution_metrics(dca_strategy, 0.0, dca_order.actual_execution_price or 0.0)
                    self.dca_order_dao.save(dca_order)
                    schedule_full_recompute_broadcast()

                    send_alert(
                        f"[{dca_strategy.target_asset_symbol}] : PRU Protection",
                        f"ℹ️ Mode: Transaction simulée (Paper Mode)\n"
                        f"📊 Logique: {dca_order.allocation_decision_description}\n\n"
                        f"🛡️ PRU Protection: Budget ({dca_order.planned_source_asset_amount:.2f} {dca_strategy.source_asset_symbol}) routé vers Dry Powder\n"
                        f"📦 Dry Powder: +{dry_powder_delta:.2f} (${dca_strategy.available_dry_powder:.2f} total)\n"
                        f"🌐 Réseau: {dca_strategy.blockchain_network.upper()}",
                        "🛡️"
                    )
                    return

                dca_order.executed_at = get_current_local_datetime()

                if dca_order.order_status == DcaOrderStatus.APPROVED:
                    dca_order.order_status = DcaOrderStatus.WITHDRAWN_FROM_AAVE
                    self.dca_order_dao.save(dca_order)
                    self.database_session.commit()
                    schedule_full_recompute_broadcast()
                    await asyncio.sleep(2)

                if dca_order.order_status == DcaOrderStatus.WITHDRAWN_FROM_AAVE:
                    dca_order.order_status = DcaOrderStatus.SWAPPED
                    self.dca_order_dao.save(dca_order)
                    self.database_session.commit()
                    schedule_full_recompute_broadcast()
                    await asyncio.sleep(2)

                if dca_order.order_status == DcaOrderStatus.SWAPPED:
                    dca_order.order_status = DcaOrderStatus.EXECUTED
                    if dca_order.executed_source_asset_amount > 0 and dca_order.actual_execution_price > 0:
                        dca_order.executed_target_asset_amount = dca_order.executed_source_asset_amount / dca_order.actual_execution_price
                    else:
                        dca_order.executed_target_asset_amount = 0.0

                    dca_strategy.available_dry_powder += dry_powder_delta
                    self.dca_strategy_dao.update_strategy_execution_metrics(dca_strategy, dca_order.executed_source_asset_amount or 0.0, dca_order.actual_execution_price or 0.0)
                    self.dca_order_dao.save(dca_order)
                    self.database_session.commit()
                    schedule_full_recompute_broadcast()

                display_title = self._resolve_action_display_title(dca_order.allocation_decision_description or "UNKNOWN")
                send_alert(
                    f"[{dca_strategy.target_asset_symbol}] : {display_title}",
                    f"ℹ️ Mode: Transaction simulée (Paper Mode)\n"
                    f"📊 Logique: {dca_order.allocation_decision_description}\n\n"
                    f"🔄 Échange: {dca_order.executed_source_asset_amount:.2f} {dca_strategy.source_asset_symbol} ➔ {dca_strategy.target_asset_symbol}\n"
                    f"💰 Prix: ${dca_order.actual_execution_price:.2f} (PRU: ${dca_strategy.average_purchase_price:.2f})\n"
                    f"📦 Dry Powder: {dry_powder_delta >= 0 and '+' or ''}{dry_powder_delta:.2f} (${dca_strategy.available_dry_powder:.2f} total)\n"
                    f"🌐 Réseau: {dca_strategy.blockchain_network.upper()}",
                    "✅"
                )

            except Exception as exception:
                logger.exception(
                    "[DCA][MANAGER][PAPER][ERROR] Pipeline execution failed at status %s for order identifier %s",
                    dca_order.order_status,
                    dca_order.id
                )
                dca_order.order_status = DcaOrderStatus.FAILED
                self.dca_order_dao.save(dca_order)
                schedule_full_recompute_broadcast()
                send_alert(
                    f"[{dca_strategy.target_asset_symbol}] Échec du Pipeline (Paper)",
                    f"🆔 Ordre identifier: {dca_order.id}\n"
                    f"🛑 État Terminal: {dca_order.order_status}\n"
                    f"⚠️ Erreur: {str(exception)}",
                    "❌"
                )
            return

        try:
            if dca_order.executed_source_asset_amount == 0.0:
                logger.info("[DCA][MANAGER][PIPELINE] Execution bypass: Amount is 0 (Protection active). Finalizing accounting only.")
                dca_order.order_status = DcaOrderStatus.EXECUTED
                dca_order.executed_at = get_current_local_datetime()
                dca_order.executed_target_asset_amount = 0.0
                dca_order.transaction_hash = "AVERAGE_PRICE_PROTECTION_BYPASS"

                dca_strategy.available_dry_powder += dry_powder_delta
                self.dca_strategy_dao.update_strategy_execution_metrics(dca_strategy, 0.0, dca_order.actual_execution_price or 0.0)
                self.dca_order_dao.save(dca_order)
                return

            amount_in_base_units = int((dca_order.executed_source_asset_amount or 0) * (10 ** dca_strategy.source_asset_decimals))

            if dca_order.order_status == DcaOrderStatus.APPROVED.value:
                logger.info("[DCA][MANAGER][PIPELINE] Step 1/3: Withdrawing %s liquidity from Aave lending pool", dca_strategy.source_asset_symbol)
                withdrawal_transaction_hash = await self.aave_executor.execute_withdrawal(
                    dca_strategy.blockchain_network,
                    dca_strategy.source_asset_address,
                    amount_in_base_units
                )
                if not withdrawal_transaction_hash:
                    raise RuntimeError("Aave withdrawal execution failed at protocol level")

                dca_order.order_status = DcaOrderStatus.WITHDRAWN_FROM_AAVE
                self.dca_order_dao.save(dca_order)
                self.database_session.commit()
                schedule_full_recompute_broadcast()
                await asyncio.sleep(5)

            if dca_order.order_status == DcaOrderStatus.WITHDRAWN_FROM_AAVE.value:
                logger.info("[DCA][MANAGER][PIPELINE] Step 2/3: Fetching LI.FI routing quote for optimal swap path")
                await self.aave_executor._initialize_provider(dca_strategy.blockchain_network)
                current_wallet_address = self.aave_executor.get_wallet_address()

                routing_quote = await asyncio.to_thread(
                    generate_token_to_token_quote,
                    chain_key=dca_strategy.blockchain_network,
                    from_address=current_wallet_address,
                    from_token_address=dca_strategy.source_asset_address,
                    to_token_address=dca_strategy.target_asset_address,
                    from_amount_wei=amount_in_base_units,
                    slippage=dca_strategy.slippage_tolerance
                )

                minimum_expected_out_units = int(routing_quote["estimate"]["toAmountMin"])
                logger.info("[DCA][MANAGER][PIPELINE] Guaranteed minimum output for swap: %d units", minimum_expected_out_units)

                numeric_chain_identifier = resolve_lifi_chain_identifier(dca_strategy.blockchain_network)
                swap_transaction_hash = await self.aave_executor.approve_and_execute_raw_transaction(
                    chain=dca_strategy.blockchain_network,
                    source_token=dca_strategy.source_asset_address,
                    spender=routing_quote["transactionRequest"]["to"],
                    amount_in_wei=amount_in_base_units,
                    to_address=routing_quote["transactionRequest"]["to"],
                    tx_data=routing_quote["transactionRequest"]["data"],
                    tx_value=int(routing_quote["transactionRequest"].get("value", 0), 16) if isinstance(routing_quote["transactionRequest"].get("value"), str) else 0,
                    gas_limit=int(routing_quote["transactionRequest"]["gasLimit"]),
                    chain_id_numeric=numeric_chain_identifier
                )
                if not swap_transaction_hash:
                    raise RuntimeError("DeFi routed swap execution failed during transaction submission")

                dca_order.order_status = DcaOrderStatus.SWAPPED
                self.dca_order_dao.save(dca_order)
                self.database_session.commit()
                schedule_full_recompute_broadcast()
                await asyncio.sleep(6)

            if dca_order.order_status == DcaOrderStatus.SWAPPED.value:
                logger.info("[DCA][MANAGER][PIPELINE] Step 3/3: Supplying newly acquired asset back to Aave lending pool")
                target_asset_balance_wei = await self.aave_executor.fetch_erc20_balance(dca_strategy.blockchain_network, dca_strategy.target_asset_address)

                if target_asset_balance_wei <= 0:
                    raise RuntimeError("On-chain balance check failed: target asset balance is zero post-swap")

                supply_transaction_hash = await self.aave_executor.execute_supply(
                    dca_strategy.blockchain_network,
                    dca_strategy.target_asset_address,
                    target_asset_balance_wei
                )
                if not supply_transaction_hash:
                    raise RuntimeError("Aave supply execution failed at protocol level")

                dca_order.order_status = DcaOrderStatus.EXECUTED
                dca_order.transaction_hash = supply_transaction_hash
                dca_order.executed_at = get_current_local_datetime()
                dca_order.executed_target_asset_amount = target_asset_balance_wei / (10 ** 18)

                dca_strategy.available_dry_powder += dry_powder_delta
                self.dca_strategy_dao.update_strategy_execution_metrics(dca_strategy, dca_order.executed_source_asset_amount or 0.0, dca_order.actual_execution_price or 0.0)
                self.dca_order_dao.save(dca_order)
                schedule_full_recompute_broadcast()

                display_title = self._resolve_action_display_title(dca_order.allocation_decision_description or "UNKNOWN")
                send_alert(
                    f"[{dca_strategy.target_asset_symbol}] : {display_title}",
                    f"📊 Logique: {dca_order.allocation_decision_description}\n\n"
                    f"🔄 Échange: {dca_order.executed_source_asset_amount:.2f} {dca_strategy.source_asset_symbol} ➔ {dca_strategy.target_asset_symbol}\n"
                    f"💰 Prix: ${dca_order.actual_execution_price:.2f} (PRU: ${dca_strategy.average_purchase_price:.2f})\n"
                    f"📦 Dry Powder: {dry_powder_delta >= 0 and '+' or ''}{dry_powder_delta:.2f} (${dca_strategy.available_dry_powder:.2f} total)\n"
                    f"🌐 Réseau: {dca_strategy.blockchain_network.upper()}\n"
                    f"🔗 Hash: {supply_transaction_hash[:10]}...",
                    "✅"
                )

        except Exception as exception:
            logger.exception(
                "[DCA][MANAGER][ERROR] Pipeline execution failed at status %s. Halting for manual review.",
                dca_order.order_status,
                exception
            )
            dca_order.order_status = DcaOrderStatus.FAILED
            self.dca_order_dao.save(dca_order)
            schedule_full_recompute_broadcast()
            send_alert(
                f"[{dca_strategy.target_asset_symbol}] Échec du Pipeline",
                f"🆔 Ordre identifier: {dca_order.id}\n"
                f"🛑 État Terminal: {dca_order.order_status}\n"
                f"⚠️ Erreur: {str(exception)}",
                "❌"
            )

    def _generate_approval_message_body(self, dca_order: DcaOrder, dca_strategy: DcaStrategy) -> str:
        average_purchase_price_difference_percentage = 0.0
        if dca_strategy.average_purchase_price > 0:
            average_purchase_price_difference_percentage = ((dca_order.actual_execution_price or 0.0) / dca_strategy.average_purchase_price - 1) * 100

        price_trend_indicator_emoji = "📈" if average_purchase_price_difference_percentage > 0 else "📉"

        return (
            f"📦 <b>Ordre #{dca_order.id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔹 <b>Actif:</b> <code>{dca_strategy.target_asset_symbol}</code>\n"
            f"💵 <b>Montant:</b> <code>${dca_order.planned_source_asset_amount:.2f}</code>\n"
            f"💰 <b>Prix Actuel:</b> <code>${dca_order.actual_execution_price:.2f}</code>\n"
            f"{price_trend_indicator_emoji} <b>vs PRU:</b> <code>{average_purchase_price_difference_percentage:+.2f}%</code> (<code>${dca_strategy.average_purchase_price:.2f}</code>)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
        )

    def _send_approval_request(self, dca_order: DcaOrder, dca_strategy: DcaStrategy) -> None:
        title = "DEMANDE D'APPROBATION"
        message_body = self._generate_approval_message_body(dca_order, dca_strategy)
        footer = "Souhaitez-vous autoriser cette exécution ?"

        buttons = [
            [
                TelegramInlineKeyboardButton(text="✅ Approuver", callback_data=f"approve_dca:{dca_order.id}"),
                TelegramInlineKeyboardButton(text="❌ Rejeter", callback_data=f"reject_dca:{dca_order.id}")
            ]
        ]

        reply_markup = TelegramInlineKeyboardMarkup(inline_keyboard=buttons)

        send_alert(
            title=title,
            body=f"{message_body}{footer}",
            emoji_indicator="🛡️",
            reply_markup=reply_markup
        )

    def resync_waiting_approvals(self) -> None:
        logger.info("[DCA][MANAGER][RESYNC] Resynchronizing pending approval requests after startup")

        from src.persistence.db import _session
        with _session() as session_instance:
            strategy_dao_instance = DcaStrategyDao(session_instance)
            order_dao_instance = DcaOrderDao(session_instance)

            from sqlalchemy import select
            waiting_orders_query = select(DcaOrder).where(
                DcaOrder.order_status.in_([DcaOrderStatus.WAITING_USER_APPROVAL, DcaOrderStatus.REJECTED])
            )
            waiting_orders = session_instance.execute(waiting_orders_query).scalars().all()

            for order in waiting_orders:
                strategy = strategy_dao_instance.retrieve_by_id(order.strategy_id)
                if strategy:
                    logger.info("[DCA][MANAGER][RESYNC] Re-sending approval request for order identifier %s", order.id)
                    if order.order_status == DcaOrderStatus.REJECTED:
                        order.order_status = DcaOrderStatus.WAITING_USER_APPROVAL
                        order_dao_instance.save(order)
                        session_instance.commit()

                    self._send_approval_request(order, strategy)
