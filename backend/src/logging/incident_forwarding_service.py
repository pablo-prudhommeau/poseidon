from __future__ import annotations

import hashlib
import logging
import threading
import time
import traceback
from types import TracebackType
from typing import Optional

from src.configuration.config import settings
from src.integrations.telegram.telegram_client import send_alert

_incident_forwarding_lock = threading.Lock()
_last_incident_sent_at_by_fingerprint: dict[str, float] = {}
_incident_forwarding_active = False

_SUPPRESSED_LOGGER_NAME_PREFIXES: tuple[str, ...] = (
    "poseidon.integrations.telegram",
)


def forward_incident_to_telegram(
        title: str,
        body: str,
        emoji_indicator: str = "🚨",
) -> None:
    global _incident_forwarding_active

    if not settings.LOGGING_INCIDENT_FORWARDING_ENABLED:
        return
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    if _incident_forwarding_active:
        return

    normalized_title = title.strip()
    normalized_body = _truncate_incident_body(body.strip())
    if not normalized_title or not normalized_body:
        return

    incident_fingerprint = _build_incident_fingerprint(
        title=normalized_title,
        body=normalized_body,
    )
    current_timestamp = time.time()
    with _incident_forwarding_lock:
        last_sent_timestamp = _last_incident_sent_at_by_fingerprint.get(incident_fingerprint)
        if last_sent_timestamp is not None:
            elapsed_seconds = current_timestamp - last_sent_timestamp
            if elapsed_seconds < settings.LOGGING_INCIDENT_COOLDOWN_SECONDS:
                return
        _last_incident_sent_at_by_fingerprint[incident_fingerprint] = current_timestamp

    _incident_forwarding_active = True
    try:
        send_alert(
            title=normalized_title,
            body=normalized_body,
            emoji_indicator=emoji_indicator,
        )
    finally:
        _incident_forwarding_active = False


def forward_log_record_to_telegram(log_record: logging.LogRecord) -> None:
    if _should_suppress_log_record_for_incident_forwarding(log_record):
        return

    minimum_level_value = _resolve_incident_minimum_logging_level()

    if log_record.levelno < minimum_level_value:
        return

    title = f"[{log_record.levelname}] {log_record.name}"
    body = _format_log_record_body(log_record)
    emoji_indicator = "🛑" if log_record.levelno >= logging.CRITICAL else "🚨"
    forward_incident_to_telegram(title=title, body=body, emoji_indicator=emoji_indicator)


def forward_logging_handler_failure(
        log_record: logging.LogRecord,
        exception_type: type[BaseException],
        exception_value: BaseException,
        exception_traceback: Optional[TracebackType],
) -> None:
    traceback_text = "".join(traceback.format_exception(exception_type, exception_value, exception_traceback))
    body = (
        f"Logger: {log_record.name}\n"
        f"Message: {log_record.getMessage()}\n\n"
        f"{traceback_text}"
    )
    forward_incident_to_telegram(
        title="[LOGGING] Handler failure",
        body=body,
        emoji_indicator="🛑",
    )


def forward_unhandled_exception_to_telegram(
        exception_type: type[BaseException],
        exception_value: BaseException,
        exception_traceback: Optional[TracebackType],
        origin_label: str,
) -> None:
    traceback_text = "".join(traceback.format_exception(exception_type, exception_value, exception_traceback))
    body = f"Origin: {origin_label}\n\n{traceback_text}"
    forward_incident_to_telegram(
        title=f"[UNHANDLED] {exception_type.__name__}",
        body=body,
        emoji_indicator="🛑",
    )


def forward_asyncio_exception_context_to_telegram(context: dict[str, object]) -> None:
    context_message = context.get("message")
    context_exception = context.get("exception")
    context_task = context.get("task")
    context_future = context.get("future")

    body_lines: list[str] = []
    if isinstance(context_message, str) and context_message.strip():
        body_lines.append(context_message.strip())

    if context_task is not None:
        body_lines.append(f"Task: {context_task!r}")

    if context_future is not None:
        body_lines.append(f"Future: {context_future!r}")

    if isinstance(context_exception, BaseException):
        body_lines.append(
            "".join(
                traceback.format_exception(
                    type(context_exception),
                    context_exception,
                    context_exception.__traceback__,
                ),
            ),
        )

    if not body_lines:
        body_lines.append(repr(context))

    forward_incident_to_telegram(
        title="[ASYNCIO] Unhandled event-loop exception",
        body="\n".join(body_lines),
        emoji_indicator="🛑",
    )


def _resolve_incident_minimum_logging_level() -> int:
    level_mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    configured_level_name = settings.LOGGING_INCIDENT_MINIMUM_LEVEL.upper()
    resolved_level = level_mapping.get(configured_level_name)
    if resolved_level is None:
        return logging.ERROR
    return resolved_level


def _should_suppress_log_record_for_incident_forwarding(log_record: logging.LogRecord) -> bool:
    logger_name = log_record.name if log_record.name is not None else ""
    for suppressed_prefix in _SUPPRESSED_LOGGER_NAME_PREFIXES:
        if logger_name.startswith(suppressed_prefix):
            return True
    return False


def _format_log_record_body(log_record: logging.LogRecord) -> str:
    message_text = log_record.getMessage()
    if log_record.exc_info:
        exception_text = "".join(traceback.format_exception(*log_record.exc_info))
        return f"{message_text}\n\n{exception_text}"
    return message_text


def _build_incident_fingerprint(title: str, body: str) -> str:
    fingerprint_source = f"{title}\n{body[:500]}"
    return hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:24]


def _truncate_incident_body(body: str) -> str:
    maximum_characters = settings.LOGGING_INCIDENT_MAX_BODY_CHARACTERS
    if len(body) <= maximum_characters:
        return body
    truncated_suffix = "\n\n[truncated]"
    keep_characters = maximum_characters - len(truncated_suffix)
    return body[:keep_characters] + truncated_suffix
