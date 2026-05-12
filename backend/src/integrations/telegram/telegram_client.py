from __future__ import annotations

import html
from typing import Final, Optional

import requests

from src.configuration.config import settings
from src.integrations.telegram.telegram_structures import (
    TelegramInlineKeyboardMarkup,
    TelegramMessagePayload,
    TelegramUpdate,
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
    if not _has_telegram_credentials():
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram credentials missing from configuration, alert will not be sent")
        return

    resolved_emoji_indicator = emoji_indicator if emoji_indicator is not None else "🔔"
    header_text = f"{resolved_emoji_indicator} {title}".strip()

    formatted_message_text = f"<b>{html.escape(header_text)}</b>\n\n{body}"

    message_payload = TelegramMessagePayload(
        chat_id=settings.TELEGRAM_CHAT_ID,
        text=formatted_message_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )

    logger.debug("[TELEGRAM][CLIENT][PREPARATION] Preparing to send Telegram alert to configured chat identifier")

    response_payload = _call_telegram_method(
        method_name="sendMessage",
        payload=message_payload.model_dump(exclude_none=True),
    )
    if response_payload is not None:
        logger.info("[TELEGRAM][CLIENT][SUCCESS] Successfully delivered Telegram alert message with title: %s", title)


def edit_message_text(
        message_id: int,
        text: str,
        reply_markup: Optional[TelegramInlineKeyboardMarkup] = None
) -> None:
    if not _has_telegram_credentials():
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram credentials missing from configuration, message edit will not be performed")
        return

    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup.model_dump(exclude_none=True) if reply_markup else None
    }

    logger.debug("[TELEGRAM][CLIENT][PREPARATION] Preparing to edit Telegram message ID: %s", message_id)

    response_payload = _call_telegram_method(
        method_name="editMessageText",
        payload=payload,
    )
    if response_payload is not None:
        logger.info("[TELEGRAM][CLIENT][SUCCESS] Successfully edited Telegram message ID: %s", message_id)


def register_bot_commands(commands: list[dict[str, str]]) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram bot token missing, bot commands will not be registered")
        return False

    logger.debug("[TELEGRAM][CLIENT][PREPARATION] Preparing to register %d Telegram bot commands", len(commands))
    response_payload = _call_telegram_method(
        method_name="setMyCommands",
        payload={"commands": commands},
    )
    if response_payload is None:
        return False

    logger.info("[TELEGRAM][CLIENT][SUCCESS] Successfully registered Telegram bot commands")
    return True


def get_updates(
        offset: int,
        allowed_updates: list[str],
        timeout_seconds: int = 0,
) -> list[TelegramUpdate]:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram bot token missing, updates will not be polled")
        return []

    response_payload = _call_telegram_method(
        method_name="getUpdates",
        payload={
            "offset": offset,
            "allowed_updates": allowed_updates,
            "timeout": timeout_seconds,
        },
    )
    if response_payload is None:
        return []

    raw_updates = response_payload.get("result")
    if not isinstance(raw_updates, list):
        logger.warning("[TELEGRAM][CLIENT][FAILURE] Telegram getUpdates returned an invalid result payload")
        return []

    parsed_updates: list[TelegramUpdate] = []
    for raw_update in raw_updates:
        if not isinstance(raw_update, dict):
            continue
        try:
            parsed_updates.append(TelegramUpdate.model_validate(raw_update))
        except Exception as validation_exception:
            logger.exception("[TELEGRAM][CLIENT][FAILURE] Failed to validate Telegram update payload: %s", validation_exception)

    return parsed_updates


def _has_telegram_credentials() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def _call_telegram_method(method_name: str, payload: dict[str, object]) -> Optional[dict[str, object]]:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram bot token missing, method %s will not be called", method_name)
        return None

    target_endpoint_url = f"{_TELEGRAM_API_BASE_URL}/bot{settings.TELEGRAM_BOT_TOKEN}/{method_name}"

    try:
        http_response = requests.post(
            url=target_endpoint_url,
            json={key: value for key, value in payload.items() if value is not None},
            timeout=10,
        )
        http_response.raise_for_status()
        response_payload = http_response.json()
        if not response_payload.get("ok", False):
            logger.warning("[TELEGRAM][CLIENT][FAILURE] Telegram method %s returned a rejected payload: %s", method_name, response_payload)
            return None

        return response_payload
    except requests.RequestException as network_exception:
        logger.exception("[TELEGRAM][CLIENT][FAILURE] Telegram method %s failed: %s", method_name, network_exception)
        return None
