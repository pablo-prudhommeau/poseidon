from __future__ import annotations

import logging
import os
import sys
import time
from typing import Optional

from src.configuration.config import settings

console_color_codes = {
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

level_to_emoji_mapping = {
    "DEBUG": "⚙️",
    "INFO": "ℹ️",
    "WARNING": "⚠️",
    "ERROR": "❌ ",
    "CRITICAL": "🛑 ",
}

level_to_color_mapping = {
    "DEBUG": console_color_codes["CYAN"],
    "INFO": console_color_codes["GREEN"],
    "WARNING": console_color_codes["YELLOW"],
    "ERROR": console_color_codes["RED"],
    "CRITICAL": console_color_codes["MAGENTA"],
}

application_namespace = "poseidon"
default_logger_name_width = 40


def get_logging_level_from_string(level_name: str) -> int:
    level_mapping = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    if level_name in level_mapping:
        return level_mapping[level_name]

    return logging.INFO


def get_canonical_logger_name(raw_logger_name: str) -> str:
    if raw_logger_name.startswith(f"{application_namespace}."):
        return raw_logger_name

    if raw_logger_name == "src":
        return application_namespace

    if raw_logger_name.startswith("src."):
        namespace_suffix = raw_logger_name[4:]
        return f"{application_namespace}.{namespace_suffix}"

    return f"{application_namespace}.{raw_logger_name}"


def format_logger_namespace(namespace: str, maximum_width: int) -> str:
    if len(namespace) <= maximum_width:
        return f"{namespace:<{maximum_width}}"

    namespace_parts = namespace.split(".")
    last_part_index = len(namespace_parts) - 1

    for current_index in range(last_part_index - 1, -1, -1):
        namespace_parts[current_index] = namespace_parts[current_index][0]
        current_abbreviation = ".".join(namespace_parts)

        if len(current_abbreviation) <= maximum_width:
            return f"{current_abbreviation:<{maximum_width}}"

    final_abbreviation = ".".join(namespace_parts)
    return final_abbreviation[:maximum_width]


def silence_specific_logger(logger_name: str, logging_level: int) -> None:
    logger_instance = logging.getLogger(logger_name)
    logger_instance.setLevel(logging_level)
    logger_instance.handlers.clear()
    logger_instance.propagate = False


def check_color_support_enabled() -> bool:
    if "NO_COLOR" in os.environ:
        return False

    if "FORCE_COLOR" in os.environ or "PYCHARM_HOSTED" in os.environ:
        return True

    return sys.stdout.isatty()


class PoseidonStreamHandler(logging.StreamHandler):
    pass


class PoseidonColorFormatter(logging.Formatter):
    def __init__(self, enable_color: bool) -> None:
        super().__init__()
        self.enable_color = enable_color
        self.time_converter = time.localtime

    def format(self, log_record: logging.LogRecord) -> str:
        creation_time_struct = self.time_converter(log_record.created)
        formatted_timestamp = time.strftime("%Y-%m-%d %H:%M:%S", creation_time_struct)
        milliseconds = int(log_record.msecs)
        timezone_offset = time.strftime("%z", creation_time_struct)
        complete_timestamp = f"{formatted_timestamp}.{milliseconds:03d}{timezone_offset}"

        level_name_upper = log_record.levelname.upper()
        emoji_icon = level_to_emoji_mapping[level_name_upper] if level_name_upper in level_to_emoji_mapping else "  "
        log_message = log_record.getMessage()
        logger_name = log_record.name if log_record.name is not None else "root"

        formatted_logger_name = format_logger_namespace(logger_name, default_logger_name_width)

        if self.enable_color:
            level_color = level_to_color_mapping[level_name_upper] if level_name_upper in level_to_color_mapping else ""
            color_reset = console_color_codes["RESET"]
            color_dim = console_color_codes["DIM"]

            formatted_line = f"{color_dim}[{complete_timestamp}]{color_reset} {level_color}{emoji_icon} [{level_name_upper:<8}]{color_reset} {color_dim}[{formatted_logger_name}]{color_reset} {level_color}→{color_reset} {log_message}"
        else:
            formatted_line = f"[{complete_timestamp}] {emoji_icon} [{level_name_upper:<8}] [{formatted_logger_name}] → {log_message}"

        if log_record.exc_info:
            formatted_line = f"{formatted_line}\n{self.formatException(log_record.exc_info)}"

        return formatted_line


def install_unfiltered_console_handler(root_logger: logging.Logger) -> None:
    for handler in root_logger.handlers:
        if isinstance(handler, PoseidonStreamHandler):
            handler.setLevel(logging.NOTSET)
            return

    console_handler = PoseidonStreamHandler(stream=sys.stdout)
    console_handler.setLevel(logging.NOTSET)
    console_handler.setFormatter(PoseidonColorFormatter(enable_color=check_color_support_enabled()))
    root_logger.addHandler(console_handler)


def initialize_application_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(get_logging_level_from_string(settings.LOG_LEVEL))
    install_unfiltered_console_handler(root_logger)

    application_logger = logging.getLogger(application_namespace)
    application_logger.setLevel(get_logging_level_from_string(settings.LOG_LEVEL_POSEIDON))

    logging.getLogger("requests").setLevel(get_logging_level_from_string(settings.LOG_LEVEL_LIB_REQUESTS))
    logging.getLogger("urllib3").setLevel(get_logging_level_from_string(settings.LOG_LEVEL_LIB_URLLIB3))
    logging.getLogger("websockets").setLevel(get_logging_level_from_string(settings.LOG_LEVEL_LIB_WEBSOCKETS))
    logging.getLogger("httpx").setLevel(get_logging_level_from_string(settings.LOG_LEVEL_LIB_HTTPX))
    logging.getLogger("httpcore").setLevel(get_logging_level_from_string(settings.LOG_LEVEL_LIB_HTTPCORE))
    logging.getLogger("asyncio").setLevel(get_logging_level_from_string(settings.LOG_LEVEL_LIB_ASYNCIO))
    logging.getLogger("anyio").setLevel(get_logging_level_from_string(settings.LOG_LEVEL_LIB_ANYIO))
    logging.getLogger("openai").setLevel(get_logging_level_from_string(settings.LOG_LEVEL_LIB_OPENAI))

    websocket_logging_level = get_logging_level_from_string(settings.LOG_LEVEL_LIB_WEBSOCKETS)
    silence_specific_logger("websockets", websocket_logging_level)
    silence_specific_logger("websockets.server", websocket_logging_level)
    silence_specific_logger("websockets.client", websocket_logging_level)
    silence_specific_logger("wsproto", websocket_logging_level)
    silence_specific_logger("uvicorn.protocols.websockets", websocket_logging_level)

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
        uvicorn_logger_instance.setLevel(get_logging_level_from_string(settings.LOG_LEVEL))
        uvicorn_logger_instance.propagate = True


def get_application_logger(logger_name: Optional[str] = None) -> logging.Logger:
    base_logger_name = logger_name if logger_name is not None else __name__
    canonical_logger_name = get_canonical_logger_name(base_logger_name)
    configured_logger = logging.getLogger(canonical_logger_name)
    configured_logger.propagate = True

    return configured_logger
