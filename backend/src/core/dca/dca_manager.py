from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.dca.dca_allocation_engine import DcaAllocationEngine
from src.core.structures.structures import DcaOrderStatus, DcaStrategyStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_executor import AaveExecutor
from src.integrations.binance.binance_client import fetch_exponential_moving_average_and_price
from src.integrations.lifi.lifi_client import build_token_to_token_quote, resolve_lifi_chain_id
from src.integrations.telegram.telegram_client import send_alert
from src.logging.logger import get_logger
from src.persistence.dao.dca_dao import DcaDao
from src.persistence.models import DcaOrder, DcaStrategy

logger = get_logger(__name__)


class DcaManager:
    """
    Orchestrates the business logic for Smart DCA execution.
    Relies on the universal DcaAllocationEngine for dynamic sizing.
    """

    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.dao = DcaDao(db_session)
        self.aave_executor = AaveExecutor()

    async def process_due_order(self, order: DcaOrder, strategy: DcaStrategy) -> None:
        logger.info("[DCA][MANAGER] Evaluating scheduled order %s for strategy %s", order.id, strategy.id)

        now = get_current_local_datetime()
        unspent_budget = strategy.total_budget - strategy.deployed_amount

        if unspent_budget > 0:
            last_calc = strategy.last_yield_calculation_at.astimezone()
            delta_seconds = (now - last_calc).total_seconds()
            if delta_seconds > 0:
                delta_years = delta_seconds / 31536000.0
                current_apy = await self.aave_executor.fetch_supply_apy(strategy.chain, strategy.asset_in_address)
                yield_chunk = unspent_budget * current_apy * delta_years
                strategy.realized_aave_yield += yield_chunk
                logger.info("[DCA][MANAGER] Yield accrued: +$%.4f (APY: %.2f%% over %.2f days)", yield_chunk, current_apy * 100, delta_seconds / 86400)

        strategy.last_yield_calculation_at = now
        self.db_session.commit()

        active_debt_detected = await self.aave_executor.verify_active_debt(strategy.chain, strategy.asset_out_address)
        if active_debt_detected:
            logger.error("[DCA][MANAGER] Conflicting borrow position detected. Suspending strategy.")
            strategy.status = DcaStrategyStatus.PAUSED
            self.db_session.commit()
            send_alert(
                "DCA Suspendu",
                f"🪙 Actif : {strategy.asset_out_symbol}\n"
                f"🛑 Raison : Position d'emprunt détectée.",
                "⛔"
            )
            return

        dry_powder_delta = 0.0

        if order.status in (DcaOrderStatus.PENDING, DcaOrderStatus.WAITING_USER_APPROVAL, DcaOrderStatus.APPROVED):
            warmup_limit = settings.AAVE_DCA_EMA50_WARMUP_KLINES
            exponential_moving_average_and_price = await fetch_exponential_moving_average_and_price(strategy.binance_pair, "1h", warmup_limit)

            pending_orders_count = self.dao.get_pending_orders_count(strategy.id)
            is_last_execution = (pending_orders_count == 1)

            allocation = DcaAllocationEngine.calculate_allocation(
                nominal_tranche=order.planned_amount,
                current_dry_powder=strategy.dry_powder,
                current_price=exponential_moving_average_and_price.latest_closing_price,
                current_macro_ema=exponential_moving_average_and_price.exponential_moving_average,
                current_pru=strategy.average_purchase_price,
                is_last_execution=is_last_execution,
                pru_elasticity_factor=strategy.pru_elasticity_factor
            )

            order.executed_amount_in = allocation.spend_amount
            order.execution_price = exponential_moving_average_and_price.latest_closing_price
            dry_powder_delta = allocation.dry_powder_delta
            self.dao.update_order(order)

            logger.info("[DCA][MANAGER] Allocation resolved [%s]: Planned=%.2f, Decided=%.2f, DryPowder Delta=%.2f",
                        allocation.action_description, order.planned_amount, allocation.spend_amount, dry_powder_delta)

            if not strategy.bypass_approval and not settings.PAPER_MODE and order.status != DcaOrderStatus.APPROVED:
                order.status = DcaOrderStatus.WAITING_USER_APPROVAL
                self.dao.update_order(order)

                if "KILL_SWITCH" in allocation.action_description:
                    send_alert(
                        "🛑 DCA Kill Switch Activé",
                        f"Le marché est au-dessus du PRU (${strategy.average_purchase_price:.2f}).\n"
                        f"L'achat est suspendu. {order.planned_amount:.2f} stockés dans le coffre.",
                        "⚠️"
                    )
                return

        await self.execute_defi_routing_flow(order, strategy, dry_powder_delta)

    async def execute_defi_routing_flow(self, order: DcaOrder, strategy: DcaStrategy, dry_powder_delta: float) -> None:
        if settings.PAPER_MODE:
            logger.info("[DCA][MANAGER] Paper Mode active. Simulating successful execution.")
            order.status = DcaOrderStatus.EXECUTED
            order.executed_at = get_current_local_datetime()

            if order.executed_amount_in > 0 and order.execution_price > 0:
                order.executed_amount_out = order.executed_amount_in / order.execution_price
            else:
                order.executed_amount_out = 0.0

            strategy.dry_powder += dry_powder_delta
            self.dao.update_strategy_execution_metrics(strategy, order.executed_amount_in or 0.0, order.execution_price or 0.0)
            self.dao.update_order(order)

            send_alert(
                "DCA Exécuté",
                f"ℹ️ Note : Transaction simulée (Paper Mode)\n\n"
                f"🔄 Tranche : {order.executed_amount_in:.2f} {strategy.asset_in_symbol} ➔ {strategy.asset_out_symbol}\n"
                f"💲 Prix d'exécution : ${order.execution_price:.2f}\n"
                f"🌐 Réseau : {strategy.chain.capitalize()}",
                "✅"
            )
            return

        try:
            # Bypass DeFi routing entirely if Kill Switch set spend to 0
            if order.executed_amount_in == 0.0:
                logger.info("[DCA][MANAGER] Execution bypass: Amount is 0 (Kill Switch). Applying accounting only.")
                order.status = DcaOrderStatus.EXECUTED
                order.executed_at = get_current_local_datetime()
                order.executed_amount_out = 0.0
                order.tx_hash = "KILL_SWITCH_BYPASS"

                strategy.dry_powder += dry_powder_delta
                self.dao.update_strategy_execution_metrics(strategy, 0.0, order.execution_price or 0.0)
                self.dao.update_order(order)
                return

            amount_in_wei = int((order.executed_amount_in or 0) * (10 ** strategy.asset_in_decimals))

            if order.status in (DcaOrderStatus.APPROVED, DcaOrderStatus.PENDING):
                logger.info("[DCA][MANAGER] Pipeline Step 1: Withdrawing %s liquidity from Aave.", strategy.asset_in_symbol)
                withdrawal_hash = await self.aave_executor.execute_withdrawal(strategy.chain, strategy.asset_in_address, amount_in_wei)
                if not withdrawal_hash:
                    raise RuntimeError("Withdrawal execution failed.")

                order.status = DcaOrderStatus.WITHDRAWN_FROM_AAVE
                self.dao.update_order(order)
                await asyncio.sleep(5)

            if order.status == DcaOrderStatus.WITHDRAWN_FROM_AAVE:
                logger.info("[DCA][MANAGER] Pipeline Step 2: Requesting LI.FI routing quote.")
                await self.aave_executor._initialize_provider(strategy.chain)
                wallet_address = self.aave_executor.get_wallet_address()

                quote = await asyncio.to_thread(
                    build_token_to_token_quote,
                    chain_key=strategy.chain,
                    from_address=wallet_address,
                    from_token_address=strategy.asset_in_address,
                    to_token_address=strategy.asset_out_address,
                    from_amount_wei=amount_in_wei,
                    slippage=strategy.slippage
                )

                expected_out_wei = int(quote["estimate"]["toAmountMin"])
                logger.info("[DCA][MANAGER] Minimum guaranteed output post-swap: %d Wei", expected_out_wei)

                numeric_chain_id = resolve_lifi_chain_id(strategy.chain)
                swap_hash = await self.aave_executor.approve_and_execute_raw_transaction(
                    chain=strategy.chain,
                    source_token=strategy.asset_in_address,
                    spender=quote["transactionRequest"]["to"],
                    amount_in_wei=amount_in_wei,
                    to_address=quote["transactionRequest"]["to"],
                    tx_data=quote["transactionRequest"]["data"],
                    tx_value=int(quote["transactionRequest"].get("value", 0), 16) if isinstance(quote["transactionRequest"].get("value"), str) else 0,
                    gas_limit=int(quote["transactionRequest"]["gasLimit"]),
                    chain_id_numeric=numeric_chain_id
                )
                if not swap_hash:
                    raise RuntimeError("Routed swap execution failed.")

                order.status = DcaOrderStatus.SWAPPED
                self.dao.update_order(order)
                await asyncio.sleep(6)

            if order.status == DcaOrderStatus.SWAPPED:
                logger.info("[DCA][MANAGER] Pipeline Step 3: Supplying accumulated asset to Aave.")
                asset_balance_wei = await self.aave_executor.fetch_erc20_balance(strategy.chain, strategy.asset_out_address)

                if asset_balance_wei <= 0:
                    raise RuntimeError("Target asset balance is zero after swap execution.")

                supply_hash = await self.aave_executor.execute_supply(strategy.chain, strategy.asset_out_address, asset_balance_wei)
                if not supply_hash:
                    raise RuntimeError("Supply execution failed.")

                order.status = DcaOrderStatus.EXECUTED
                order.tx_hash = supply_hash
                order.executed_at = get_current_local_datetime()
                order.executed_amount_out = asset_balance_wei / (10 ** 18)

                strategy.dry_powder += dry_powder_delta
                self.dao.update_strategy_execution_metrics(strategy, order.executed_amount_in or 0.0, order.execution_price or 0.0)
                self.dao.update_order(order)

                send_alert(
                    "DCA Exécuté avec Succès",
                    f"🔄 Tranche : {order.executed_amount_in:.2f} {strategy.asset_in_symbol} ➔ {strategy.asset_out_symbol}\n"
                    f"💲 Prix d'exécution : ${order.execution_price:.2f}\n"
                    f"🌐 Réseau : {strategy.chain.capitalize()}\n"
                    f"🔗 Transaction : {supply_hash[:10]}...",
                    "✅"
                )

        except Exception as exception:
            logger.error("[DCA][MANAGER] Critical failure during pipeline execution. Halting at state %s. Error: %s", order.status.name, exception)
            order.status = DcaOrderStatus.FAILED
            self.dao.update_order(order)
            send_alert(
                "Échec du Pipeline DCA",
                f"🆔 Ordre ID : {order.id}\n"
                f"🛑 État d'arrêt : {order.status.name}\n"
                f"⚠️ Erreur : {exception}",
                "❌"
            )
