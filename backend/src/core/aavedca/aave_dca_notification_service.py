from __future__ import annotations

import html
import time
from typing import Optional

from sqlalchemy.orm import Session

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavedca.aave_dca_helpers import (
    deserialize_pipeline_operations,
    format_allocation_decision_label,
    resolve_pipeline_step_descriptor,
)
from src.core.aavedca.aave_dca_structures import AaveDcaAllocationDecision, AaveDcaOrderStatus
from src.core.trading.trading_utils import get_currency_symbol
from src.integrations.telegram.telegram_client import delete_message, edit_message_text, send_alert
from src.integrations.telegram.telegram_format_utils import (
    TELEGRAM_MAIN_TITLE_BODY_SEPARATOR,
    build_telegram_section_block,
    build_telegram_section_header,
)
from src.integrations.telegram.telegram_structures import (
    TelegramCallbackQuery,
    TelegramInlineKeyboardButton,
    TelegramInlineKeyboardMarkup,
)
from src.integrations.telegram.telegram_update_registry import telegram_update_registry
from src.logging.logger import get_application_logger
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)

_TELEGRAM_RESYNC_PUBLISH_INTERVAL_SECONDS: float = 0.5


def build_dca_order_telegram_body(
    dca_order: AaveDcaOrder,
    dca_strategy: AaveDcaStrategy,
    status_note: Optional[str] = None,
) -> str:
    average_purchase_price_difference_percentage: float = 0.0
    if dca_strategy.average_purchase_price > 0 and dca_order.actual_execution_price is not None:
        average_purchase_price_difference_percentage = (
            dca_order.actual_execution_price / dca_strategy.average_purchase_price - 1
        ) * 100

    price_trend_indicator_emoji: str = "📈" if average_purchase_price_difference_percentage > 0 else "📉"
    order_status: AaveDcaOrderStatus = AaveDcaOrderStatus(dca_order.order_status)
    pipeline_step_descriptor = resolve_pipeline_step_descriptor(order_status)
    source_asset_currency_symbol: str = get_currency_symbol(dca_strategy.source_asset_symbol)

    order_header_title: str = f"📦 Ordre #{dca_order.id}"
    body_sections: list[str] = [build_telegram_section_header(order_header_title)]

    identity_section_lines: list[str] = [
        f"🔹 <b>Actif:</b> <code>{html.escape(dca_strategy.target_asset_symbol)}</code>",
        f"📌 <b>Statut:</b> <code>{html.escape(order_status.value)}</code>",
    ]
    body_sections.append(build_telegram_section_block("Identité", identity_section_lines))

    amounts_section_lines: list[str] = [
        f"💵 <b>Montant prévisionnel:</b> <code>${dca_order.planned_source_asset_amount:.2f}</code>",
    ]
    if order_status == AaveDcaOrderStatus.SKIPPED:
        amounts_section_lines.append(
            "💸 <b>Montant réellement exécuté:</b> <code>—</code>"
        )
    elif dca_order.executed_source_asset_amount is not None:
        amounts_section_lines.append(
            f"💸 <b>Montant réellement exécuté:</b> "
            f"<code>${dca_order.executed_source_asset_amount:.2f}</code>"
        )
    if dca_order.actual_execution_price is not None:
        amounts_section_lines.append(
            f"💰 <b>Prix actuel:</b> <code>${dca_order.actual_execution_price:.2f}</code>"
        )
        amounts_section_lines.append(
            f"{price_trend_indicator_emoji} <b>vs PRU:</b> "
            f"<code>{average_purchase_price_difference_percentage:+.2f}%</code> "
            f"(<code>${dca_strategy.average_purchase_price:.2f}</code>)"
        )
    body_sections.append(build_telegram_section_block("Montants", amounts_section_lines))

    allocation_section_lines: list[str] = []
    if dca_order.reference_market_price is not None and dca_order.actual_execution_price is None:
        allocation_section_lines.append(
            f"📈 <b>Prix marché:</b> <code>${dca_order.reference_market_price:.2f}</code>"
        )
    if dca_order.allocation_decision is not None:
        allocation_decision = AaveDcaAllocationDecision(dca_order.allocation_decision)
        allocation_label = format_allocation_decision_label(
            allocation_decision=allocation_decision,
            allocation_multiplier=dca_order.allocation_multiplier,
        )
        allocation_section_lines.append(
            f"📊 <b>Décision:</b> <code>{html.escape(allocation_label)}</code>"
        )
    if dca_order.dry_powder_delta is not None and dca_order.dry_powder_delta != 0:
        dry_powder_sign_prefix: str = "+" if dca_order.dry_powder_delta >= 0 else "-"
        dry_powder_absolute_amount: float = abs(dca_order.dry_powder_delta)
        allocation_section_lines.append(
            f"📦 <b>Dry powder:</b> "
            f"<code>{dry_powder_sign_prefix}{source_asset_currency_symbol}{dry_powder_absolute_amount:.2f}</code>"
        )
    body_sections.append(build_telegram_section_block("Allocation", allocation_section_lines))

    pipeline_section_lines: list[str] = []
    if pipeline_step_descriptor is not None:
        pipeline_step_number, pipeline_step_label = pipeline_step_descriptor
        pipeline_section_lines.append(
            f"🔄 <b>Phase:</b> <code>Step {pipeline_step_number}/3 — {html.escape(pipeline_step_label)}</code>"
        )
    if dca_order.pipeline_attempt_count > 0:
        pipeline_section_lines.append(
            f"🔁 <b>Retry:</b> <code>{dca_order.pipeline_attempt_count}/{settings.AAVE_DCA_PIPELINE_MAX_RETRY_ATTEMPTS}</code>"
        )
        if dca_order.next_attempt_at is not None:
            pipeline_section_lines.append(
                f"⏱️ <b>Prochain essai:</b> <code>{html.escape(dca_order.next_attempt_at.strftime('%Y-%m-%d %H:%M:%S'))}</code>"
            )
    if dca_order.suspension_reason is not None:
        pipeline_section_lines.append(
            f"🛑 <b>Raison:</b> <code>{html.escape(dca_order.suspension_reason)}</code>"
        )

    pipeline_operations_container = deserialize_pipeline_operations(dca_order.pipeline_operations)
    for pipeline_operation in pipeline_operations_container.pipeline_operations:
        if pipeline_operation.transaction_hash is not None:
            pipeline_section_lines.append(
                f"🔗 <b>{html.escape(pipeline_operation.step.value)}:</b> "
                f"<code>{html.escape(pipeline_operation.transaction_hash)}</code>"
            )
    body_sections.append(build_telegram_section_block("Pipeline", pipeline_section_lines))

    if status_note is not None:
        decision_section_lines: list[str] = [status_note]
        body_sections.append(build_telegram_section_block("Décision", decision_section_lines))

    return "\n".join(section for section in body_sections if section)


def resolve_dca_order_telegram_title_and_emoji(dca_order: AaveDcaOrder) -> tuple[str, str]:
    order_status: AaveDcaOrderStatus = AaveDcaOrderStatus(dca_order.order_status)
    if dca_order.suspension_reason is not None:
        return "PIPELINE SUSPENDU", "⏸️"
    if order_status == AaveDcaOrderStatus.WAITING_USER_APPROVAL:
        return "DEMANDE D'APPROBATION", "🛡️"
    if order_status == AaveDcaOrderStatus.SKIPPED:
        return "ORDRE IGNORÉ", "⏭️"
    if order_status == AaveDcaOrderStatus.EXECUTED:
        return "ORDRE EXÉCUTÉ", "✅"
    if order_status == AaveDcaOrderStatus.REJECTED:
        return "ORDRE REJETÉ", "❌"
    if order_status == AaveDcaOrderStatus.FAILED:
        return "ORDRE ÉCHOUÉ", "❌"
    return "ORDRE DCA", "🔄"


def resolve_dca_order_telegram_reply_markup(dca_order: AaveDcaOrder) -> Optional[TelegramInlineKeyboardMarkup]:
    order_status: AaveDcaOrderStatus = AaveDcaOrderStatus(dca_order.order_status)
    if dca_order.suspension_reason is not None:
        return TelegramInlineKeyboardMarkup(
            inline_keyboard=[
                [
                    TelegramInlineKeyboardButton(
                        text="▶️ Reprendre",
                        callback_data=f"resume_dca:{dca_order.id}",
                    )
                ]
            ]
        )
    if order_status == AaveDcaOrderStatus.WAITING_USER_APPROVAL:
        return TelegramInlineKeyboardMarkup(
            inline_keyboard=[
                [
                    TelegramInlineKeyboardButton(text="✅ Approuver", callback_data=f"approve_dca:{dca_order.id}"),
                    TelegramInlineKeyboardButton(text="❌ Rejeter", callback_data=f"reject_dca:{dca_order.id}"),
                ]
            ]
        )
    return None


def format_dca_order_telegram_message_text(
    dca_order: AaveDcaOrder,
    dca_strategy: AaveDcaStrategy,
    status_note: Optional[str] = None,
) -> str:
    title, emoji_indicator = resolve_dca_order_telegram_title_and_emoji(dca_order)
    header_text: str = f"{emoji_indicator} {title}".strip()
    body_text: str = build_dca_order_telegram_body(
        dca_order=dca_order,
        dca_strategy=dca_strategy,
        status_note=status_note,
    )
    return f"<b>{html.escape(header_text)}</b>{TELEGRAM_MAIN_TITLE_BODY_SEPARATOR}{body_text}"


def publish_dca_order_telegram_message(
    dca_order: AaveDcaOrder,
    dca_strategy: AaveDcaStrategy,
    order_dao: AaveDcaOrderDao,
    status_note: Optional[str] = None,
) -> None:
    title, emoji_indicator = resolve_dca_order_telegram_title_and_emoji(dca_order)
    message_text: str = format_dca_order_telegram_message_text(
        dca_order=dca_order,
        dca_strategy=dca_strategy,
        status_note=status_note,
    )
    reply_markup: Optional[TelegramInlineKeyboardMarkup] = resolve_dca_order_telegram_reply_markup(dca_order)

    if order_status_requires_approval_footer(dca_order):
        message_text = f"{message_text}\n\n<i>Souhaitez-vous autoriser cette exécution ?</i>"

    if dca_order.telegram_message_id is not None:
        edit_message_text(
            message_id=dca_order.telegram_message_id,
            text=message_text,
            reply_markup=reply_markup,
        )
        return

    body_text: str = build_dca_order_telegram_body(
        dca_order=dca_order,
        dca_strategy=dca_strategy,
        status_note=status_note,
    )
    if order_status_requires_approval_footer(dca_order):
        body_text = f"{body_text}\n\n<i>Souhaitez-vous autoriser cette exécution ?</i>"

    message_identifier: Optional[int] = send_alert(
        title=title,
        body=body_text,
        emoji_indicator=emoji_indicator,
        reply_markup=reply_markup,
        title_body_separator=TELEGRAM_MAIN_TITLE_BODY_SEPARATOR,
    )
    if message_identifier is not None:
        dca_order.telegram_message_id = message_identifier
        order_dao.save(dca_order)
        logger.info(
            "[AAVEDCA][TELEGRAM] Published new order message for order_id=%s message_id=%s",
            dca_order.id,
            message_identifier,
        )


def delete_dca_order_telegram_message(dca_order: AaveDcaOrder, order_dao: AaveDcaOrderDao) -> None:
    if dca_order.telegram_message_id is None:
        return
    delete_message(dca_order.telegram_message_id)
    dca_order.telegram_message_id = None
    order_dao.save(dca_order)


def order_status_requires_approval_footer(dca_order: AaveDcaOrder) -> bool:
    return (
        AaveDcaOrderStatus(dca_order.order_status) == AaveDcaOrderStatus.WAITING_USER_APPROVAL
        and dca_order.suspension_reason is None
    )


def resync_active_dca_order_telegram_messages(database_session: Session) -> None:
    order_dao = AaveDcaOrderDao(database_session)
    strategy_dao = AaveDcaStrategyDao(database_session)
    active_orders = order_dao.retrieve_active_telegram_orders()

    logger.info("[AAVEDCA][TELEGRAM][RESYNC] Refreshing %d active order telegram messages", len(active_orders))

    for active_order in active_orders:
        if active_order.telegram_message_id is not None:
            deleted_successfully = delete_message(active_order.telegram_message_id)
            if not deleted_successfully:
                logger.debug(
                    "[AAVEDCA][TELEGRAM][RESYNC] Could not delete stale message_id=%s for order_id=%s",
                    active_order.telegram_message_id,
                    active_order.id,
                )
            active_order.telegram_message_id = None
            order_dao.save(active_order)

    database_session.commit()

    for active_order_index, active_order in enumerate(active_orders):
        strategy = strategy_dao.retrieve_by_id(active_order.strategy_id)
        if strategy is None:
            continue
        publish_dca_order_telegram_message(
            dca_order=active_order,
            dca_strategy=strategy,
            order_dao=order_dao,
        )
        if active_order_index < len(active_orders) - 1:
            time.sleep(_TELEGRAM_RESYNC_PUBLISH_INTERVAL_SECONDS)

    database_session.commit()


class AaveDcaNotificationService:

    async def handle_dca_callback(self, telegram_callback_query: TelegramCallbackQuery) -> None:
        if telegram_callback_query.message is None:
            logger.warning("[AAVEDCA][TELEGRAM] Malformed callback query received")
            return

        interaction_callback_data: str = telegram_callback_query.data
        if interaction_callback_data.startswith("approve_dca:") or interaction_callback_data.startswith("reject_dca:"):
            await self._handle_approval_callback(telegram_callback_query, interaction_callback_data)
            return

        if interaction_callback_data.startswith("resume_dca:"):
            await self._handle_resume_callback(telegram_callback_query, interaction_callback_data)

    async def _handle_approval_callback(
        self,
        telegram_callback_query: TelegramCallbackQuery,
        interaction_callback_data: str,
    ) -> None:
        origin_message_identifier: int = telegram_callback_query.message.message_id
        target_order_identifier: int = int(interaction_callback_data.split(":")[1])
        is_approval_action: bool = interaction_callback_data.startswith("approve_dca:")
        resolved_order_status: AaveDcaOrderStatus = (
            AaveDcaOrderStatus.AWAITING_WITHDRAW if is_approval_action else AaveDcaOrderStatus.REJECTED
        )
        resolved_status_label: str = "APPROUVÉ ✅" if is_approval_action else "REJETÉ ❌"

        with get_database_session() as database_session:
            order_dao = AaveDcaOrderDao(database_session)
            strategy_dao = AaveDcaStrategyDao(database_session)
            target_dca_order = order_dao.retrieve_by_id(target_order_identifier)

            if target_dca_order is None:
                logger.info(
                    "[AAVEDCA][TELEGRAM] Ignoring callback for missing order identifier %s",
                    target_order_identifier,
                )
                edit_message_text(
                    message_id=origin_message_identifier,
                    text="<b>⚠️ Ordre expiré / recréé</b>\n\nCe bouton ne correspond plus à un ordre actif.",
                )
                return

            current_order_status: AaveDcaOrderStatus = AaveDcaOrderStatus(target_dca_order.order_status)
            strategy_instance = strategy_dao.retrieve_by_id(target_dca_order.strategy_id)

            if current_order_status is not AaveDcaOrderStatus.WAITING_USER_APPROVAL:
                logger.info(
                    "[AAVEDCA][TELEGRAM] Ignoring stale callback for order identifier %s (current status: %s)",
                    target_order_identifier,
                    current_order_status.value,
                )
                if strategy_instance is not None:
                    edit_message_text(
                        message_id=origin_message_identifier,
                        text=format_dca_order_telegram_message_text(
                            dca_order=target_dca_order,
                            dca_strategy=strategy_instance,
                            status_note=f"⚠️ <b>Statut:</b> déjà traité ({html.escape(current_order_status.value)})",
                        ),
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
                logger.info(
                    "[AAVEDCA][TELEGRAM] Ignoring callback for missing order identifier %s after re-fetch",
                    target_order_identifier,
                )
                return

            target_dca_order.order_status = resolved_order_status.value
            if target_dca_order.telegram_message_id is None:
                target_dca_order.telegram_message_id = origin_message_identifier
            order_dao.save(target_dca_order)
            database_session.commit()

            strategy_instance = strategy_dao.retrieve_by_id(target_dca_order.strategy_id)
            if strategy_instance is not None:
                publish_dca_order_telegram_message(
                    dca_order=target_dca_order,
                    dca_strategy=strategy_instance,
                    order_dao=order_dao,
                    status_note=f"✨ <b>Statut:</b> {resolved_status_label}",
                )
                database_session.commit()

            cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
            logger.info(
                "[AAVEDCA][TELEGRAM] DCA order identifier %s updated to %s",
                target_order_identifier,
                resolved_order_status.value,
            )

    async def _handle_resume_callback(
        self,
        telegram_callback_query: TelegramCallbackQuery,
        interaction_callback_data: str,
    ) -> None:
        origin_message_identifier: int = telegram_callback_query.message.message_id
        target_order_identifier: int = int(interaction_callback_data.split(":")[1])

        with get_database_session() as database_session:
            order_dao = AaveDcaOrderDao(database_session)
            strategy_dao = AaveDcaStrategyDao(database_session)
            target_dca_order = order_dao.retrieve_by_id(target_order_identifier)

            if target_dca_order is None:
                logger.info(
                    "[AAVEDCA][TELEGRAM] Ignoring resume callback for missing order identifier %s",
                    target_order_identifier,
                )
                edit_message_text(
                    message_id=origin_message_identifier,
                    text="<b>⚠️ Ordre expiré / recréé</b>\n\nCe bouton ne correspond plus à un ordre actif.",
                )
                return

            strategy_instance = strategy_dao.retrieve_by_id(target_dca_order.strategy_id)
            if strategy_instance is None:
                logger.info(
                    "[AAVEDCA][TELEGRAM] Strategy not found for resume of order identifier %s",
                    target_order_identifier,
                )
                return

            if target_dca_order.suspension_reason is None:
                logger.info(
                    "[AAVEDCA][TELEGRAM] Ignoring stale resume callback for order identifier %s (not suspended)",
                    target_order_identifier,
                )
                publish_dca_order_telegram_message(
                    dca_order=target_dca_order,
                    dca_strategy=strategy_instance,
                    order_dao=order_dao,
                    status_note="⚠️ <b>Statut:</b> déjà repris",
                )
                database_session.commit()
                return

            target_dca_order.suspension_reason = None
            target_dca_order.pipeline_attempt_count = 0
            target_dca_order.next_attempt_at = None
            if target_dca_order.telegram_message_id is None:
                target_dca_order.telegram_message_id = origin_message_identifier
            order_dao.save(target_dca_order)
            database_session.commit()

            publish_dca_order_telegram_message(
                dca_order=target_dca_order,
                dca_strategy=strategy_instance,
                order_dao=order_dao,
                status_note="✨ <b>Statut:</b> reprise programmée",
            )
            database_session.commit()
            cache_invalidator.mark_dirty(CacheRealm.AAVE_DCA_STRATEGIES)
            logger.info(
                "[AAVEDCA][TELEGRAM] DCA order identifier %s resumed at status %s",
                target_order_identifier,
                target_dca_order.order_status,
            )


def register_aave_dca_telegram_handlers() -> None:
    telegram_update_registry.register_callback_query_handler(
        aave_dca_notification_service.handle_dca_callback,
    )
    logger.info("[AAVEDCA][TELEGRAM] DCA Telegram handlers registered")


aave_dca_notification_service = AaveDcaNotificationService()
