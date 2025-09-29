import asyncio
import threading
import time
from typing import Optional, Dict, Any

from src.api.ws_hub import ws_manager
from src.configuration.config import settings
from src.core.pnl import (
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)
from src.core.trending_job import TrendingJob
from src.integrations.dexscreener_client import fetch_prices_by_addresses
from src.logging.logger import get_logger
from src.persistence import dao
from src.persistence.dao.portfolio_snapshots import snapshot_portfolio, equity_curve
from src.persistence.dao.positions import get_open_addresses, serialize_positions_with_prices_by_address, \
    get_open_positions
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import _session
from src.persistence.serializers import serialize_trade, serialize_portfolio
from src.persistence.service import check_thresholds_and_autosell_for_address

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
        "mode": "PAPER" if settings.PAPER_MODE else "LIVE",
        "interval": int(settings.TREND_INTERVAL_SEC),
    }


def reset_runtime_state() -> None:
    """
    Clear in-memory runtime state for PAPER resets:
    - Trader positions and PnL accumulator
    - Safety blacklist
    """
    try:
        if _trending_job and _trending_job.trader:
            t = _trending_job.trader
            open_count = len(t.positions)
            t.positions.clear()
            t.realized_pnl_usd = 0.0
            log.info("Runtime trader state cleared (positions=%d -> 0)", open_count)
        log.info("Runtime safety state cleared")
    except Exception:
        log.exception("Failed to reset runtime state")


async def _dex_prices_loop() -> None:
    """Background loop that fetches live prices and broadcasts portfolio updates."""
    log.info(
        "Background DexScreener price loop starting (interval=%ss)",
        settings.DEXSCREENER_FETCH_INTERVAL_SECONDS,
    )
    while True:
        try:
            with _session() as db:
                addresses = get_open_addresses(db)

            if addresses:
                address_price: Dict[str, float] = await fetch_prices_by_addresses(addresses)

                with _session() as db:
                    for addr, price in address_price.items():
                        autos = check_thresholds_and_autosell_for_address(db, address=addr, last_price=price)
                        for tr in autos:
                            ws_manager.broadcast_json_threadsafe(
                                {"type": "trade", "payload": serialize_trade(tr)}
                            )
                    pos_payload = serialize_positions_with_prices_by_address(db, address_price)
                    ws_manager.broadcast_json_threadsafe(
                        {"type": "positions", "payload": pos_payload}
                    )
                    positions = get_open_positions(db)
                    get_all = getattr(dao, "get_all_trades", None)
                    trades = get_all(db) if callable(get_all) else get_recent_trades(db, limit=10000)
                    starting_cash: float = float(settings.PAPER_STARTING_CASH)
                    realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
                    cash, _, _, _ = cash_from_trades(starting_cash, trades)
                    holdings_live, unrealized_live = holdings_and_unrealized(positions, address_price)
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

        await asyncio.sleep(max(1, int(settings.DEXSCREENER_FETCH_INTERVAL_SECONDS)))
