# src/ui/orchestrator.py
from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Optional, Dict

from src.configuration.config import settings
from src.integrations.dexscreener_client import fetch_prices_by_addresses
from src.logging.logger import get_logger, init_logging
from src.persistence import crud
from src.persistence.db import SessionLocal
from src.persistence.serializers import serialize_trade, serialize_portfolio
from src.core.trending_job import TrendingJob
from src.core.log_bridge import install_bridge
from src.api.ws_hub import ws_manager
from src.core.pnl import (
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)

log = get_logger(__name__)

_w3 = None
_thread: Optional[threading.Thread] = None
_trending_job: Optional[TrendingJob] = None
_started = False
_price_task: asyncio.Task | None = None


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

    global _price_task
    loop = asyncio.get_event_loop()
    if _price_task is None or _price_task.done():
        _price_task = loop.create_task(_dex_prices_loop())


def get_status():
    return {
        "mode": "PAPER" if getattr(settings, "PAPER_MODE", True) else "LIVE",
        "web3_ok": _is_connected(_w3),
        "interval": int(getattr(settings, "TREND_INTERVAL_SEC", 180)),
    }


async def _dex_prices_loop():
    log.info("Background DexScreener price loop starting (interval=%ss)", settings.DEXSCREENER_FETCH_INTERVAL_SECONDS)
    while True:
        try:
            with SessionLocal() as db:
                addresses = crud.get_open_addresses(db)

            if addresses:
                address_price: Dict[str, float] = await fetch_prices_by_addresses(addresses)

                with SessionLocal() as db:
                    # autosell par adresse (résultats -> broadcast trade)
                    for addr, price in address_price.items():
                        autos = crud.check_thresholds_and_autosell_for_address(db, address=addr, last_price=price)
                        for tr in autos:
                            ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(tr)})

                    # broadcast positions avec last_price live (par adresse)
                    pos_payload = crud.serialize_positions_with_prices_by_address(db, address_price)
                    ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": pos_payload})

                    # ------ Calculs PnL centralisés via pnl_center ------
                    positions = crud.get_open_positions(db)
                    # get_all_trades si dispo, sinon recent large
                    get_all = getattr(crud, "get_all_trades", None)
                    trades = get_all(db) if callable(get_all) else crud.get_recent_trades(db, limit=10000)

                    start_cash = float(getattr(settings, "PAPER_STARTING_CASH", 10_000.0))
                    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
                    cash, _, _, _ = cash_from_trades(start_cash, trades)
                    holdings_live, unrealized_live = holdings_and_unrealized(positions, address_price)
                    equity = round(cash + holdings_live, 2)

                    # snapshot (écriture simple)
                    snap = crud.snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings_live)

                    # payload portfolio
                    portfolio_payload = serialize_portfolio(
                        snap,
                        equity_curve=crud.equity_curve(db),
                        realized_total=realized_total,
                        realized_24h=realized_24h,
                    )
                    portfolio_payload["unrealized_pnl"] = unrealized_live

                    ws_manager.broadcast_json_threadsafe({
                        "type": "portfolio",
                        "payload": portfolio_payload
                    })
        except Exception:
            log.exception("DexScreener price loop error")
        await asyncio.sleep(max(1, int(settings.DEXSCREENER_FETCH_INTERVAL_SECONDS)))
