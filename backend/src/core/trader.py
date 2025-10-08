from __future__ import annotations

"""
Trader service.

Behavior:
- PAPER mode (default): write paper trades to DB and broadcast updates.
- LIVE mode (Option B): execute a provided LI.FI route on-chain using external signers:
  * EVM: eth-account HD wallet (mnemonic in env, derived address)
  * Solana: base58 secret key (no mnemonic ingestion in code)
Requirements for LIVE execution:
- settings.TRADING_LIVE_ENABLED must be true AND class attribute self.paper must be False.
- The incoming payload must include a 'lifi_route' dictionary produced by LI.FI (/v1/quote, etc.).
  We intentionally do not reconstruct a route here; upstream logic should obtain the route.

Logging policy:
- INFO for major steps and final outcomes.
- DEBUG for low-level details; never log secrets or raw calldata.
"""

import asyncio
from typing import Any, Dict, Optional, List

from src.api.ws_manager import ws_manager
from src.configuration.config import settings
from src.core.pnl import (
    fifo_realized_pnl,
    cash_from_trades,
    holdings_and_unrealized_from_trades,
)
from src.integrations.dexscreener_client import fetch_prices_by_addresses
from src.core.prices import merge_prices_with_entry
from src.core.risk_manager import AdaptiveRiskManager
from src.integrations.dexscreener_client import fetch_prices_by_addresses_sync
from src.logging.logger import get_logger
from src.persistence.dao import trades
from src.persistence.dao.portfolio_snapshots import snapshot_portfolio, equity_curve
from src.persistence.dao.positions import get_open_positions, serialize_positions_with_prices_by_address
from src.persistence.dao.trades import get_recent_trades
from src.persistence.db import _session
from src.persistence.models import Status
from src.persistence.serializers import serialize_trade, serialize_portfolio
from src.persistence.service import check_thresholds_and_autosell
from src.core.live_executor import LiveExecutionService

log = get_logger(__name__)


class Trader:
    """Trader that operates in PAPER mode by default and supports opt-in LIVE execution."""

    def __init__(self) -> None:
        self.paper = settings.PAPER_MODE
        self.realized_pnl_usd: float = 0.0

    def _dex_price_for_address(self, address: str) -> Optional[float]:
        """Fetch a live DEX price for a single address (sync-friendly)."""
        if not address:
            return None
        try:
            try:
                asyncio.get_running_loop()
                log.debug("Detected running event loop, skipping synchronous DEX price for %s", address)
                return None
            except RuntimeError:
                pass

            result = fetch_prices_by_addresses_sync([address])
            price = result.get(address)
            return float(price) if price and price > 0 else None
        except Exception as exc:
            log.warning("DexScreener price fetch failed for %s: %s", address, exc)
            return None

    async def _recompute_and_broadcast(self) -> None:
        """Recompute portfolio metrics with PnL helpers, then broadcast positions and portfolio."""
        with _session() as db:
            positions = get_open_positions(db)
            trades_rows = get_recent_trades(db, limit=10000)

            addresses: List[str] = [getattr(p, "address", "") for p in positions if getattr(p, "address", None)]
            live_prices: Dict[str, float] = await fetch_prices_by_addresses(addresses)
            display_prices = merge_prices_with_entry(positions, live_prices)

            starting_cash = float(settings.PAPER_STARTING_CASH)
            realized_total, realized_24h = fifo_realized_pnl(trades_rows, cutoff_hours=24)
            cash, _, _, _ = cash_from_trades(starting_cash, trades_rows)
            holdings_value, unrealized = holdings_and_unrealized_from_trades(trades_rows, display_prices)
            equity = round(cash + holdings_value, 2)

            snap = snapshot_portfolio(db, equity=equity, cash=cash, holdings=holdings_value)
            pos_payload = serialize_positions_with_prices_by_address(db, display_prices)
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
        """Schedule a recomputation and broadcast."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._recompute_and_broadcast())
        except RuntimeError:
            asyncio.run(self._recompute_and_broadcast())

    @staticmethod
    def _infer_route_network(route: Dict[str, Any]) -> str:
        """
        Infer whether a LI.FI route targets EVM or Solana.

        Heuristics:
        - EVM: 'transactionRequest' key is present with 'to' and 'data'.
        - Solana: 'transaction' or 'transactions' includes a 'serializedTransaction' field (base64).
        """
        if isinstance(route, dict) and "transactionRequest" in route:
            return "EVM"
        if isinstance(route, dict) and ("transaction" in route or "transactions" in route):
            return "SOLANA"
        # Fallback to EVM to avoid accidental Solana signing with wrong data.
        return "EVM"

    async def _execute_live_buy(
            self,
            *,
            symbol: str,
            chain: str,
            address: str,
            qty: float,
            price: float,
            stop: float,
            tp1: float,
            tp2: float,
            lifi_route: Dict[str, Any],
    ) -> None:
        """
        Execute a live buy using a precomputed LI.FI route and persist the trade.

        The route must be produced upstream via LI.FI API. We do not compute it here.
        """
        exec_service = LiveExecutionService()
        try:
            network = self._infer_route_network(lifi_route)
            log.info("LIVE buy: executing route for %s on %s (chain=%s)", symbol, network, chain)

            if network == "EVM":
                tx_hash = await exec_service.evm_execute_route(lifi_route)
                raw_result: Dict[str, Any] = {"network": "EVM", "tx_hash": tx_hash}
                log.info("LIVE buy: EVM broadcast successful for %s, tx_hash=%s", symbol, tx_hash)
            else:
                signature = await exec_service.solana_execute_route(lifi_route)
                raw_result = {"network": "SOLANA", "signature": signature}
                log.info("LIVE buy: Solana broadcast successful for %s, signature=%s", symbol, signature)

            # Persist the live trade result
            with _session() as db:
                trade = trades.buy(
                    db=db,
                    symbol=symbol,
                    chain=chain,
                    address=address,
                    qty=qty,
                    price=float(price),
                    stop=float(stop),
                    tp1=float(tp1),
                    tp2=float(tp2),
                    fee=0.0,
                    status=Status.LIVE,
                    raw_order_result=raw_result,
                )
                ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(trade)})
        except Exception as exc:
            log.exception("LIVE buy: execution failed for %s (%s): %s", symbol, address, exc)
        finally:
            try:
                await exec_service.close()
            except Exception:
                pass
            self._rebroadcast_portfolio()

    def buy(self, it: Dict[str, Any]) -> None:
        """
        Open a position in PAPER or LIVE mode.

        PAPER:
            - Compute thresholds, record paper trade, broadcast updates.
        LIVE:
            - Requires settings.TRADING_LIVE_ENABLED is True and class is not in PAPER mode.
            - Requires 'lifi_route' provided in the payload 'it'.
        """
        symbol = it.get("symbol")
        address = it.get("address") or ""
        chain = (it.get("chain") or "unknown").lower()

        # Price discovery with DexScreener and optional fallback
        dex_price = self._dex_price_for_address(address)
        fallback_price: Optional[float] = None
        try:
            raw_price = it.get("price")
            if raw_price is not None:
                raw_price = float(raw_price)
                fallback_price = raw_price if raw_price > 0 else None
        except Exception:
            fallback_price = None

        price = dex_price or fallback_price
        if not address or price is None:
            log.debug("BUY skipped: invalid address/price (address=%s price=%s symbol=%s)", address, price, symbol)
            return

        # Sanity check on price deviation vs. external reference (if both are present)
        max_mult = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)
        if dex_price is not None and fallback_price is not None:
            low, high = sorted([dex_price, fallback_price])
            if high > 0 and (high / low) > max_mult:
                log.warning("BUY skipped: price mismatch for %s DEX=%.6f vs ext=%.6f (>x%.1f)", symbol, dex_price, fallback_price, max_mult)
                return

        # Order sizing
        order_notional = float(it.get("order_notional") or 0.0)
        if order_notional <= 0.0:
            log.debug("BUY skipped: invalid order_notional=%s for %s", order_notional, symbol)
            return
        qty = order_notional / float(price)

        # Risk thresholds
        thresholds = AdaptiveRiskManager().compute_thresholds(float(price), it)
        stop = thresholds.stop_loss
        tp1 = thresholds.take_profit_tp1
        tp2 = thresholds.take_profit_tp2

        # PAPER mode (default)
        if self.paper or not settings.TRADING_LIVE_ENABLED:
            with _session() as db:
                trade = trades.buy(
                    db=db,
                    symbol=symbol,
                    chain=chain,
                    address=address,
                    qty=qty,
                    price=float(price),
                    stop=float(stop),
                    tp1=float(tp1),
                    tp2=float(tp2),
                    fee=0.0,
                    status=Status.PAPER,
                )
                ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(trade)})
                auto_trades = check_thresholds_and_autosell(db, symbol=symbol, last_price=float(price))
                for atr in auto_trades:
                    ws_manager.broadcast_json_threadsafe({"type": "trade", "payload": serialize_trade(atr)})
            self._rebroadcast_portfolio()
            return

        # LIVE mode: execute a precomputed LI.FI route (Option B)
        lifi_route = it.get("lifi_route")
        if not isinstance(lifi_route, dict):
            log.warning(
                "LIVE buy skipped for %s: missing 'lifi_route' in payload. "
                "Provide a LI.FI route object (from /v1/quote) or enable PAPER_MODE.",
                symbol,
            )
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._execute_live_buy(
                    symbol=symbol,
                    chain=chain,
                    address=address,
                    qty=qty,
                    price=float(price),
                    stop=float(stop),
                    tp1=float(tp1),
                    tp2=float(tp2),
                    lifi_route=lifi_route,
                )
            )
        except RuntimeError:
            asyncio.run(
                self._execute_live_buy(
                    symbol=symbol,
                    chain=chain,
                    address=address,
                    qty=qty,
                    price=float(price),
                    stop=float(stop),
                    tp1=float(tp1),
                    tp2=float(tp2),
                    lifi_route=lifi_route,
                )
            )
