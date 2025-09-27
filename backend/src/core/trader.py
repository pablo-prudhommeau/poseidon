from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

from web3 import Web3

from src.configuration.config import settings
from src.core.trader_hooks import on_trade
from src.integrations.dexscreener.dexscreener_client import fetch_prices_by_addresses
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass
class Position:
    symbol: str
    chain: str
    address: str
    qty: float
    entry: float
    stop: float
    tp1: float
    tp2: float
    phase: str = "OPEN"


class Trader:
    """PAPER trader by default.

    - buy(): opens a simulated position
    - evaluate(prices): handles stop/tp exits and logs realized PnL
    - automatically re-broadcasts the portfolio after buy/sell/exit
    """

    def __init__(self, w3: Optional[Web3] = None) -> None:
        self.w3 = w3
        self.paper = settings.PAPER_MODE
        self.order_usd = 250.0  # simulated order notional
        self.slippage_bps = 75  # 0.75%
        self.positions: Dict[str, Position] = {}  # key = address (lowercased)
        self.realized_pnl_usd: float = 0.0  # internal running total (for logs)

    def _dex_price_for_address(self, address: str) -> Optional[float]:
        """Fetch a live DEX price for a single address (sync-friendly).

        If already inside a running event loop, we avoid blocking and return None,
        letting the caller use its fallback price if any.
        """
        if not address:
            return None
        try:
            # If we're already in an event loop (e.g., FastAPI task), do not block.
            try:
                asyncio.get_running_loop()
                log.debug(
                    "Running loop detected, skipping sync DEX price for %s (will use fallback if any)",
                    address,
                )
                return None
            except RuntimeError:
                # No running loop → we can perform a blocking call safely.
                pass

            result = asyncio.run(
                fetch_prices_by_addresses([address])
            )
            price = result.get(address.lower())
            return float(price) if price and price > 0 else None
        except Exception as exc:
            log.warning("DexScreener price fetch failed for %s: %s", address, exc)
            return None

    def _gas_price_gwei(self) -> Optional[float]:
        """Return current base fee (gwei) if a Web3 client is available."""
        try:
            if not self.w3:
                return None
            return self.w3.eth.gas_price / 1e9
        except Exception:
            return None

    def _rebroadcast_portfolio(self) -> None:
        """Recompute & re-broadcast the portfolio payload to all clients."""
        try:
            # Late import to avoid cycles
            from src.core.trader_hooks import rebroadcast_portfolio  # async

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(rebroadcast_portfolio())
            except RuntimeError:
                asyncio.run(rebroadcast_portfolio())
        except Exception as exc:
            log.debug("rebroadcast_portfolio failed: %s", exc)

    def buy(self, it: Dict[str, Any]) -> None:
        symbol = it.get("symbol")
        address = (it.get("address") or "").lower()
        chain = (it.get("chain") or "unknown").lower()

        # 1) Preferred: strict DexScreener price
        ds_price = self._dex_price_for_address(address)

        # 2) Optional fallback (price provided by scan/trending item)
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

        # 3) Safety: if both sources exist, reject on huge deviation
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

        # Already in position?
        if address in self.positions:
            return

        gas_gwei = self._gas_price_gwei()
        if gas_gwei is not None and gas_gwei > 120:
            log.info("[SKIP GAS] %s baseFee=%.1f gwei (cap=120)", symbol, gas_gwei)
            return

        notional = self.order_usd
        qty = notional / price

        stop = price * settings.TRENDING_STOP_PCT
        tp1 = price * settings.TRENDING_TP1_PCT
        tp2 = price * settings.TRENDING_TP2_PCT

        if self.paper:
            liq = float(it.get("liqUsd", 0.0) or 0.0)
            vol = float(it.get("vol24h", 0.0) or 0.0)
            tail = address[-6:] if address else "--"
            src = "DEX" if ds_price is not None else "FALLBACK"
            log.info(
                "[PAPER BUY/%s] %s $%.0f @ $%.8f (~%s %s)liq=$%.0f vol24h=$%.0f 0x%s",
                src,
                symbol,
                notional,
                price,
                f"{qty:.6f}",
                symbol,
                liq,
                vol,
                tail,
            )
            self.positions[address] = Position(symbol, chain, address, qty, price, stop, tp1, tp2, phase="OPEN")
            log.info("[PAPER EXIT PLAN] %s stop=$%.8f tp1=$%.8f tp2=$%.8f", symbol, stop, tp1, tp2)
            # hook trade (paper)
            on_trade(side="BUY", symbol=symbol, chain=chain, price=price, qty=qty, status="PAPER", address=address)
            # rebroadcast portfolio (no custom type)
            self._rebroadcast_portfolio()
            return

        log.warning("[LIVE BUY NOT IMPLEMENTED] %s (%s)", symbol, address)

    def evaluate(self, prices_by_addr: Dict[str, Optional[float]]) -> None:
        """Called every off-chain tick.

        Args:
            prices_by_addr: mapping {address_lower -> last_price}.

        Handles STOP/TP logic, updates realized PnL on each sale,
        then re-broadcasts the portfolio payload.
        """
        to_close: list[str] = []
        pnl_realized_delta = 0.0  # for logging

        for address, pos in list(self.positions.items()):
            price = prices_by_addr.get(address)
            if not price or price <= 0:
                continue

            # STOP loss (full exit)
            if price <= pos.stop and pos.phase != "CLOSED":
                sell_qty = pos.qty
                pnl = (price - pos.entry) * sell_qty
                self.realized_pnl_usd += pnl
                pnl_realized_delta += pnl
                log.info(
                    "[PAPER SELL STOP] %s @ $%.8f (entry $%.8f) qty=%.6f realized=$%.2f",
                    pos.symbol,
                    price,
                    pos.entry,
                    sell_qty,
                    pnl,
                )
                on_trade(
                    side="SELL",
                    symbol=pos.symbol,
                    chain=pos.chain,
                    price=price,
                    qty=sell_qty,
                    status="PAPER",
                    address=address,
                )
                to_close.append(address)
                continue

            # TP1 → take half and move stop to break-even
            if pos.phase == "OPEN" and price >= pos.tp1:
                sell_qty = pos.qty * 0.5
                pnl = (price - pos.entry) * sell_qty
                self.realized_pnl_usd += pnl
                pnl_realized_delta += pnl

                pos.qty -= sell_qty
                pos.phase = "TP1"
                pos.stop = pos.entry  # move to break-even

                log.info(
                    "[PAPER TP1] %s @ $%.8f realized=$%.2f sold=%.6f left=%.6f (BE stop=$%.8f)",
                    pos.symbol,
                    price,
                    pnl,
                    sell_qty,
                    pos.qty,
                    pos.stop,
                )
                on_trade(
                    side="SELL",
                    symbol=pos.symbol,
                    chain=pos.chain,
                    price=price,
                    qty=sell_qty,
                    status="PAPER",
                    address=address,
                )
                continue

            # TP2 → close the remainder (full exit)
            if pos.phase in {"OPEN", "TP1"} and price >= pos.tp2:
                sell_qty = pos.qty
                pnl = (price - pos.entry) * sell_qty
                self.realized_pnl_usd += pnl
                pnl_realized_delta += pnl

                log.info(
                    "[PAPER TP2] %s @ $%.8f close qty=%.6f realized=$%.2f",
                    pos.symbol,
                    price,
                    sell_qty,
                    pnl,
                )
                on_trade(
                    side="SELL",
                    symbol=pos.symbol,
                    chain=pos.chain,
                    price=price,
                    qty=sell_qty,
                    status="PAPER",
                    address=address,
                )
                to_close.append(address)
                continue

            # After TP1, if we fall back to stop (break-even), close
            if pos.phase == "TP1" and price <= pos.stop:
                sell_qty = pos.qty
                pnl = (price - pos.entry) * sell_qty
                self.realized_pnl_usd += pnl
                pnl_realized_delta += pnl

                log.info(
                    "[PAPER EXIT @BE] %s @ $%.8f qty=%.6f realized=$%.2f",
                    pos.symbol,
                    price,
                    sell_qty,
                    pnl,
                )
                on_trade(
                    side="SELL",
                    symbol=pos.symbol,
                    chain=pos.chain,
                    price=price,
                    qty=sell_qty,
                    status="PAPER",
                    address=address,
                )
                to_close.append(address)
                continue

        # Mark CLOSED and remove from table
        for address in to_close:
            if address in self.positions:
                self.positions[address].phase = "CLOSED"
                del self.positions[address]

        # Re-broadcast after sales/exits
        if self.positions or pnl_realized_delta != 0.0:
            self._rebroadcast_portfolio()
