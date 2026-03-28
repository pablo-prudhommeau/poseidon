from __future__ import annotations

import logging
import sys
import time
from typing import Optional

from src.configuration.config import settings

_TERMINAL_COLORS: dict[str, str] = {
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

_LOG_LEVEL_EMOJIS: dict[str, str] = {
    "DEBUG": "🔍",
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "ERROR": "❌",
    "CRITICAL": "🛑",
}

_LOG_LEVEL_COLORS: dict[str, str] = {
    "DEBUG": _TERMINAL_COLORS["CYAN"],
    "INFO": _TERMINAL_COLORS["GREEN"],
    "WARNING": _TERMINAL_COLORS["YELLOW"],
    "ERROR": _TERMINAL_COLORS["RED"],
    "CRITICAL": _TERMINAL_COLORS["MAGENTA"],
}

_LOG_LEVEL_MAPPING: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

APPLICATION_NAMESPACE: str = "poseidon"


def _get_logging_level_from_string(level_string: str) -> int:
    sanitized_level_string = (level_string or "INFO").upper()
    if sanitized_level_string in _LOG_LEVEL_MAPPING:
        return _LOG_LEVEL_MAPPING[sanitized_level_string]
    return logging.INFO


def _get_canonical_logger_name(module_name: str) -> str:
    if module_name.startswith(APPLICATION_NAMESPACE + "."):
        return module_name
    if module_name == "src":
        return APPLICATION_NAMESPACE
    if module_name.startswith("src."):
        return APPLICATION_NAMESPACE + "." + module_name[len("src."):]
    return f"{APPLICATION_NAMESPACE}.{module_name}"


def _silence_logger_output(logger_name: str, target_level: int) -> None:
    logger_instance = logging.getLogger(logger_name)
    logger_instance.setLevel(target_level)
    logger_instance.handlers.clear()
    logger_instance.propagate = False


class TerminalColorFormatter(logging.Formatter):
    def __init__(self, is_color_enabled: bool = True, date_format: Optional[str] = None) -> None:
        super().__init__()
        self.is_color_enabled = is_color_enabled
        self.date_format = date_format or "%Y-%m-%d %H:%M:%S"
        self.time_converter = time.localtime

    def format(self, log_record: logging.LogRecord) -> str:
        local_creation_time = self.time_converter(log_record.created)
        base_timestamp = time.strftime(self.date_format, local_creation_time)
        timezone_offset = time.strftime("%z", local_creation_time)
        formatted_timestamp_with_milliseconds = f"{base_timestamp}.{int(log_record.msecs):03d}{timezone_offset}"

        level_name = log_record.levelname.upper()
        emoji_indicator = _LOG_LEVEL_EMOJIS.get(level_name, "")
        log_message = log_record.getMessage()
        logger_name = log_record.name or ""

        if self.is_color_enabled:
            level_color = _LOG_LEVEL_COLORS.get(level_name, "")
            color_reset = _TERMINAL_COLORS["RESET"]
            color_dim = _TERMINAL_COLORS["DIM"]
            formatted_log_line = f"{color_dim}{formatted_timestamp_with_milliseconds}{color_reset} {level_color}{emoji_indicator} {level_name:<8}{color_reset} {logger_name} {color_dim}- {log_message}{color_reset}"
        else:
            formatted_log_line = f"{formatted_timestamp_with_milliseconds} {emoji_indicator} {level_name:<8} {logger_name} - {log_message}"

        if log_record.exc_info:
            formatted_log_line = f"{formatted_log_line}\n{self.formatException(log_record.exc_info)}"

        return formatted_log_line


def _install_console_stream_handler(root_logger: logging.Logger) -> None:
    for existing_handler in root_logger.handlers:
        if isinstance(existing_handler, logging.StreamHandler) and hasattr(existing_handler, "is_poseidon_custom_handler"):
            existing_handler.setLevel(logging.NOTSET)
            return

    is_color_enabled = sys.stderr.isatty() and not bool(getattr(settings, "NO_COLOR", False))
    stream_handler = logging.StreamHandler(stream=sys.stderr)
    setattr(stream_handler, "is_poseidon_custom_handler", True)
    stream_handler.setLevel(logging.NOTSET)
    stream_handler.setFormatter(TerminalColorFormatter(is_color_enabled=is_color_enabled))
    root_logger.addHandler(stream_handler)


def init_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(_get_logging_level_from_string(settings.LOG_LEVEL))
    _install_console_stream_handler(root_logger=root_logger)

    logging.getLogger(APPLICATION_NAMESPACE).setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_POSEIDON))

    logging.getLogger("requests").setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_LIB_REQUESTS))
    logging.getLogger("urllib3").setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_LIB_URLLIB3))
    logging.getLogger("websockets").setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_LIB_WEBSOCKETS))
    logging.getLogger("httpx").setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_LIB_HTTPX))
    logging.getLogger("httpcore").setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_LIB_HTTPCORE))
    logging.getLogger("asyncio").setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_LIB_ASYNCIO))
    logging.getLogger("anyio").setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_LIB_ANYIO))
    logging.getLogger("openai").setLevel(_get_logging_level_from_string(settings.LOG_LEVEL_LIB_OPENAI))

    websockets_log_level = _get_logging_level_from_string(settings.LOG_LEVEL_LIB_WEBSOCKETS)
    _silence_logger_output("websockets", websockets_log_level)
    _silence_logger_output("websockets.server", websockets_log_level)
    _silence_logger_output("websockets.client", websockets_log_level)
    _silence_logger_output("wsproto", websockets_log_level)
    _silence_logger_output("uvicorn.protocols.websockets", websockets_log_level)

    uvicorn_loggers = [
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "uvicorn.asgi",
        "uvicorn.protocols.http",
        "uvicorn.protocols.websockets",
    ]

    for uvicorn_logger_name in uvicorn_loggers:
        uvicorn_logger_instance = logging.getLogger(uvicorn_logger_name)
        uvicorn_logger_instance.handlers.clear()
        uvicorn_logger_instance.setLevel(_get_logging_level_from_string(settings.LOG_LEVEL))
        uvicorn_logger_instance.propagate = True

    application_logger = get_logger(__name__)
    application_logger.info("[LOGGING][SYSTEM][INIT] Application logging successfully initialized with local timezone synchronization")


def get_logger(module_name: Optional[str] = None) -> logging.Logger:
    base_module_name = module_name or __name__
    canonical_module_name = _get_canonical_logger_name(module_name=base_module_name)
    application_logger = logging.getLogger(canonical_module_name)
    application_logger.propagate = True
    return application_logger
