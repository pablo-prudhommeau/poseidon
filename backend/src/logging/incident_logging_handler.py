from __future__ import annotations

import logging
import sys

from src.configuration.config import settings
from src.logging.incident_forwarding_service import (
    forward_log_record_to_telegram,
    forward_logging_handler_failure,
)


class IncidentLoggingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)

    def emit(self, log_record: logging.LogRecord) -> None:
        forward_log_record_to_telegram(log_record)

    def handleError(self, record: logging.LogRecord) -> None:
        exception_information = sys.exc_info()
        if exception_information[0] is None:
            return
        forward_logging_handler_failure(
            log_record=record,
            exception_type=exception_information[0],
            exception_value=exception_information[1],
            exception_traceback=exception_information[2],
        )


def install_incident_logging_handler(root_logger: logging.Logger) -> None:
    if not settings.LOGGING_INCIDENT_FORWARDING_ENABLED:
        return

    for handler in root_logger.handlers:
        if isinstance(handler, IncidentLoggingHandler):
            return

    root_logger.addHandler(IncidentLoggingHandler())
