from __future__ import annotations

from typing import Final

import requests

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)

_TELEGRAM_API_BASE: Final[str] = "https://api.telegram.org"


def _escape_markdown_v2(text: str) -> str:
    """Escape MarkdownV2 special characters for Telegram."""
    # See: https://core.telegram.org/bots/api#markdownv2-style
    specials = r"_*[]()~`>#+-=|{}.!"
    for ch in specials:
        text = text.replace(ch, f"\\{ch}")
    return text


def send_alert(title: str, body: str, emoji: str = "🔔") -> None:
    """Send a MarkdownV2 Telegram alert to the configured chat.

    Notes:
        - No-op if TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is unset.
        - Does not raise on failure; logs an error instead (non-breaking behavior).

    Args:
        title: Alert title (plain text; will be escaped).
        body: Alert body (plain text; will be escaped).
        emoji: Optional emoji to prefix the title with.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return

    header = f"{emoji} {title}".strip()
    text = f"*{_escape_markdown_v2(header)}*\n{_escape_markdown_v2(body)}"

    url = f"{_TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)
