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
        reply_markup: Optional[TelegramInlineKeyboardMarkup] = None,
        title_body_separator: str = "\n\n",
) -> Optional[int]:
    if not _has_telegram_credentials():
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram credentials missing from configuration, alert will not be sent")
        return None

    resolved_emoji_indicator: str = emoji_indicator if emoji_indicator is not None else "🔔"
    header_text: str = f"{resolved_emoji_indicator} {title}".strip()

    formatted_message_text: str = f"<b>{html.escape(header_text)}</b>{title_body_separator}{body}"
    return send_html_message(
        text=formatted_message_text,
        reply_markup=reply_markup,
    )


def send_html_message(
        text: str,
        reply_markup: Optional[TelegramInlineKeyboardMarkup] = None,
) -> Optional[int]:
    if not _has_telegram_credentials():
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram credentials missing from configuration, html message will not be sent")
        return None

    message_payload = TelegramMessagePayload(
        chat_id=settings.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )

    logger.debug("[TELEGRAM][CLIENT][PREPARATION] Preparing to send Telegram html message to configured chat identifier")

    response_payload = _call_telegram_method(
        method_name="sendMessage",
        payload=message_payload.model_dump(exclude_none=True),
    )
    if response_payload is None:
        return None

    message_identifier: Optional[int] = _extract_message_identifier_from_response(response_payload)
    logger.debug(
        "[TELEGRAM][CLIENT][SUCCESS] Successfully delivered Telegram html message message_id=%s",
        message_identifier,
    )
    return message_identifier


def edit_message_text(
        message_id: int,
        text: str,
        reply_markup: Optional[TelegramInlineKeyboardMarkup] = None,
) -> bool:
    if not _has_telegram_credentials():
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram credentials missing from configuration, message edit will not be performed")
        return False

    payload: dict[str, object] = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup.model_dump(exclude_none=True) if reply_markup else None,
    }

    logger.debug("[TELEGRAM][CLIENT][PREPARATION] Preparing to edit Telegram message ID: %s", message_id)

    response_payload = _call_telegram_method(
        method_name="editMessageText",
        payload=payload,
    )
    if response_payload is None:
        return False

    logger.debug("[TELEGRAM][CLIENT][SUCCESS] Successfully edited Telegram message ID: %s", message_id)
    return True


def delete_message(message_id: int) -> bool:
    if not _has_telegram_credentials():
        logger.debug("[TELEGRAM][CLIENT][SKIPPED] Telegram credentials missing from configuration, message delete will not be performed")
        return False

    payload: dict[str, object] = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "message_id": message_id,
    }

    logger.debug("[TELEGRAM][CLIENT][PREPARATION] Preparing to delete Telegram message ID: %s", message_id)

    response_payload = _call_telegram_method(
        method_name="deleteMessage",
        payload=payload,
    )
    if response_payload is None:
        return False

    logger.debug("[TELEGRAM][CLIENT][SUCCESS] Successfully deleted Telegram message ID: %s", message_id)
    return True


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

    logger.debug("[TELEGRAM][CLIENT][SUCCESS] Successfully registered Telegram bot commands")
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


def _extract_message_identifier_from_response(response_payload: dict[str, object]) -> Optional[int]:
    result_payload = response_payload.get("result")
    if not isinstance(result_payload, dict):
        return None
    message_identifier = result_payload.get("message_id")
    if isinstance(message_identifier, int):
        return message_identifier
    return None


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
        if not http_response.ok:
            response_description: str = _extract_telegram_error_description(http_response)
            logger.warning(
                "[TELEGRAM][CLIENT][FAILURE] Telegram method %s failed with status %s description=%s",
                method_name,
                http_response.status_code,
                response_description,
            )
            return None

        response_payload = http_response.json()
        if not response_payload.get("ok", False):
            response_description = str(response_payload.get("description", "unknown"))
            logger.warning(
                "[TELEGRAM][CLIENT][FAILURE] Telegram method %s returned a rejected payload description=%s",
                method_name,
                response_description,
            )
            return None

        return response_payload
    except requests.RequestException as network_exception:
        logger.warning(
            "[TELEGRAM][CLIENT][FAILURE] Telegram method %s network failure: %s",
            method_name,
            network_exception,
        )
        return None


def _extract_telegram_error_description(http_response: requests.Response) -> str:
    try:
        response_payload = http_response.json()
        if isinstance(response_payload, dict):
            description = response_payload.get("description")
            if isinstance(description, str):
                return description
    except ValueError:
        return http_response.text[:500]
    return http_response.text[:500]
