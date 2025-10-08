import asyncio
import threading
import time
from typing import Optional, Dict, Any

from src.api.websocket.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.jobs.trending_job import TrendingJob
from src.core.structures.structures import Mode
from src.core.utils.pnl_utils import fifo_realized_pnl, cash_from_trades, holdings_and_unrealized_from_trades
from src.core.utils.price_utils import merge_prices_with_entry
from src.integrations.dexscreener.dexscreener_client import fetch_prices_by_token_addresses
from src.logging.logger import get_logger
from src.persistence import dao
from src.persistence.dao.portfolio_snapshots import snapshot_portfolio, equity_curve
from src.persistence.dao.positions import (
    get_open_addresses,
    serialize_positions_with_prices_by_token_address,
    get_open_positions,
)
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import _session
from src.persistence.serializers import serialize_trade, serialize_portfolio
from src.persistence.service import check_thresholds_and_autosell_for_token_address

log = get_logger(__name__)

_thread: Optional[threading.Thread] = None
_trending_job: Optional[TrendingJob] = None
_started: bool = False
_price_task: asyncio.Task | None = None


def _loop() -> None:
    """Background loop that runs the trending job at a fixed interval."""
    interval = int(settings.TREND_INTERVAL_SEC)
    log.info("Background trending loop starting (interval=%ss)", interval)
    while True:
        try:
            _trending_job.run_once()
        except Exception as exc:
            log.exception("Trending loop error: %s", exc)
        time.sleep(interval)


def ensure_started() -> None:
    """Start the trending loop & price loop once; also install the log bridge."""
    global _started, _thread, _trending_job, _price_task
    if _started:
        return

    _trending_job = TrendingJob()

    _thread = threading.Thread(target=_loop, name="trending-loop", daemon=True)
    _thread.start()
    _started = True

    loop = asyncio.get_event_loop()
    if _price_task is None or _price_task.done():
        _price_task = loop.create_task(_dex_prices_loop())


def get_status() -> Dict[str, Any]:
    """Return a lightweight orchestrator status for the API/UI."""
    return {
        "mode": Mode.PAPER if settings.PAPER_MODE else Mode.LIVE,
        "interval": int(settings.TREND_INTERVAL_SEC),
        "prices_interval": int(settings.DEXSCREENER_FETCH_INTERVAL_SECONDS),
    }


async def _dex_prices_loop() -> None:
    """
    Background loop that fetches live prices and broadcasts portfolio updates.

    Remarques:
    - L'autosell s'exécute ici sur les prix live. Les ventes qui ferment entièrement
      une position arment un cooldown via dao.trades.sell (re-entry lock).
    - On valorise l'UI avec 'display_prices' (live ou fallback entry).
    """
    fetch_interval = max(1, int(settings.DEXSCREENER_FETCH_INTERVAL_SECONDS))
    log.info("Background DexScreener price loop starting (interval=%ss)", fetch_interval)

    while True:
        try:
            with _session() as db:
                addresses = get_open_addresses(db)

            if addresses:
                live_prices: Dict[str, float] = await fetch_prices_by_token_addresses(addresses)

                with _session() as db:
                    for addr, price in (live_prices or {}).items():
                        autos = check_thresholds_and_autosell_for_token_address(
                            db, tokenAddress=addr, last_price=price
                        )
                        for tr in autos:
                            ws_manager.broadcast_json_threadsafe(
                                {"type": "trade", "payload": serialize_trade(tr)}
                            )

                    positions = get_open_positions(db)
                    display_prices = merge_prices_with_entry(positions, live_prices)
                    pos_payload = serialize_positions_with_prices_by_token_address(db, display_prices)
                    ws_manager.broadcast_json_threadsafe(
                        {"type": "positions", "payload": pos_payload}
                    )

                    get_all = getattr(dao, "get_all_trades", None)
                    trades = get_all(db) if callable(get_all) else get_recent_trades(db, limit=10000)

                    starting_cash: float = float(settings.PAPER_STARTING_CASH)
                    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)

                    cash, _, _, _ = cash_from_trades(starting_cash, trades)
                    holdings_live, unrealized_live = holdings_and_unrealized_from_trades(
                        trades, display_prices
                    )
                    equity = round(cash + holdings_live, 2)

                    snap = snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings_live)
                    portfolio_payload = serialize_portfolio(
                        snap,
                        equity_curve=equity_curve(db),
                        realized_total=realized_total,
                        realized_24h=realized_24h,
                    )
                    portfolio_payload["unrealized_pnl"] = unrealized_live
                    ws_manager.broadcast_json_threadsafe(
                        {"type": "portfolio", "payload": portfolio_payload}
                    )

        except Exception:
            log.exception("DexScreener price loop error")

        await asyncio.sleep(fetch_interval)
