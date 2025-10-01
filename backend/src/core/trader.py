from __future__ import annotations

import asyncio
from typing import Any
from typing import Dict, Optional

from src.api.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.pnl import (
    latest_prices_for_positions,
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized,
)
from src.core.risk_manager import AdaptiveRiskManager
from src.integrations.dexscreener_client import fetch_prices_by_addresses_sync
from src.logging.logger import get_logger
from src.persistence.dao import trades
from src.persistence.dao.portfolio_snapshots import snapshot_portfolio, equity_curve
from src.persistence.dao.positions import get_open_positions, serialize_positions_with_prices_by_address
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import _session
from src.persistence.models import Position, Phase, Status
from src.persistence.serializers import serialize_trade, serialize_portfolio
from src.persistence.service import check_thresholds_and_autosell

log = get_logger(__name__)


class Trader:
    """PAPER trader by default.

    - buy(): opens a simulated position
    - evaluate(prices): handles stop/tp exits and logs realized PnL
    - automatically re-broadcasts the portfolio after buy/sell/exit
    """

    def __init__(self) -> None:
        self.paper = settings.PAPER_MODE
        self.realized_pnl_usd: float = 0.0

    def _dex_price_for_address(self, address: str) -> Optional[float]:
        """Fetch a live DEX price for a single address (sync-friendly).

        If already inside a running event loop, we avoid blocking and return None,
        letting the caller use its fallback price if any.
        """
        if not address:
            return None
        try:
            try:
                asyncio.get_running_loop()
                log.debug(
                    "Running loop detected, skipping sync DEX price for %s (will use fallback if any)",
                    address,
                )
                return None
            except RuntimeError:
                pass

            result = fetch_prices_by_addresses_sync([address])
            price = result.get(address.lower())
            return float(price) if price and price > 0 else None
        except Exception as exc:
            log.warning("DexScreener price fetch failed for %s: %s", address, exc)
            return None

    async def _recompute_and_broadcast(self) -> None:
        """Recompute with PnL helpers, then broadcast positions and portfolio."""
        with _session() as db:
            positions = get_open_positions(db)
            trades = get_recent_trades(db, limit=10000)

            prices: Dict[str, float] = {}
            if positions:
                prices = await latest_prices_for_positions(positions)

            starting_cash = float(settings.PAPER_STARTING_CASH)
            realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
            cash, _, _, _ = cash_from_trades(starting_cash, trades)
            holdings, unrealized = holdings_and_unrealized(positions, prices)
            equity = round(cash + holdings, 2)

            snap = snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings)
            pos_payload = serialize_positions_with_prices_by_address(db, prices)
            portfolio_payload = serialize_portfolio(
                snap,
                equity_curve=equity_curve(db),
                realized_total=realized_total,
                realized_24h=realized_24h,
            )
            portfolio_payload["unrealized_pnl"] = unrealized
            ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": pos_payload})
            ws_manager.broadcast_json_threadsafe({"type": "portfolio", "payload": portfolio_payload})

    def _rebroadcast_portfolio(self) -> None:
        """Recompute & re-broadcast the portfolio payload to all clients."""
        try:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._recompute_and_broadcast())
            except RuntimeError:
                asyncio.run(self._recompute_and_broadcast())
        except Exception as exc:
            log.debug("rebroadcast_portfolio failed: %s", exc)

    def buy(self, it: Dict[str, Any]) -> None:
        """Open a (paper) position; supports adaptive overrides from the caller."""
        symbol = it.get("symbol")
        address = it.get("address") or ""
        chain = (it.get("chain") or "unknown").lower()
        ds_price = self._dex_price_for_address(address)
        fallback_price: Optional[float] = None
        try:
            raw_price = it.get("price")
            if raw_price is not None:
                raw_price = float(raw_price)
                fallback_price = raw_price if raw_price > 0 else None
        except Exception:
            fallback_price = None

        price = ds_price or fallback_price
        if not address or price is None:
            log.debug("[BUY SKIP] %s addr/price invalid (addr=%s price=%s)", symbol, address, price)
            return

        max_mult = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)
        if ds_price is not None and fallback_price is not None:
            lo, hi = sorted([ds_price, fallback_price])
            if hi > 0 and (hi / lo) > max_mult:
                log.warning(
                    "[BUY SKIP] %s price mismatch DEX %.6f vs ext %.6f (>x%.1f)",
                    symbol,
                    ds_price,
                    fallback_price,
                    max_mult,
                )
                return

        order_notional = it.get("order_notional")
        qty = order_notional / price

        thresholds = AdaptiveRiskManager().compute_thresholds(price, it)
        stop = thresholds.stop_loss
        tp1 = thresholds.take_profit_tp1
        tp2 = thresholds.take_profit_tp2

        if self.paper:
            liq = float(it.get("liqUsd", 0.0) or 0.0)
            vol = float(it.get("vol24h", 0.0) or 0.0)
            tail = address[-6:] if address else "--"
            src = "DEX" if ds_price is not None else "FALLBACK"
            log.info(
                "[PAPER BUY/%s] %s $%.0f @ $%.8f (~%s %s)liq=$%.0f vol24h=$%.0f 0x%s",
                src,
                symbol,
                order_notional,
                price,
                f"{qty:.6f}",
                symbol,
                liq,
                vol,
                tail,
            )
            log.info("[PAPER EXIT PLAN] %s stop=$%.8f tp1=$%.8f tp2=$%.8f", symbol, stop, tp1, tp2)
            with _session() as db:
                trade = trades.buy(
                    db,
                    symbol=symbol,
                    chain=chain,
                    address=address,
                    qty=qty,
                    price=price,
                    stop=stop,
                    tp1=tp1,
                    tp2=tp2,
                    fee=0.0,
                    status=Status.PAPER,
                )
                ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(trade)})
                auto_trades = check_thresholds_and_autosell(db, symbol=symbol, last_price=price)
                for atr in auto_trades:
                    ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(atr)})
                    _schedule_recompute_and_broadcast()
                self._rebroadcast_portfolio()
            return

        log.warning("[LIVE BUY NOT IMPLEMENTED] %s (%s)", symbol, address)


def _schedule_recompute_and_broadcast() -> None:
    """Schedule `_recompute_and_broadcast()` without blocking the caller thread."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_recompute_and_broadcast())
    except RuntimeError:
        asyncio.run(_recompute_and_broadcast())


async def _recompute_and_broadcast() -> None:
    """Recompute with PnL helpers, then broadcast positions and portfolio."""
    with _session() as db:
        positions = get_open_positions(db)
        trades = get_recent_trades(db, limit=10000)
        prices: Dict[str, float] = {}
        if positions:
            prices = await latest_prices_for_positions(positions)

        starting_cash = float(settings.PAPER_STARTING_CASH)
        realized_total, realized_24h = fifo_realized_pnl(trades, cutoff_hours=24)
        cash, _, _, _ = cash_from_trades(starting_cash, trades)
        holdings, unrealized = holdings_and_unrealized(positions, prices)
        equity = round(cash + holdings, 2)
        snap = snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings)
        pos_payload = serialize_positions_with_prices_by_address(db, prices)
        portfolio_payload = serialize_portfolio(
            snap,
            equity_curve=equity_curve(db),
            realized_total=realized_total,
            realized_24h=realized_24h,
        )
        portfolio_payload["unrealized_pnl"] = unrealized
        ws_manager.broadcast_json_threadsafe({"type": "positions", "payload": pos_payload})
        ws_manager.broadcast_json_threadsafe({"type": "portfolio", "payload": portfolio_payload})


async def rebroadcast_portfolio() -> None:
    """Recompute and broadcast portfolio/positions immediately."""
    await _recompute_and_broadcast()
