from __future__ import annotations

from unittest.mock import MagicMock, patch

import src.integrations.telegram.telegram_client as telegram_client
from src.integrations.telegram.telegram_client import get_updates, send_html_message


def _rate_limited_response() -> MagicMock:
    response = MagicMock()
    response.ok = False
    response.status_code = 429
    response.text = "Too Many Requests"
    response.json.return_value = {
        "ok": False,
        "description": "Too Many Requests: retry after 45",
        "parameters": {"retry_after": 45},
    }
    return response


@patch("src.integrations.telegram.telegram_client.requests.post")
@patch("src.integrations.telegram.telegram_client.settings")
def test_send_message_is_muted_until_retry_after_elapses_while_get_updates_continues(
        settings_mock: MagicMock,
        post_mock: MagicMock,
) -> None:
    settings_mock.TELEGRAM_BOT_TOKEN = "token"
    settings_mock.TELEGRAM_CHAT_ID = "chat"
    telegram_client._telegram_outbound_muted_until_monotonic = None
    post_mock.return_value = _rate_limited_response()

    assert send_html_message("first") is None
    assert send_html_message("second") is None
    assert get_updates(offset=0, allowed_updates=["message"], timeout_seconds=0) == []
    assert post_mock.call_count == 2

    telegram_client._telegram_outbound_muted_until_monotonic = None
