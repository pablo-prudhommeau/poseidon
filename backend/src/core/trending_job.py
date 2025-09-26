from __future__ import annotations
import asyncio
from typing import Any, Dict, List, Optional

from src.configuration.config import settings
from src.logging.logger import get_logger
from src.persistence.db import SessionLocal
from src.persistence import crud

from src.integrations.dexscreener_client import fetch_trending_candidates
from src.core.trending_utils import (
    filter_strict, softfill, apply_quality_filter,
    recently_traded, preload_best_prices
)

log = get_logger(__name__)

try:
    from src.core.trader import Trader
except Exception:
    Trader = None


def _as_frac(x: float | int) -> float:
    try:
        v = float(x)
        return v / 100.0 if v > 1 else v
    except Exception:
        return 0.0


class TrendingJob:
    """Thin orchestrator: fetch → filter → quality → guard → buy."""

    def __init__(self, w3: Optional["Web3"] = None) -> None:
        self.interval = (settings.TREND_INTERVAL or "1h").lower()
        self.page_size = int(getattr(settings, "TREND_PAGE_SIZE", 100))
        self.max_results = int(getattr(settings, "TREND_MAX_RESULTS", 100))
        self.chain = (getattr(settings, "TREND_CHAIN", "ethereum") or "ethereum").lower()
        self.chain_id = getattr(settings, "TREND_CHAIN_ID", "1")

        self.min_vol = float(getattr(settings, "TREND_MIN_VOL_USD", 100_000))
        self.min_liq = float(getattr(settings, "TREND_MIN_LIQ_USD", 50_000))
        self.th5 = _as_frac(getattr(settings, "TREND_MIN_PCT_5M", 2.0))
        self.th1 = _as_frac(getattr(settings, "TREND_MIN_PCT_1H", 5.0))
        self.th24 = _as_frac(getattr(settings, "TREND_MIN_PCT_24H", 10.0))

        self.exclude_stables = bool(getattr(settings, "TREND_EXCLUDE_STABLES", True))
        self.exclude_majors = bool(getattr(settings, "TREND_EXCLUDE_MAJORS", True))
        self.softfill_min = int(getattr(settings, "TREND_SOFTFILL_MIN", 6))
        self.softfill_sort = getattr(settings, "TREND_SOFTFILL_SORT", "vol24h")

        self.trader = Trader() if Trader else None
        self.w3 = w3  # compat

    # ---- portfolio helpers
    def _free_cash(self) -> float:
        with SessionLocal() as db:
            snap = crud.get_latest_portfolio(db, create_if_missing=True)
            return float(snap.cash or 0.0) if snap else 0.0

    def _open_sets(self) -> tuple[set[str], set[str]]:
        with SessionLocal() as db:
            pos = crud.get_open_positions(db)
        syms = {(p.symbol or "").upper() for p in pos if p.symbol}
        addrs = {(p.address or "").lower() for p in pos if p.address}
        return syms, addrs

    def _per_buy_budget(self, free_cash: float) -> float:
        frac = float(getattr(settings, "TREND_PER_BUY_FRACTION", 0.0))
        return max(1.0, free_cash * frac) if frac > 0 else float(getattr(settings, "TREND_PER_BUY_USD", 200.0))

    # ---- fetch
    def _fetch(self) -> List[Dict[str, Any]]:
        try:
            return asyncio.run(
                fetch_trending_candidates(self.interval, page_size=self.page_size, chain=self.chain, chain_id=self.chain_id)
            )
        except Exception as e:
            log.warning("Dexscreener trending fetch failed: %s", e)
            return []

    # ---- main
    def run_once(self) -> None:
        if not getattr(settings, "TREND_ENABLE", True):
            log.info("Trending disabled");
            return

        rows = self._fetch()
        if not rows:
            log.info("Trending: 0 candidates");
            return

        kept, rej = filter_strict(
            rows,
            interval=self.interval,
            min_vol_usd=self.min_vol, min_liq_usd=self.min_liq,
            th5=self.th5, th1=self.th1, th24=self.th24,
            exclude_stables=self.exclude_stables, exclude_majors=self.exclude_majors,
            max_results=self.max_results,
        )

        need_min = max(self.softfill_min, len(kept))
        kept = softfill(rows, kept, need_min=need_min, min_vol_usd=self.min_vol, min_liq_usd=self.min_liq, sort_key=self.softfill_sort)

        kept = apply_quality_filter(kept)
        if not kept:
            log.info("Quality kept=0 (rej=%s)", rej);
            return

        key = self.softfill_sort if self.softfill_sort in {"vol24h", "liqUsd"} else "vol24h"
        kept.sort(key=lambda x: float(x.get(key) or 0.0), reverse=True)
        kept = kept[: self.max_results]

        open_syms, open_addrs = self._open_sets()
        candidates = [it for it in kept if (it.get("symbol", "").upper() not in open_syms and (it.get("address") or "").lower() not in open_addrs)]
        if not candidates:
            log.info("No buys: already in open positions");
            return

        addr_list = [(it.get("address") or "").lower() for it in candidates if it.get("address")]
        price_map = preload_best_prices(addr_list)
        cooldown_min = int(getattr(settings, "DS_REBUY_COOLDOWN_MIN", 45))

        if self.trader is None:
            log.warning("Trader unavailable; skipping execution");
            return

        free_cash = self._free_cash()
        per_buy = self._per_buy_budget(free_cash)
        min_free = float(getattr(settings, "TREND_MIN_FREE_CASH_USD", 50.0))
        max_buys = int(getattr(settings, "TREND_MAX_BUYS_PER_RUN", 5))
        require_dex = bool(getattr(settings, "TREND_REQUIRE_DEX_PRICE", True))
        max_mult = float(getattr(settings, "MAX_PRICE_DEVIATION_MULTIPLIER", 3.0))

        sim_cash, buys = free_cash, 0
        for it in candidates:
            if buys >= max_buys: break
            addr = (it.get("address") or "").lower()
            if recently_traded(addr, minutes=cooldown_min): continue

            ds_price = price_map.get(addr)
            if require_dex and (ds_price is None or ds_price <= 0): continue

            ext_price = None
            try:
                p = float(it.get("price") or 0.0)
                ext_price = p if p > 0 else None
            except Exception:
                ext_price = None
            if ds_price and ext_price:
                lo, hi = sorted([ds_price, ext_price])
                if lo > 0 and (hi / lo) > max_mult: continue

            if sim_cash < per_buy or (sim_cash - per_buy) < min_free: break

            payload = dict(it)
            if ds_price is not None:
                payload["dex_price"] = ds_price
            try:
                self.trader.buy(payload)  # type: ignore[attr-defined]
                buys += 1
                sim_cash -= per_buy
            except Exception as e:
                log.warning("BUY failed for %s: %s", it.get("symbol"), e)

        log.info("Executed buys=%d (free_cash_start=%.2f per_buy=%.2f)", buys, free_cash, per_buy)

    # Backward compat if something calls run()
    def run(self) -> None:
        self.run_once()
