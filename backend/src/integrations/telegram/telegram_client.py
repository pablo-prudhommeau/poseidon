from __future__ import annotations

from typing import Final

import requests

from src.configuration.config import settings
from src.logging.logger import get_logger

logger = get_logger(__name__)

_TELEGRAM_API_BASE: Final[str] = "https://api.telegram.org"


def _escape_markdown_v2(text: str) -> str:
    specials = r"_*[]()~`>#+-=|{}.!"
    for char in specials:
        text = text.replace(char, f"\\{char}")
    return text


def send_alert(title: str, body: str, emoji: str = "🔔") -> None:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return

    header = f"{emoji} {title}".strip()

    safe_header = _escape_markdown_v2(header)
    safe_body = _escape_markdown_v2(body)

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
