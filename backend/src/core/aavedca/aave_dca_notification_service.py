from __future__ import annotations

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.aavedca.aave_dca_structures import AaveDcaOrderStatus
from src.integrations.telegram.telegram_client import edit_message_text
from src.integrations.telegram.telegram_structures import TelegramCallbackQuery
from src.integrations.telegram.telegram_update_registry import telegram_update_registry
from src.logging.logger import get_application_logger
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)


def build_approval_message_body(dca_order: AaveDcaOrder, dca_strategy: AaveDcaStrategy) -> str:
    average_purchase_price_difference_percentage: float = 0.0
    if dca_strategy.average_purchase_price > 0:
        average_purchase_price_difference_percentage = (
            (dca_order.actual_execution_price or 0.0) / dca_strategy.average_purchase_price - 1
        ) * 100

    price_trend_indicator_emoji: str = "📈" if average_purchase_price_difference_percentage > 0 else "📉"

    return (
        f"📦 <b>Ordre #{dca_order.id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔹 <b>Actif:</b> <code>{dca_strategy.target_asset_symbol}</code>\n"
        f"💵 <b>Montant:</b> <code>${dca_order.planned_source_asset_amount:.2f}</code>\n"
        f"💰 <b>Prix Actuel:</b> <code>${dca_order.actual_execution_price:.2f}</code>\n"
        f"{price_trend_indicator_emoji} <b>vs PRU:</b> <code>{average_purchase_price_difference_percentage:+.2f}%</code> "
        f"(<code>${dca_strategy.average_purchase_price:.2f}</code>)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )


class AaveDcaNotificationService:

    async def handle_approval_callback(self, telegram_callback_query: TelegramCallbackQuery) -> None:
        if telegram_callback_query.message is None:
            logger.warning("[AAVEDCA][TELEGRAM] Malformed callback query received")
            return

        interaction_callback_data: str = telegram_callback_query.data
        if (
            not interaction_callback_data.startswith("approve_dca:")
            and not interaction_callback_data.startswith("reject_dca:")
        ):
            return

        origin_message_identifier: int = telegram_callback_query.message.message_id
        target_order_identifier: int = int(interaction_callback_data.split(":")[1])
        is_approval_action: bool = interaction_callback_data.startswith("approve_dca:")
        resolved_order_status: AaveDcaOrderStatus = (
            AaveDcaOrderStatus.APPROVED if is_approval_action else AaveDcaOrderStatus.REJECTED
        )
        resolved_status_label: str = "APPROUVÉ ✅" if is_approval_action else "REJETÉ ❌"

        with get_database_session() as database_session:
            order_dao = AaveDcaOrderDao(database_session)
            strategy_dao = AaveDcaStrategyDao(database_session)
            target_dca_order = order_dao.retrieve_by_id(target_order_identifier)

            if target_dca_order is None:
                logger.error(
                    "[AAVEDCA][TELEGRAM] DCA order identifier %s was not found",
                    target_order_identifier,
                )
                return

            current_order_status: AaveDcaOrderStatus = AaveDcaOrderStatus(target_dca_order.order_status)
            strategy_instance = strategy_dao.retrieve_by_id(target_dca_order.strategy_id)
            base_message_details: str = (
                build_approval_message_body(target_dca_order, strategy_instance)
                if strategy_instance is not None
                else f"📦 <b>Ordre #{target_order_identifier}</b>\n━━━━━━━━━━━━━━━━━━\n"
            )

            if current_order_status is not AaveDcaOrderStatus.WAITING_USER_APPROVAL:
                logger.info(
                    "[AAVEDCA][TELEGRAM] Ignoring stale callback for order identifier %s (current status: %s)",
                    target_order_identifier,
                    current_order_status.value,
                )
                edit_message_text(
                    message_id=origin_message_identifier,
                    text=f"{base_message_details}⚠️ <b>Statut:</b> déjà traité ({current_order_status.value})",
                )
                return

        logger.info(
            "[AAVEDCA][TELEGRAM] Processing %s for order identifier %s",
            resolved_order_status.value,
            target_order_identifier,
        )

        with get_database_session() as database_session:
            order_dao = AaveDcaOrderDao(database_session)
            strategy_dao = AaveDcaStrategyDao(database_session)
            target_dca_order = order_dao.retrieve_by_id(target_order_identifier)

            if target_dca_order is None:
                logger.error(
                    "[AAVEDCA][TELEGRAM] DCA order identifier %s was not found",
                    target_order_identifier,
                )
                return

            target_dca_order.order_status = resolved_order_status.value
            order_dao.save(target_dca_order)
            database_session.commit()

            strategy_instance = strategy_dao.retrieve_by_id(target_dca_order.strategy_id)

            if strategy_instance is not None:
                base_message_details = build_approval_message_body(target_dca_order, strategy_instance)
                full_confirmation_message = f"{base_message_details}✨ <b>Statut:</b> {resolved_status_label}"
                edit_message_text(
                    message_id=origin_message_identifier,
                    text=full_confirmation_message,
                )
            else:
                edit_message_text(
                    message_id=origin_message_identifier,
                    text=f"✅ Ordre #{target_order_identifier} {resolved_status_label} avec succès.",
                )

            cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
            logger.info(
                "[AAVEDCA][TELEGRAM] DCA order identifier %s updated to %s",
                target_order_identifier,
                resolved_order_status.value,
            )


def register_aave_dca_telegram_handlers() -> None:
    telegram_update_registry.register_callback_query_handler(
        aave_dca_notification_service.handle_approval_callback,
    )
    logger.info("[AAVEDCA][TELEGRAM] DCA Telegram handlers registered")


aave_dca_notification_service = AaveDcaNotificationService()
