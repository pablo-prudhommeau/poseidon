# src/execution/trader.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional

import httpx
from web3 import Web3
from src.configuration.config import settings
from src.core.trader_hooks import on_trade
from src.logging.logger import get_logger

log = get_logger(__name__)

@dataclass
class Position:
    symbol: str
    address: str
    qty: float
    entry: float
    stop: float
    tp1: float
    tp2: float
    phase: str = "OPEN"  # OPEN -> TP1 -> CLOSED

class Trader:
    """
    Trader PAPER par défaut.
    - buy(): ouvre une position simulée
    - evaluate(prices): gère stop/tp et sort avec logs
    """

    def __init__(self, w3: Optional[Web3] = None):
        self.w3 = w3
        self.paper = settings.PAPER_MODE
        self.order_usd = 250.0      # taille d'ordre simulée
        self.slippage_bps = 75      # 0.75%
        self.positions: Dict[str, Position] = {}  # key = address

    def _dex_price_for_address(self, address: str) -> Optional[float]:
        """
        Prix DexScreener strict: on ne retient que les paires où le token est BASE.
        Si aucune paire 'baseToken.address == address', on renvoie None (on NE fait PAS d'inversion).
        """
        if not address:
            return None
        base = getattr(settings, "DEXSCREENER_BASE_URL", "https://api.dexscreener.com").rstrip("/")
        url = f"{base}/latest/dex/tokens/{address.lower()}"
        try:
            r = httpx.get(url, timeout=8.0)
            r.raise_for_status()
            data = r.json() or {}
            pairs = data.get("pairs", []) or []

            # garder seulement les paires où le token EST le baseToken
            addr_l = address.lower()
            base_pairs = []
            for p in pairs:
                bt = (p.get("baseToken") or {})
                if (bt.get("address") or "").lower() == addr_l:
                    base_pairs.append(p)

            if not base_pairs:
                # rien de fiable -> pas d'achat
                log.warning("DexScreener: no BASE pair for %s, skipping price.", address)
                return None

            # score liquidité/volume
            def score(p):
                liq = float((p.get("liquidity") or {}).get("usd") or 0.0)
                vol = float((p.get("volume") or {}).get("h24") or 0.0)
                return (liq, vol)

            best = max(base_pairs, key=score)
            price = best.get("priceUsd")
            price = float(price) if price is not None else None
            return price if (price is not None and price > 0) else None
        except Exception as e:
            log.debug("DexScreener price fetch failed for %s: %s", address, e)
            return None

    # --------- utils ----------
    def _gas_price_gwei(self) -> Optional[float]:
        try:
            if not self.w3:
                return None
            return self.w3.eth.gas_price / 1e9
        except Exception:
            return None

    # --------- actions ----------
    def buy(self, it: Dict[str, Any]) -> None:
        sym  = it.get("symbol")
        addr = (it.get("address") or "").lower()

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

        # --- reste inchangé ---
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
            self.positions[addr] = Position(sym, addr, qty, price, stop, tp1, tp2, "OPEN")
            log.info("[PAPER EXIT PLAN] %s stop=$%.8f tp1=$%.8f tp2=$%.8f", sym, stop, tp1, tp2)
            on_trade(side="BUY", symbol=sym, price=price, qty=qty, status="PAPER", address=addr)
            return

        log.warning("[LIVE BUY NOT IMPLEMENTED] %s (%s)", sym, addr)

    def evaluate(self, prices_by_addr: Dict[str, Optional[float]]) -> None:
        """
        Appelée à chaque tick offchain (après le scan CMC).
        prices_by_addr: {address -> last_price}
        """
        to_close = []

        for addr, pos in self.positions.items():
            price = prices_by_addr.get(addr)
            if not price or price <= 0:
                continue

            # STOP loss
            if price <= pos.stop and pos.phase != "CLOSED":
                log.info("[PAPER SELL STOP] %s @ $%.8f (entry $%.8f) qty=%.6f", pos.symbol, price, pos.entry, pos.qty)
                to_close.append(addr)
                continue

            # TP1 -> on prend la moitié et on remonte le stop à break-even
            if pos.phase == "OPEN" and price >= pos.tp1:
                sell_qty = pos.qty * 0.5
                pos.qty -= sell_qty
                pos.phase = "TP1"
                pos.stop = pos.entry  # remonte à break-even
                log.info("[PAPER TP1] %s @ $%.8f (BE stop=$%.8f) realized=%.6f", pos.symbol, price, pos.stop, sell_qty)
                continue

            # TP2 -> on sort le reste
            if pos.phase in {"OPEN", "TP1"} and price >= pos.tp2:
                log.info("[PAPER TP2] %s @ $%.8f (close) qty=%.6f", pos.symbol, price, pos.qty)
                to_close.append(addr)
                continue

            # Après TP1, si on retombe sur le stop (break-even), on ferme
            if pos.phase == "TP1" and price <= pos.stop:
                log.info("[PAPER EXIT @BE] %s @ $%.8f qty=%.6f", pos.symbol, price, pos.qty)
                to_close.append(addr)
                continue

        for addr in to_close:
            self.positions[addr].phase = "CLOSED"
            del self.positions[addr]
