# src/logger.py
import logging, sys
from src.config import settings

_FMT = "%(asctime)s %(levelname)s %(name)s:%(lineno)d — %(message)s"

def _lvl(name, default=logging.INFO) -> int:
    try:
        return logging._nameToLevel.get(str(name).upper(), default)
    except Exception:
        return default

def init_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter(_FMT))
        h.setLevel(_lvl(getattr(settings, "LOG_LEVEL", "INFO")))   # <= handler level aussi
        root.addHandler(h)
    root.setLevel(_lvl(getattr(settings, "LOG_LEVEL", "INFO")))     # <= insensible à la casse

    # Verbosité libs (mêmes protections)
    logging.getLogger("requests").setLevel(_lvl(getattr(settings, "LOG_LEVEL_LIB_REQUESTS", "WARNING"), logging.WARNING))
    logging.getLogger("urllib3").setLevel(_lvl(getattr(settings, "LOG_LEVEL_LIB_URLLIB3", "WARNING"), logging.WARNING))  # si var existe
    logging.getLogger("web3").setLevel(_lvl(getattr(settings, "LOG_LEVEL_LIB_WEB3", "WARNING"), logging.WARNING))
    logging.getLogger("websockets").setLevel(_lvl(getattr(settings, "LOG_LEVEL_LIB_WEBS", "WARNING"), logging.WARNING))
    logging.getLogger("websockets.client").setLevel(_lvl(getattr(settings, "LOG_LEVEL_LIB_WEBS", "WARNING"), logging.WARNING))

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
