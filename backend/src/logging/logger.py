# src/logging/logger.py
from __future__ import annotations

import logging
import sys
import time
from typing import Optional

from src.configuration.config import settings

# ANSI colors
_COLORS = {
    "RESET": "\033[0m",
    "DIM": "\033[2m",
    "BOLD": "\033[1m",
    "GREY": "\033[90m",
    "RED": "\033[31m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "BLUE": "\033[34m",
    "MAGENTA": "\033[35m",
    "CYAN": "\033[36m",
}

_LEVEL_EMOJI = {
    "DEBUG": "🔍",
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "CRITICAL": "🛑",
}

_LEVEL_COLOR = {
    "DEBUG": _COLORS["CYAN"],
    "INFO": _COLORS["GREEN"],
    "WARNING": _COLORS["YELLOW"],
    "ERROR": _COLORS["RED"],
    "CRITICAL": _COLORS["MAGENTA"],
}

APP_NAMESPACE = "poseidon"


def _level_from_str(value: str) -> int:
    try:
        return getattr(logging, (value or "INFO").upper())
    except Exception:
        return logging.INFO


def _canonical_name(name: str) -> str:
    """Map module logger names to the canonical 'poseidon.*' namespace."""
    if name.startswith(APP_NAMESPACE + "."):
        return name
    if name == "src":
        return APP_NAMESPACE
    if name.startswith("src."):
        return APP_NAMESPACE + "." + name[len("src."):]
    return f"{APP_NAMESPACE}.{name}"


def _silence_logger(name: str, level: int) -> None:
    lg = logging.getLogger(name)
    lg.setLevel(level)
    # Some libraries attach their own handlers with raw formats
    lg.handlers.clear()
    lg.propagate = False


class ColorFormatter(logging.Formatter):
    """
    Readable, colored formatter with emoji per level and UTC ISO-8601 timestamps.
    Example:
      2025-10-02 01:36:22.123+0000 ℹ️ INFO     poseidon.core.pnl - Realized P&L computed: total=9.54 recent_24h=9.54
    """

    def __init__(self, use_color: bool = True, datefmt: Optional[str] = None) -> None:
        super().__init__()
        self.use_color = use_color
        self.datefmt = datefmt or "%Y-%m-%d %H:%M:%S.%03d%z"
        self.converter = time.localtime

    def format(self, record: logging.LogRecord) -> str:
        ct = self.converter(record.created)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", ct) + f".{int(record.msecs):03d}+0000"

        level_name = record.levelname.upper()
        emoji = _LEVEL_EMOJI.get(level_name, "")
        message = record.getMessage()
        name = record.name or ""

        if self.use_color:
            color = _LEVEL_COLOR.get(level_name, "")
            reset = _COLORS["RESET"]
            dim = _COLORS["DIM"]
            line = f"{dim}{timestamp}{reset} {color}{emoji} {level_name:<8}{reset} {name} {dim}- {message}{reset}"
        else:
            line = f"{timestamp} {emoji} {level_name:<8} {name} - {message}"

        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def _install_console_handler(root: logging.Logger) -> None:
    """Install a single console handler that does not filter by level (NOTSET)."""
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler) and getattr(h, "_poseidon_handler", False):
            h.setLevel(logging.NOTSET)
            return

    use_color = sys.stderr.isatty() and (not bool(getattr(settings, "NO_COLOR", False)))
    handler = logging.StreamHandler(stream=sys.stderr)
    handler._poseidon_handler = True
    handler.setLevel(logging.NOTSET)
    handler.setFormatter(ColorFormatter(use_color=use_color))
    root.addHandler(handler)


def init_logging() -> None:
    """
    Initialize logging with:
    - UTC ISO-8601 timestamps
    - Emoji per level
    - Unified format for uvicorn/access/error + asyncio + websockets
    """
    root = logging.getLogger()

    # Root level
    root.setLevel(_level_from_str(settings.LOG_LEVEL))
    _install_console_handler(root)

    # All application loggers under 'poseidon' use LOG_LEVEL_POSEIDON
    logging.getLogger(APP_NAMESPACE).setLevel(_level_from_str(settings.LOG_LEVEL_POSEIDON))

    # Tame noisy libs (configurable)
    logging.getLogger("requests").setLevel(_level_from_str(settings.LOG_LEVEL_LIB_REQUESTS))
    logging.getLogger("urllib3").setLevel(_level_from_str(settings.LOG_LEVEL_LIB_URLLIB3))
    logging.getLogger("websockets").setLevel(_level_from_str(settings.LOG_LEVEL_LIB_WEBSOCKETS))
    logging.getLogger("httpx").setLevel(_level_from_str(settings.LOG_LEVEL_LIB_HTTPX))
    logging.getLogger("httpcore").setLevel(_level_from_str(settings.LOG_LEVEL_LIB_HTTPCORE))
    logging.getLogger("asyncio").setLevel(_level_from_str(settings.LOG_LEVEL_LIB_ASYNCIO))
    logging.getLogger("anyio").setLevel(_level_from_str(settings.LOG_LEVEL_LIB_ANYIO))
    logging.getLogger("openai").setLevel(_level_from_str(settings.LOG_LEVEL_LIB_OPENAI))

    # 🔇 Silence raw websocket/protocol traces
    ws_level = _level_from_str(settings.LOG_LEVEL_LIB_WEBSOCKETS)
    _silence_logger("websockets", ws_level)
    _silence_logger("websockets.server", ws_level)
    _silence_logger("websockets.client", ws_level)
    _silence_logger("wsproto", ws_level)
    _silence_logger("uvicorn.protocols.websockets", ws_level)

    # Force uvicorn family to propagate to our root handler (same formatting)
    for name in (
            "uvicorn", "uvicorn.error", "uvicorn.access",
            "uvicorn.asgi", "uvicorn.protocols.http", "uvicorn.protocols.websockets",
    ):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.setLevel(_level_from_str(settings.LOG_LEVEL))
        lg.propagate = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a logger in the canonical 'poseidon.*' namespace."""
    base = name or __name__
    full = _canonical_name(base)
    logger = logging.getLogger(full)
    logger.propagate = True
    return logger
