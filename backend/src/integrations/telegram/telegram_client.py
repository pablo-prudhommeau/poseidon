from __future__ import annotations

from typing import Final, Optional

import requests

from src.configuration.config import settings
from src.logging.logger import get_logger

logger = get_logger(__name__)

_TELEGRAM_API_BASE: Final[str] = "https://api.telegram.org"


def _escape_markdown_v2(text: str) -> str:
    """
    Escape MarkdownV2 special characters for Telegram.
    See: https://core.telegram.org/bots/api#markdownv2-style
    """
    specials = r"_*[]()~`>#+-=|{}.!"
    for char in specials:
        text = text.replace(char, f"\\{char}")
    return text


def send_alert(title: str, body: str, emoji: str = "🔔") -> None:
    """
    Send a formatted Telegram alert using MarkdownV2.

    This function handles the visual formatting to ensure messages are
    readable and aesthetically pleasing, avoiding the 'raw' look.

    Args:
        title: The header of the message.
        body: The main content.
        emoji: Icon prefix.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        # Silent return if not configured, to avoid spamming logs in dev environments without secrets
        return

    # Clean styling: Bold title, clean body
    header = f"{emoji} {title}".strip()

    # We escape inputs to prevent Markdown injection breaking the parsing
    safe_header = _escape_markdown_v2(header)
    safe_body = _escape_markdown_v2(body)

    # Construction: Header in bold, Body standard
    text = f"*{safe_header}*\n\n{safe_body}"

    url = f"{_TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.RequestException as error:
        logger.error(f"[TELEGRAM] Send failed: {error}")