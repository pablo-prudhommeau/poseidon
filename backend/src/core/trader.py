# src/execution/trader.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional
import asyncio

from web3 import Web3
from src.configuration.config import settings
from src.integrations.dexscreener_client import fetch_prices_by_addresses
from src.core.trader_hooks import on_trade  # rebroadcast_portfolio est importé tardivement
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
    """
    Trader PAPER par défaut.
    - buy(): ouvre une position simulée
    - evaluate(prices): gère stop/tp et sort avec logs
    - rebroadcast automatiquement le portfolio (payload 'portfolio') après buy/sell/exit
    """

    def __init__(self, w3: Optional[Web3] = None):
        self.w3 = w3
        self.paper = settings.PAPER_MODE
        self.order_usd = 250.0      # taille d'ordre simulée
        self.slippage_bps = 75      # 0.75%
        self.positions: Dict[str, Position] = {}  # key = address
        self.realized_pnl_usd: float = 0.0        # suivi interne (utile aux logs)

    # ------------- prix -------------
    def _dex_price_for_address(self, address: str) -> Optional[float]:
        if not address:
            return None
        try:
            # Si on est déjà DANS une boucle asyncio (FastAPI task, etc.), on évite asyncio.run()
            try:
                asyncio.get_running_loop()
                # Dans ce cas, on ne bloque pas : on laisse le fallback prendre le relais
                log.debug("Running loop detected, skipping sync DEX price for %s (will use fallback if any)", address)
                return None
            except RuntimeError:
                pass  # pas de loop -> on peut faire un appel bloquant

            m = asyncio.run(
                fetch_prices_by_addresses([address], chain_id=getattr(settings, "TREND_CHAIN_ID", None))
            )
            price = m.get(address.lower())
            return float(price) if price and price > 0 else None
        except Exception as e:
            log.warning("DexScreener price fetch failed for %s: %s", address, e)
            return None

    # ------------- utils -------------
    def _gas_price_gwei(self) -> Optional[float]:
        try:
            if not self.w3:
                return None
            return self.w3.eth.gas_price / 1e9
        except Exception:
            return None

    def _rebroadcast_portfolio(self) -> None:
        """
        Recalcule & rebroadcast le portfolio (payload 'portfolio') à tous les clients.
        Aucun changement de protocole WS côté front.
        """
        try:
            # import tardif pour éviter les cycles
            from src.core.trader_hooks import rebroadcast_portfolio  # async
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(rebroadcast_portfolio())
            except RuntimeError:
                asyncio.run(rebroadcast_portfolio())
        except Exception as e:
            log.debug("rebroadcast_portfolio failed: %s", e)

    # ------------- actions -------------
    def buy(self, it: Dict[str, Any]) -> None:
        sym  = it.get("symbol")
        addr = (it.get("address") or "").lower()
        chain = (it.get("chain") or "unknown").lower()

        # 1) prix DexScreener strict (préféré)
        ds_price = self._dex_price_for_address(addr)

        # 2) fallback éventuel (prix du scan/trending si fourni)
        fallback = None
        try:
            v = it.get("price")
            if v is not None:
                v = float(v)
                fallback = v if v > 0 else None
        except Exception:
            fallback = None

        price = ds_price or fallback
        if not addr or price is None:
            log.debug("[BUY SKIP] %s addr/price invalid (addr=%s price=%s)", sym, addr, price)
            return

        # 3) GARDE-FOU: si on a les deux, refuse si l’écart est énorme
        max_mult = float(getattr(settings, "MAX_PRICE_DEVIATION_MULTIPLIER", 3.0))
        if ds_price is not None and fallback is not None:
            lo, hi = sorted([ds_price, fallback])
            if hi > 0 and (hi / lo) > max_mult:
                log.warning("[BUY SKIP] %s price mismatch DEX %.6f vs ext %.6f (>x%.1f)",
                            sym, ds_price, fallback, max_mult)
                return

        # déjà en position ?
        if addr in self.positions:
            return

        gas_gwei = self._gas_price_gwei()
        if gas_gwei is not None and gas_gwei > 120:
            log.info("[SKIP GAS] %s baseFee=%.1f gwei (cap=120)", sym, gas_gwei)
            return

        notional = self.order_usd
        qty = notional / price

        stop = price * settings.STOP_PCT
        tp1  = price * settings.TP1_PCT
        tp2  = price * settings.TP2_PCT

        if self.paper:
            liq = float(it.get("liqUsd", 0.0) or 0.0)
            vol = float(it.get("vol24h", 0.0) or 0.0)
            tail = addr[-6:] if addr else "--"
            src = "DEX" if ds_price is not None else "FALLBACK"
            log.info("[PAPER BUY/%s] %s $%.0f @ $%.8f (~%s %s)liq=$%.0f vol24h=$%.0f 0x%s",
                     src, sym, notional, price, f"{qty:.6f}", sym, liq, vol, tail)
            self.positions[addr] = Position(sym, chain, addr, qty, price, stop, tp1, tp2, phase="OPEN")
            log.info("[PAPER EXIT PLAN] %s stop=$%.8f tp1=$%.8f tp2=$%.8f", sym, stop, tp1, tp2)
            # hook trade (paper)
            on_trade(side="BUY", symbol=sym, chain=chain, price=price, qty=qty, status="PAPER", address=addr)
            # rebroadcast du portfolio (pas de type custom)
            self._rebroadcast_portfolio()
            return

        log.warning("[LIVE BUY NOT IMPLEMENTED] %s (%s)", sym, addr)

    def evaluate(self, prices_by_addr: Dict[str, Optional[float]]) -> None:
        """
        Appelée à chaque tick offchain.
        prices_by_addr: {address -> last_price}
        Gère STOP/TP et met à jour le PnL réalisé à chaque vente (partielle ou totale).
        Puis rebroadcast le portfolio.
        """
        to_close = []
        pnl_realized_delta = 0.0  # pour log

        for addr, pos in list(self.positions.items()):
            price = prices_by_addr.get(addr)
            if not price or price <= 0:
                continue

            # STOP loss (vente totale)
            if price <= pos.stop and pos.phase != "CLOSED":
                sell_qty = pos.qty
                pnl = (price - pos.entry) * sell_qty
                self.realized_pnl_usd += pnl
                pnl_realized_delta += pnl
                log.info("[PAPER SELL STOP] %s @ $%.8f (entry $%.8f) qty=%.6f realized=$%.2f",
                         pos.symbol, price, pos.entry, sell_qty, pnl)
                on_trade(side="SELL", symbol=pos.symbol, chain=pos.chain, price=price, qty=sell_qty, status="PAPER", address=addr)
                to_close.append(addr)
                continue

            # TP1 -> on prend la moitié et on remonte le stop à break-even
            if pos.phase == "OPEN" and price >= pos.tp1:
                sell_qty = pos.qty * 0.5
                pnl = (price - pos.entry) * sell_qty
                self.realized_pnl_usd += pnl
                pnl_realized_delta += pnl

                pos.qty -= sell_qty
                pos.phase = "TP1"
                pos.stop = pos.entry  # remonte à break-even

                log.info("[PAPER TP1] %s @ $%.8f realized=$%.2f sold=%.6f left=%.6f (BE stop=$%.8f)",
                         pos.symbol, price, pnl, sell_qty, pos.qty, pos.stop)
                on_trade(side="SELL", symbol=pos.symbol, chain=pos.chain, price=price, qty=sell_qty, status="PAPER", address=addr)
                continue

            # TP2 -> on sort le reste (vente totale du solde)
            if pos.phase in {"OPEN", "TP1"} and price >= pos.tp2:
                sell_qty = pos.qty
                pnl = (price - pos.entry) * sell_qty
                self.realized_pnl_usd += pnl
                pnl_realized_delta += pnl

                log.info("[PAPER TP2] %s @ $%.8f close qty=%.6f realized=$%.2f",
                         pos.symbol, price, sell_qty, pnl)
                on_trade(side="SELL", symbol=pos.symbol, chain=pos.chain, price=price, qty=sell_qty, status="PAPER", address=addr)
                to_close.append(addr)
                continue

            # Après TP1, si on retombe sur le stop (break-even), on ferme (réalisé ≈ 0)
            if pos.phase == "TP1" and price <= pos.stop:
                sell_qty = pos.qty
                pnl = (price - pos.entry) * sell_qty
                self.realized_pnl_usd += pnl
                pnl_realized_delta += pnl

                log.info("[PAPER EXIT @BE] %s @ $%.8f qty=%.6f realized=$%.2f",
                         pos.symbol, price, sell_qty, pnl)
                on_trade(side="SELL", symbol=pos.symbol, chain=pos.chain, price=price, qty=sell_qty, status="PAPER", address=addr)
                to_close.append(addr)
                continue

        for addr in to_close:
            # marque CLOSED puis retire de la table
            if addr in self.positions:
                self.positions[addr].phase = "CLOSED"
                del self.positions[addr]

        # rebroadcast du portfolio après ventes/fermetures
        if self.positions or pnl_realized_delta != 0.0:
            self._rebroadcast_portfolio()
