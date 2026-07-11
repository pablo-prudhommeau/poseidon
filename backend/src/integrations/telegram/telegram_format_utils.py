from __future__ import annotations

import html
from typing import Final

TELEGRAM_MAIN_TITLE_BODY_SEPARATOR: Final[str] = "\n\n\n"


def build_telegram_section_header(plain_text_title: str) -> str:
    escaped_title: str = html.escape(plain_text_title)
    underline: str = "─" * len(plain_text_title)
    return f"<b>{escaped_title}</b>\n{underline}"


def build_telegram_section_block(plain_text_title: str, content_lines: list[str]) -> str:
    if len(content_lines) == 0:
        return ""

    section_header: str = build_telegram_section_header(plain_text_title)
    section_content: str = "\n".join(content_lines)
    return f"{section_header}\n{section_content}\n"
