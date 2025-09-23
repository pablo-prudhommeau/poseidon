# src/logger.py
import logging
import sys
from src.config import settings

_FMT = "%(asctime)s %(levelname)s %(name)s:%(lineno)d — %(message)s"

def init_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter(_FMT))
        root.addHandler(h)
    root.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))

    # Libs verbosity
    logging.getLogger("requests").setLevel(getattr(logging, settings.LOG_LEVEL_LIB_REQUESTS, logging.WARNING))
    logging.getLogger("urllib3").setLevel(getattr(logging, settings.LOG_LEVEL_LIB_REQUESTS, logging.WARNING))
    logging.getLogger("web3").setLevel(getattr(logging, settings.LOG_LEVEL_LIB_WEB3, logging.WARNING))
    logging.getLogger("websockets").setLevel(getattr(logging, settings.LOG_LEVEL_LIB_WEB3, logging.WARNING))
    logging.getLogger("websockets.client").setLevel(getattr(logging, settings.LOG_LEVEL_LIB_WEB3, logging.WARNING))

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
