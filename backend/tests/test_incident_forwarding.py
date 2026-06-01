from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.logging.incident_forwarding_service import (
    forward_incident_to_telegram,
    forward_log_record_to_telegram,
)
from src.logging.incident_logging_handler import IncidentLoggingHandler


@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_forward_incident_to_telegram_sends_when_enabled(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
) -> None:
    settings_mock.LOGGING_INCIDENT_FORWARDING_ENABLED = True
    settings_mock.TELEGRAM_BOT_TOKEN = "token"
    settings_mock.TELEGRAM_CHAT_ID = "chat"
    settings_mock.LOGGING_INCIDENT_COOLDOWN_SECONDS = 120
    settings_mock.LOGGING_INCIDENT_MAX_BODY_CHARACTERS = 3500

    forward_incident_to_telegram(title="Test title", body="Test body", emoji_indicator="🚨")

    send_alert_mock.assert_called_once()


@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_forward_incident_to_telegram_deduplicates_within_cooldown(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
) -> None:
    settings_mock.LOGGING_INCIDENT_FORWARDING_ENABLED = True
    settings_mock.TELEGRAM_BOT_TOKEN = "token"
    settings_mock.TELEGRAM_CHAT_ID = "chat"
    settings_mock.LOGGING_INCIDENT_COOLDOWN_SECONDS = 120
    settings_mock.LOGGING_INCIDENT_MAX_BODY_CHARACTERS = 3500

    forward_incident_to_telegram(title="Duplicate", body="Same body", emoji_indicator="🚨")
    forward_incident_to_telegram(title="Duplicate", body="Same body", emoji_indicator="🚨")

    send_alert_mock.assert_called_once()


@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_incident_logging_handler_skips_telegram_logger(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
) -> None:
    settings_mock.LOGGING_INCIDENT_FORWARDING_ENABLED = True
    settings_mock.TELEGRAM_BOT_TOKEN = "token"
    settings_mock.TELEGRAM_CHAT_ID = "chat"
    settings_mock.LOGGING_INCIDENT_MINIMUM_LEVEL = "ERROR"
    settings_mock.LOGGING_INCIDENT_COOLDOWN_SECONDS = 120
    settings_mock.LOGGING_INCIDENT_MAX_BODY_CHARACTERS = 3500

    handler = IncidentLoggingHandler()
    log_record = logging.LogRecord(
        name="poseidon.integrations.telegram.telegram_client",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Telegram API failure",
        args=(),
        exc_info=None,
    )
    handler.emit(log_record)
    send_alert_mock.assert_not_called()


@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_forward_log_record_forwards_error_from_application_logger(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
) -> None:
    settings_mock.LOGGING_INCIDENT_FORWARDING_ENABLED = True
    settings_mock.TELEGRAM_BOT_TOKEN = "token"
    settings_mock.TELEGRAM_CHAT_ID = "chat"
    settings_mock.LOGGING_INCIDENT_MINIMUM_LEVEL = "ERROR"
    settings_mock.LOGGING_INCIDENT_COOLDOWN_SECONDS = 120
    settings_mock.LOGGING_INCIDENT_MAX_BODY_CHARACTERS = 3500

    log_record = logging.LogRecord(
        name="poseidon.core.trading.execution",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Execution failed",
        args=(),
        exc_info=None,
    )
    forward_log_record_to_telegram(log_record)

    send_alert_mock.assert_called_once()
