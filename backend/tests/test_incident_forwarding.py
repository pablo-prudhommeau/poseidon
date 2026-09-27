from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import src.logging.incident_forwarding_service as incident_forwarding_service
from src.logging.incident_forwarding_service import (
    forward_incident_to_telegram,
    forward_log_record_to_telegram,
)
from src.logging.incident_logging_handler import IncidentLoggingHandler


def _reset_incident_forwarding_state() -> None:
    incident_forwarding_service._last_incident_sent_at_by_fingerprint.clear()
    incident_forwarding_service._incident_window_started_at_monotonic = None
    incident_forwarding_service._incidents_sent_in_window = 0
    incident_forwarding_service._suppressed_incident_count = 0
    incident_forwarding_service._incident_forwarding_active = False


def _configure_incident_settings(
        settings_mock: MagicMock,
        max_per_window: int = 10,
        window_seconds: int = 600,
        cooldown_seconds: int = 120,
) -> None:
    settings_mock.LOGGING_INCIDENT_FORWARDING_ENABLED = True
    settings_mock.TELEGRAM_BOT_TOKEN = "token"
    settings_mock.TELEGRAM_CHAT_ID = "chat"
    settings_mock.LOGGING_INCIDENT_COOLDOWN_SECONDS = cooldown_seconds
    settings_mock.LOGGING_INCIDENT_MAX_BODY_CHARACTERS = 3500
    settings_mock.LOGGING_INCIDENT_MAX_PER_WINDOW = max_per_window
    settings_mock.LOGGING_INCIDENT_WINDOW_SECONDS = window_seconds
    settings_mock.LOGGING_INCIDENT_MINIMUM_LEVEL = "ERROR"


@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_forward_incident_to_telegram_sends_when_enabled(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
) -> None:
    _reset_incident_forwarding_state()
    _configure_incident_settings(settings_mock)

    forward_incident_to_telegram(title="Test title", body="Test body", emoji_indicator="🚨")

    send_alert_mock.assert_called_once()


@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_forward_incident_to_telegram_deduplicates_within_cooldown(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
) -> None:
    _reset_incident_forwarding_state()
    _configure_incident_settings(settings_mock)

    forward_incident_to_telegram(title="Duplicate", body="Same body", emoji_indicator="🚨")
    forward_incident_to_telegram(title="Duplicate", body="Same body", emoji_indicator="🚨")

    send_alert_mock.assert_called_once()


@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_incident_logging_handler_skips_telegram_logger(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
) -> None:
    _reset_incident_forwarding_state()
    _configure_incident_settings(settings_mock)

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
    _reset_incident_forwarding_state()
    _configure_incident_settings(settings_mock)

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


@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_forward_incident_to_telegram_deduplicates_bodies_that_differ_only_by_block_number(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
) -> None:
    _reset_incident_forwarding_state()
    _configure_incident_settings(settings_mock)

    forward_incident_to_telegram(
        title="[ERROR] poseidon.i.a.aave_protocol_reader",
        body="Historical reserve index batch lookup failed block=95821062 url=https://api.avax.network/ext/bc/C/rpc",
        emoji_indicator="🚨",
    )
    forward_incident_to_telegram(
        title="[ERROR] poseidon.i.a.aave_protocol_reader",
        body="Historical reserve index batch lookup failed block=95821111 url=https://api.avax.network/ext/bc/C/rpc",
        emoji_indicator="🚨",
    )

    send_alert_mock.assert_called_once()


@patch("src.logging.incident_forwarding_service.time.time")
@patch("src.logging.incident_forwarding_service.send_alert")
@patch("src.logging.incident_forwarding_service.settings")
def test_forward_incident_to_telegram_caps_the_window_and_announces_suppressed_incidents(
        settings_mock: MagicMock,
        send_alert_mock: MagicMock,
        time_mock: MagicMock,
) -> None:
    _reset_incident_forwarding_state()
    _configure_incident_settings(settings_mock, max_per_window=2, window_seconds=600)
    time_mock.return_value = 1_000.0

    forward_incident_to_telegram(title="Incident A", body="Body A", emoji_indicator="🚨")
    forward_incident_to_telegram(title="Incident B", body="Body B", emoji_indicator="🚨")
    forward_incident_to_telegram(title="Incident C", body="Body C", emoji_indicator="🚨")
    forward_incident_to_telegram(title="Incident D", body="Body D", emoji_indicator="🚨")

    assert send_alert_mock.call_count == 2

    time_mock.return_value = 1_700.0
    forward_incident_to_telegram(title="Incident E", body="Body E", emoji_indicator="🚨")

    assert send_alert_mock.call_count == 4
    summary_body = send_alert_mock.call_args_list[2].kwargs["body"]
    assert summary_body == "2 incidents were suppressed during the previous window."
