from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple, Set, Coroutine

from src.ai.chart_signal_provider import ChartAiSignalProvider
from src.configuration.config import settings
from src.core.risk_manager import AdaptiveRiskManager
from src.core.scoring import ScoringEngine
from src.core.trader import Trader
from src.core.trending_quality import apply_quality_filter
from src.core.trending_utils import (
    filter_strict,
    soft_fill,
    recently_traded,
    preload_best_prices,
    _age_hours,
)
from src.logging.logger import get_logger
from src.persistence.dao.portfolio_snapshots import get_latest_portfolio
from src.persistence.dao.positions import get_open_positions
from src.persistence.db import _session

log = get_logger(__name__)


def _run_coro_in_fresh_loop(coro: Coroutine[Any, Any, Any], *, debug_label: str = "") -> Any:
    """
    Run an async coroutine in an isolated event loop.
    Falls back to a fresh loop when the debugger's asyncio patch causes
    'Event loop is closed' with asyncio.run(...).
    """
    try:
        return asyncio.run(coro)
    except RuntimeError as exc:
        if "Event loop is closed" not in str(exc):
            raise
        log.debug("TrendingJob: closed loop detected (%s); using a fresh event loop.", debug_label or "coro")
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(coro)
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            return result
        finally:
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass
            loop.close()


def _fetch_trending_candidates_sync(*args, **kwargs) -> List[Dict[str, Any]]:
    """Synchronous wrapper around the async DexScreener trending fetch."""
    # Local import to avoid circular dependencies
    from src.integrations.dexscreener_client import fetch_trending_candidates
    return _run_coro_in_fresh_loop(
        fetch_trending_candidates(*args, **kwargs),
        debug_label="fetch_trending_candidates",
    )


def _normalize_lookup_address(address: str) -> str:
    """
    Normalize an address for internal lookups:
    - EVM → lowercase
    - SOL → keep case
    """
    if not address:
        return ""
    return address.lower() if address.startswith("0x") else address


class TrendingJob:
    """
    Orchestrator pipeline:

      fetch → hard filter → quality filter → de-dup (open positions) → preload prices
      → base scoring (0..100) → gate checks (recently traded, risk, prices, deviation)
      → Chart AI on survivors top-K → final score → risk & sizing → buy
    """

    def __init__(self) -> None:
        # Baseline selection knobs
        self.interval: str = settings.TREND_INTERVAL.lower()
        self.page_size: int = settings.TREND_PAGE_SIZE
        self.max_results: int = settings.TREND_MAX_RESULTS

        self.min_volume_usd: float = settings.TREND_MIN_VOL_USD
        self.min_liquidity_usd: float = settings.TREND_MIN_LIQ_USD
        self.min_pct_5m = float(settings.TREND_MIN_PCT_5M)
        self.min_pct_1h = float(settings.TREND_MIN_PCT_1H)
        self.min_pct_24h = float(settings.TREND_MIN_PCT_24H)

        self.soft_fill_min: int = settings.TREND_SOFT_FILL_MIN
        self.soft_fill_sort: str = settings.TREND_SOFT_FILL_SORT

        # Execution and risk
        self.trader = Trader()
        self.risk_manager = AdaptiveRiskManager()

        # AI
        self.chart_ai = ChartAiSignalProvider()
        self.chart_ai_top_k: int = int(getattr(settings, "TOP_K_CANDIDATES_FOR_CHART_AI"))
        self.chart_ai_timeframe: int = int(getattr(settings, "CHART_AI_TIMEFRAME"))
        self.chart_ai_lookback: int = int(getattr(settings, "CHART_AI_LOOKBACK_MINUTES"))

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
        """Compute the per-buy budget using a fraction of free cash."""
        fraction = float(settings.TREND_PER_BUY_FRACTION)
        return max(1.0, free_cash * fraction)

    def _compute_base_scores(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Compute base scores (0..100) for candidates — no Chart AI here.
        Populates `base_score` and initializes `final_score` with the same value.
        """
        if not candidates:
            return []
        engine = ScoringEngine().fit(candidates)
        for item in candidates:
            item["base_score"] = float(engine.base_score(item))
            item["final_score"] = item["base_score"]
        return candidates

    def run_once(self) -> None:
        """Run one full trending cycle."""
        if not settings.TREND_ENABLE:
            log.info("Trending disabled")
            return

        # 1) Fetch candidates from DexScreener
        try:
            rows = _fetch_trending_candidates_sync()
        except Exception as exc:
            log.warning("DexScreener trending fetch failed: %s", exc)
            rows = []
        if not rows:
            log.info("Trending: 0 candidates")
            return

        # 2) Hard filters
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
        log.info("[FILTER] kept=%d rejected=%s", len(kept), rejected_counts)

        # 3) Soft-fill to ensure a minimum pool
        need_minimum = max(self.soft_fill_min, len(kept))
        kept = soft_fill(
            rows,
            kept,
            need_min=need_minimum,
            min_vol_usd=self.min_volume_usd,
            min_liq_usd=self.min_liquidity_usd,
            sort_key=self.soft_fill_sort,
        )

        # 4) Quality filters (no AI here)
        kept = apply_quality_filter(kept)
        if not kept:
            log.info("[QUALITY] 0 candidates after quality filter")
            return

        # 5) Sort and clip by a deterministic key to stabilize cohorts
        sort_key = self.soft_fill_sort if self.soft_fill_sort in {"vol24h", "liqUsd"} else "vol24h"
        kept.sort(key=lambda item: float(item.get(sort_key) or 0.0), reverse=True)
        kept = kept[: self.max_results]

        # 6) Remove symbols/addresses already in open positions
        open_symbols, open_addresses = self._open_sets()
        candidates = [
            item
            for item in kept
            if (item.get("symbol", "").upper() not in open_symbols)
               and ((item.get("address") or "").lower() not in open_addresses)
        ]
        if not candidates:
            log.info("[DEDUP] 0 candidates after removing open positions")
            return

        # 7) Preload best prices for decision quality (preserve SOL casing)
        address_list = [item.get("address") or "" for item in candidates if item.get("address")]
        best_price_by_address = preload_best_prices(address_list)

        # 8) Base scoring only (cheap)
        candidates = self._compute_base_scores(candidates)

        # 9) Gatekeeping BEFORE any AI calls (save cost/latency)
        cooldown_minutes = int(settings.DEXSCREENER_REBUY_COOLDOWN_MIN)
        max_price_deviation = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)

        eligible: List[Dict[str, Any]] = []
        for item in sorted(candidates, key=lambda x: x["base_score"], reverse=True):
            lookup_addr = _normalize_lookup_address(item.get("address") or "")

            if lookup_addr and recently_traded(lookup_addr, minutes=cooldown_minutes):
                log.debug("[GATE] skip recently traded %s", item.get("symbol"))
                continue

            decision = self.risk_manager.pre_entry_decision(item)
            if not decision.should_buy:
                log.debug("[GATE] pre-entry block %s — %s", item.get("symbol"), decision.reason)
                continue

            dex_price = best_price_by_address.get(lookup_addr)
            if dex_price is None or dex_price <= 0:
                log.debug("[GATE] invalid DEX price for %s", item.get("symbol"))
                continue

            quoted_price = float(item.get("price") or 0.0)
            if dex_price and quoted_price:
                low, high = sorted([dex_price, quoted_price])
                if low > 0 and (high / low) > max_price_deviation:
                    log.debug("[GATE] price deviation too large for %s (dex=%.6f quote=%.6f)",
                              item.get("symbol"), dex_price, quoted_price)
                    continue

            # enrich for later
            item["dex_price"] = dex_price
            eligible.append(item)

        if not eligible:
            log.info("[GATE] 0 candidates after checks")
            return

        # 10) Chart AI strictly last, on survivors only (top-K by base_score)
        top_for_ai = sorted(eligible, key=lambda x: x["base_score"], reverse=True)[: max(0, self.chart_ai_top_k)]
        engine_for_ai = ScoringEngine().fit(eligible)

        for item in top_for_ai:
            try:
                token_age_hours = _age_hours(int(item.get("pairCreatedAt") or 0))
                signal = self.chart_ai.predict(
                    symbol=(item.get("symbol") or ""),
                    chain_name=item.get("chain") or None,
                    pair_address=item.get("address") or None,
                    timeframe_minutes=self.chart_ai_timeframe,
                    lookback_minutes=self.chart_ai_lookback,
                    token_age_hours=token_age_hours,
                )
            except Exception:
                log.exception("[AI] ChartAI failed for %s", item.get("symbol") or item.get("address"))
                continue

            if signal is None:
                continue

            item["ai_delta"] = float(signal.quality_score_delta)
            item["ai_probability_buy"] = float(signal.probability_tp1_before_sl)
            item["final_score"] = float(engine_for_ai.apply_ai_adjustment(item["base_score"], item["ai_delta"]))

        # If no AI delta, final_score stays == base_score
        eligible.sort(key=lambda x: x.get("final_score", x["base_score"]), reverse=True)

        # 11) Execution constraints
        free_cash = self._free_cash()
        per_buy_usd = self._per_buy_budget(free_cash)
        min_free_cash_usd = float(settings.TREND_MIN_FREE_CASH_USD)
        max_buys_per_run = int(settings.TREND_MAX_BUYS_PER_RUN)

        simulated_cash = free_cash
        executed_buys = 0

        for item in eligible:
            if executed_buys >= max_buys_per_run:
                log.debug("[BUY] Max buys per run reached (%d)", max_buys_per_run)
                break

            size_multiplier = self.risk_manager.size_multiplier(item)
            order_notional = max(0.0, per_buy_usd * size_multiplier)

            if simulated_cash < order_notional or (simulated_cash - order_notional) < min_free_cash_usd:
                log.debug("[BUY] Insufficient simulated cash for %s (need=%.2f, have=%.2f, min_free=%.2f)",
                          item.get("symbol"), order_notional, simulated_cash, min_free_cash_usd)
                break

            # Enrich payload for execution/logging/audits
            payload = dict(item)
            payload["order_notional"] = order_notional

            log.info(
                "[BUY] %s base=%.2f final=%.2f aiΔ=%.2f prob=%.3f size×=%.2f notional=%.2f",
                item.get("symbol"),
                item.get("base_score"),
                item.get("final_score", item.get("base_score")),
                item.get("ai_delta", 0.0),
                item.get("ai_probability_buy", 0.0),
                size_multiplier,
                order_notional,
            )

            try:
                self.trader.buy(payload)
                executed_buys += 1
                simulated_cash -= order_notional
            except Exception as exc:
                log.warning("[BUY] Failed for %s: %s", item.get("symbol"), exc)

        log.info("[SUMMARY] executed=%d / %d candidates (cash=%.2f → %.2f)",
                 executed_buys, len(eligible), free_cash, simulated_cash)

    def run(self) -> None:
        """Compatibility alias."""
        self.run_once()
