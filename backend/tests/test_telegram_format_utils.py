from src.integrations.telegram.telegram_format_utils import (
    build_telegram_section_block,
    build_telegram_section_header,
)


def test_build_telegram_section_header_matches_title_length() -> None:
    section_header: str = build_telegram_section_header("Ordre #171")

    assert section_header == "<b>Ordre #171</b>\n──────────"


def test_build_telegram_section_header_includes_emoji_in_underline_length() -> None:
    plain_text_title: str = "📦 Ordre #171"
    section_header: str = build_telegram_section_header(plain_text_title)

    assert section_header.startswith("<b>📦 Ordre #171</b>\n")
    underline_line: str = section_header.split("\n", maxsplit=1)[1]
    assert len(underline_line) == len(plain_text_title)
    assert set(underline_line) == {"─"}


def test_build_telegram_section_block_assembles_header_and_content() -> None:
    section_block: str = build_telegram_section_block(
        "Identité",
        [
            "🔹 <b>Actif:</b> <code>BTC.b</code>",
            "📌 <b>Statut:</b> <code>SKIPPED</code>",
        ],
    )

    assert section_block.startswith("<b>Identité</b>\n────────\n")
    assert "🔹 <b>Actif:</b> <code>BTC.b</code>" in section_block
    assert section_block.endswith("\n")


def test_build_telegram_section_block_returns_empty_string_for_empty_content() -> None:
    section_block: str = build_telegram_section_block("Pipeline", [])

    assert section_block == ""


def test_telegram_main_title_body_separator_uses_two_blank_lines() -> None:
    from src.integrations.telegram.telegram_format_utils import TELEGRAM_MAIN_TITLE_BODY_SEPARATOR

    assert TELEGRAM_MAIN_TITLE_BODY_SEPARATOR == "\n\n\n"
