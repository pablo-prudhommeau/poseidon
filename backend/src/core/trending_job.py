from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple, Set

from src.configuration.config import settings
from src.core.trader import Trader
from src.core.trending_quality import apply_quality_filter
from src.core.trending_utils import (
    filter_strict,
    soft_fill,
    recently_traded,
    preload_best_prices,
)
from src.integrations.dexscreener_client import fetch_trending_candidates
from src.logging.logger import get_logger
from src.persistence.dao.portfolio_snapshots import get_latest_portfolio
from src.persistence.dao.positions import get_open_positions
from src.persistence.db import _session

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

    def __init__(self) -> None:
        self.interval: str = settings.TREND_INTERVAL.lower()
        self.page_size: int = settings.TREND_PAGE_SIZE
        self.max_results: int = settings.TREND_MAX_RESULTS

        self.min_volume_usd: float = settings.TREND_MIN_VOL_USD
        self.min_liquidity_usd: float = settings.TREND_MIN_LIQ_USD
        self.min_pct_5m: float = _as_fraction(settings.TREND_MIN_PCT_5M)
        self.min_pct_1h: float = _as_fraction(settings.TREND_MIN_PCT_1H)
        self.min_pct_24h: float = _as_fraction(settings.TREND_MIN_PCT_24H)

        self.soft_fill_min: int = settings.TREND_SOFT_FILL_MIN
        self.soft_fill_sort: str = settings.TREND_SOFT_FILL_SORT

        self.trader = Trader()

    def _free_cash(self) -> float:
        """Return the current free cash from the latest portfolio snapshot."""
        with _session() as db:
            snapshot = get_latest_portfolio(db, create_if_missing=True)
            return float(snapshot.cash or 0.0) if snapshot else 0.0

    def _open_sets(self) -> Tuple[Set[str], Set[str]]:
        """Return sets of currently open symbols and addresses."""
        with _session() as db:
            positions = get_open_positions(db)
        symbols = {(p.symbol or "").upper() for p in positions if p.symbol}
        addresses = {(p.address or "").lower() for p in positions if p.address}
        return symbols, addresses

    def _per_buy_budget(self, free_cash: float) -> float:
        """Compute the per-buy budget using either fraction or absolute USD."""
        fraction = float(settings.TREND_PER_BUY_FRACTION)
        return max(1.0, free_cash * fraction)

    def _fetch(self) -> List[Dict[str, Any]]:
        """Fetch trending candidates from Dexscreener."""
        try:
            return asyncio.run(fetch_trending_candidates(page_size=self.page_size))
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
            return

        address_list = [(item.get("address") or "").lower() for item in candidates if item.get("address")]
        best_price_by_address = preload_best_prices(address_list)
        cooldown_minutes = int(settings.DEXSCREENER_REBUY_COOLDOWN_MIN)

        free_cash = self._free_cash()
        per_buy_usd = self._per_buy_budget(free_cash)
        min_free_cash_usd = float(settings.TREND_MIN_FREE_CASH_USD)
        max_buys_per_run = int(settings.TREND_MAX_BUYS_PER_RUN)
        max_price_deviation = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)

        simulated_cash = free_cash
        executed_buys = 0
        for item in candidates:
            if executed_buys >= max_buys_per_run:
                log.debug("Max buys per run reached (%d)", max_buys_per_run)
                break

            address = (item.get("address") or "").lower()
            if recently_traded(address, minutes=cooldown_minutes):
                log.debug("Skipping recently traded %s", item.get("symbol"))
                continue

            dex_price = best_price_by_address.get(address)
            if dex_price is None or dex_price <= 0:
                log.debug("Skipping %s without valid DEX price", item.get("symbol"))
                continue

            price = float(item.get("price") or 0.0)
            if dex_price and price:
                low, high = sorted([dex_price, price])
                if low > 0 and (high / low) > max_price_deviation:
                    continue

            if simulated_cash < order_notional or (simulated_cash - order_notional) < min_free_cash_usd:
                break

            payload = dict(item)
            payload["dex_price"] = dex_price
            payload["order_notional"] = order_notional

            try:
                self.trader.buy(payload)
                executed_buys += 1
                simulated_cash -= order_notional
            except Exception as exc:
                log.warning("BUY failed for %s: %s", item.get("symbol"), exc)

    def run(self) -> None:
        """Compatibility alias."""
        self.run_once()
