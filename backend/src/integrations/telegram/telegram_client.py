from __future__ import annotations

import html
from typing import Final, Optional

import requests

from src.configuration.config import settings
from src.integrations.telegram.telegram_structures import (
    TelegramInlineKeyboardMarkup,
    TelegramMessagePayload,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_TELEGRAM_API_BASE_URL: Final[str] = "https://api.telegram.org"


def send_alert(
        title: str,
        body: str,
        emoji_indicator: Optional[str] = None,
        reply_markup: Optional[TelegramInlineKeyboardMarkup] = None
) -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram credentials missing from configuration, alert will not be sent")
        return

    resolved_emoji_indicator = emoji_indicator if emoji_indicator is not None else "🔔"
    header_text = f"{resolved_emoji_indicator} {title}".strip()

    formatted_message_text = f"<b>{html.escape(header_text)}</b>\n\n{body}"
    target_endpoint_url = f"{_TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    message_payload = TelegramMessagePayload(
        chat_id=settings.TELEGRAM_CHAT_ID,
        text=formatted_message_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )

    logger.debug("[TELEGRAM][CLIENT][PREPARATION] Preparing to send Telegram alert to configured chat identifier")

    try:
        http_response = requests.post(
            url=target_endpoint_url,
            json=message_payload.model_dump(exclude_none=True),
            timeout=10
        )
        http_response.raise_for_status()
        logger.info("[TELEGRAM][CLIENT][SUCCESS] Successfully delivered Telegram alert message with title: %s", title)
    except requests.RequestException as network_exception:
        logger.exception("[TELEGRAM][CLIENT][FAILURE] Failed to deliver Telegram alert message due to network exception: %s", network_exception)


def edit_message_text(
        message_id: int,
        text: str,
        reply_markup: Optional[TelegramInlineKeyboardMarkup] = None
) -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram credentials missing from configuration, message edit will not be performed")
        return

    target_endpoint_url = f"{_TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/editMessageText"

    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup.model_dump(exclude_none=True) if reply_markup else None
    }

    logger.debug("[TELEGRAM][CLIENT][PREPARATION] Preparing to edit Telegram message ID: %s", message_id)

    try:
        http_response = requests.post(
            url=target_endpoint_url,
            json={key: value for key, value in payload.items() if value is not None},
            timeout=10
        )
        http_response.raise_for_status()
        logger.info("[TELEGRAM][CLIENT][SUCCESS] Successfully edited Telegram message ID: %s", message_id)
    except requests.RequestException as network_exception:
        logger.exception("[TELEGRAM][CLIENT][FAILURE] Failed to edit Telegram message due to network exception: %s", network_exception)
