# src/ui/orchestrator.py
from __future__ import annotations

import os
import threading
import time
from typing import Optional

from src.logger import get_logger, init_logging
from src.config import settings
from src.trending.trending_job import TrendingJob
from src.ui.log_bridge import install_bridge

log = get_logger(__name__)

_w3 = None
_thread: Optional[threading.Thread] = None
_trending_job: Optional[TrendingJob] = None
_started = False


def _is_connected(w3) -> bool:
    if not w3:
        return False
    try:
        return bool(w3.is_connected())  # web3>=6
    except Exception:
        try:
            return bool(w3.isConnected())  # web3<6
        except Exception:
            return False


def _make_web3():
    """Essaie d'instancier Web3 depuis QUICKNODE_URL (WS puis HTTP)."""
    try:
        from web3 import Web3  # type: ignore
    except Exception:
        return None

    url = (getattr(settings, "QUICKNODE_URL", "") or os.getenv("QUICKNODE_URL", "")).strip()
    if not url:
        return None

    if url.startswith("ws"):
        try:
            w3 = Web3(Web3.WebsocketProvider(url, websocket_timeout=10))
            if _is_connected(w3):
                return w3
        except Exception:
            log.warning("WS provider failed, fallback to HTTP")

    try:
        w3 = Web3(Web3.HTTPProvider(url))
        if _is_connected(w3):
            return w3
    except Exception:
        pass
    return None


def _loop():
    interval = int(getattr(settings, "TREND_INTERVAL_SEC", 180))
    log.info("Background trending loop starting (interval=%ss)", interval)
    while True:
        try:
            _trending_job.run_once()  # type: ignore[attr-defined]
        except Exception as e:
            log.exception("Trending loop error: %s", e)
        time.sleep(interval)


def ensure_started():
    """Démarre une seule fois la boucle de trending + installe le log bridge."""
    global _started, _thread, _trending_job, _w3
    if _started:
        return

    init_logging()
    install_bridge()  # persiste automatiquement les logs PAPER (BUY/EXIT PLAN/TP/EXIT)

    _w3 = _make_web3()
    _trending_job = TrendingJob(_w3)

    _thread = threading.Thread(target=_loop, name="trending-loop", daemon=True)
    _thread.start()
    _started = True


def get_status():
    return {
        "mode": "PAPER" if getattr(settings, "PAPER_MODE", True) else "LIVE",
        "web3_ok": _is_connected(_w3),
        "interval": int(getattr(settings, "TREND_INTERVAL_SEC", 180)),
    }
