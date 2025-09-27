from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple, Set

from src.configuration.config import settings
from src.core.trader import Trader
from src.core.trending_utils import (
    filter_strict,
    soft_fill,
    apply_quality_filter,
    recently_traded,
    preload_best_prices,
)
from src.integrations.dexscreener.dexscreener_client import fetch_trending_candidates
from src.logging.logger import get_logger
from src.persistence import crud
from src.persistence.db import SessionLocal

log = get_logger(__name__)


def _as_fraction(value: float | int) -> float:
    """Convert a percent-like number to a fraction (e.g., 5 → 0.05)."""
    try:
        number = float(value)
        return number / 100.0 if number > 1 else number
    except Exception:
        return 0.0


class TrendingJob:
    """Thin orchestrator: fetch → filter → quality → guards → buy."""

    def __init__(self, w3: Optional["Web3"] = None) -> None:
        self.interval: str = settings.TREND_INTERVAL.lower()
        self.page_size: int = settings.TREND_PAGE_SIZE
        self.max_results: int = settings.TREND_MAX_RESULTS

        self.min_volume_usd: float = settings.TREND_MIN_VOL_USD
        self.min_liquidity_usd: float = settings.TREND_MIN_LIQ_USD
        self.min_pct_5m: float = _as_fraction(settings.TREND_MIN_PCT_5M)
        self.min_pct_1h: float = _as_fraction(settings.TREND_MIN_PCT_1H)
        self.min_pct_24h: float = _as_fraction(settings.TREND_MIN_PCT_24H)

        self.exclude_stables: bool = settings.TREND_EXCLUDE_STABLES
        self.exclude_majors: bool = settings.TREND_EXCLUDE_MAJORS
        self.soft_fill_min: int = settings.TREND_SOFT_FILL_MIN
        self.soft_fill_sort: str = settings.TREND_SOFT_FILL_SORT

        self.trader = Trader()
        self.w3 = w3

    def _free_cash(self) -> float:
        """Return the current free cash from the latest portfolio snapshot."""
        with SessionLocal() as db:
            snapshot = crud.get_latest_portfolio(db, create_if_missing=True)
            return float(snapshot.cash or 0.0) if snapshot else 0.0

    def _open_sets(self) -> Tuple[Set[str], Set[str]]:
        """Return sets of currently open symbols and addresses."""
        with SessionLocal() as db:
            positions = crud.get_open_positions(db)
        symbols = {(p.symbol or "").upper() for p in positions if p.symbol}
        addresses = {(p.address or "").lower() for p in positions if p.address}
        return symbols, addresses

    def _per_buy_budget(self, free_cash: float) -> float:
        """Compute the per-buy budget using either fraction or absolute USD."""
        fraction = float(settings.TREND_PER_BUY_FRACTION)
        return max(1.0, free_cash * fraction) if fraction > 0 else float(settings.TREND_PER_BUY_USD)

    def _fetch(self) -> List[Dict[str, Any]]:
        """Fetch trending candidates from Dexscreener."""
        try:
            return asyncio.run(
                fetch_trending_candidates(
                    self.interval,
                    page_size=self.page_size
                )
            )
        except Exception as exc:
            log.warning("Dexscreener trending fetch failed: %s", exc)
            return []

    def run_once(self) -> None:
        """Run one full trending cycle: fetch → filter → rank → execute buys."""
        if not settings.TREND_ENABLE:
            log.info("Trending disabled")
            return

        rows = self._fetch()
        if not rows:
            log.info("Trending: 0 candidates")
            return

        kept, rejected_counts = filter_strict(
            rows,
            interval=self.interval,
            min_vol_usd=self.min_volume_usd,
            min_liq_usd=self.min_liquidity_usd,
            th5=self.min_pct_5m,
            th1=self.min_pct_1h,
            th24=self.min_pct_24h,
            exclude_stables=self.exclude_stables,
            exclude_majors=self.exclude_majors,
            max_results=self.max_results,
        )

        need_minimum = max(self.soft_fill_min, len(kept))
        kept = soft_fill(
            rows,
            kept,
            need_min=need_minimum,
            min_vol_usd=self.min_volume_usd,
            min_liq_usd=self.min_liquidity_usd,
            sort_key=self.soft_fill_sort,
        )

        kept = apply_quality_filter(kept)
        if not kept:
            log.info("Quality kept=0 (rejected=%s)", rejected_counts)
            return

        sort_key = self.soft_fill_sort if self.soft_fill_sort in {"vol24h", "liqUsd"} else "vol24h"
        kept.sort(key=lambda item: float(item.get(sort_key) or 0.0), reverse=True)
        kept = kept[: self.max_results]

        open_symbols, open_addresses = self._open_sets()
        candidates = [
            item
            for item in kept
            if (item.get("symbol", "").upper() not in open_symbols)
               and ((item.get("address") or "").lower() not in open_addresses)
        ]
        if not candidates:
            log.info("No buys: already in open positions")
            return

        address_list = [(item.get("address") or "").lower() for item in candidates if item.get("address")]
        best_price_by_address = preload_best_prices(address_list)
        cooldown_minutes = int(settings.DEXSCREENER_REBUY_COOLDOWN_MIN)

        if self.trader is None:
            log.warning("Trader unavailable; skipping execution")
            return

        free_cash = self._free_cash()
        per_buy_usd = self._per_buy_budget(free_cash)
        min_free_cash_usd = float(settings.TREND_MIN_FREE_CASH_USD)
        max_buys_per_run = int(settings.TREND_MAX_BUYS_PER_RUN)
        require_dex_price = bool(settings.TREND_REQUIRE_DEX_PRICE)
        max_price_deviation = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)

        simulated_cash = free_cash
        executed_buys = 0
        for item in candidates:
            if executed_buys >= max_buys_per_run:
                break

            address = (item.get("address") or "").lower()
            if recently_traded(address, minutes=cooldown_minutes):
                continue

            dex_price = best_price_by_address.get(address)
            if require_dex_price and (dex_price is None or dex_price <= 0):
                continue

            external_price: Optional[float] = None
            try:
                raw_price = float(item.get("price") or 0.0)
                external_price = raw_price if raw_price > 0 else None
            except Exception:
                external_price = None

            if dex_price and external_price:
                low, high = sorted([dex_price, external_price])
                if low > 0 and (high / low) > max_price_deviation:
                    continue

            if simulated_cash < per_buy_usd or (simulated_cash - per_buy_usd) < min_free_cash_usd:
                break

            payload = dict(item)
            if dex_price is not None:
                payload["dex_price"] = dex_price

            try:
                self.trader.buy(payload)  # type: ignore[attr-defined]
                executed_buys += 1
                simulated_cash -= per_buy_usd
            except Exception as exc:
                log.warning("BUY failed for %s: %s", item.get("symbol"), exc)

        log.info(
            "Executed buys=%d (free_cash_start=%.2f per_buy=%.2f)",
            executed_buys,
            free_cash,
            per_buy_usd,
        )

    def run(self) -> None:
        """Compatibility alias."""
        self.run_once()
