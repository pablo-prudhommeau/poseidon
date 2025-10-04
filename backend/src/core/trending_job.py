from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple, Set, Coroutine, Optional

from src.ai.chart_signal_provider import ChartAiSignalProvider
from src.configuration.config import settings
from src.core.risk_manager import AdaptiveRiskManager
from src.core.trader import Trader
from src.core.trending_scoring import apply_quality_filter, ScoringEngine
from src.core.trending_utils import (
    filter_strict, soft_fill, recently_traded, preload_best_prices, _age_hours,
)
from src.logging.logger import get_logger
from src.persistence.dao.portfolio_snapshots import get_latest_portfolio
from src.persistence.dao.positions import get_open_positions
from src.persistence.db import _session

log = get_logger(__name__)


def _run_coro_in_fresh_loop(coro: Coroutine[Any, Any, Any], *, debug_label: str = "") -> Any:
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
    from src.integrations.dexscreener_client import fetch_trending_candidates
    return _run_coro_in_fresh_loop(fetch_trending_candidates(*args, **kwargs),
                                   debug_label="fetch_trending_candidates")


def _address_in_open_positions(candidate: str, addresses: Set[str]) -> bool:
    return bool(candidate) and candidate in addresses


def _price_get(price_map: Dict[str, float], address: str) -> Optional[float]:
    if not address:
        return None
    if address in price_map:
        return price_map.get(address)
    return None


class TrendingJob:
    """
    Pipeline (gates explicites) :
      1) QUALITY GATE     → qualityScore >= min
      2) STATISTICS GATE  → statScore   >= min
      3) AI GATE          → entryScore  >= min
      (puis sizing & buy au fil de l'eau)
    """

    def __init__(self) -> None:
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

        self.trader = Trader()
        self.risk_manager = AdaptiveRiskManager()

        self.chart_ai = ChartAiSignalProvider()
        self.chart_ai_top_k: int = int(getattr(settings, "TOP_K_CANDIDATES_FOR_CHART_AI"))
        self.chart_ai_timeframe: int = int(getattr(settings, "CHART_AI_TIMEFRAME"))
        self.chart_ai_lookback: int = int(getattr(settings, "CHART_AI_LOOKBACK_MINUTES"))

        self.min_statistics_score: float = float(getattr(settings, "SCORE_MIN_STATISTICS"))
        self.min_entry_score: float = float(getattr(settings, "SCORE_MIN_ENTRY"))

    def _free_cash(self) -> float:
        with _session() as db:
            snapshot = get_latest_portfolio(db, create_if_missing=True)
            return float(snapshot.cash or 0.0) if snapshot else 0.0

    def _open_sets(self) -> Tuple[Set[str], Set[str]]:
        with _session() as db:
            positions = get_open_positions(db)
            symbols = {(p.symbol or "").upper() for p in positions if p.symbol}
            addresses: Set[str] = {p.address for p in positions if getattr(p, "address", None)}
            return symbols, addresses

    def _per_buy_budget(self, free_cash: float) -> float:
        fraction = float(settings.TREND_PER_BUY_FRACTION)
        return max(1.0, free_cash * fraction)

    def run_once(self) -> None:
        if not settings.TREND_ENABLE:
            log.info("Trending disabled")
            return

        # 1) Fetch
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

        # 3) Soft-fill
        need_minimum = max(self.soft_fill_min, len(kept))
        kept = soft_fill(
            rows, kept,
            need_min=need_minimum,
            min_vol_usd=self.min_volume_usd,
            min_liq_usd=self.min_liquidity_usd,
            sort_key=self.soft_fill_sort,
        )

        # 4) QUALITY GATE (gate #1)
        kept = apply_quality_filter(kept)
        if not kept:
            log.info("[QUALITY] 0 candidates after gate #1")
            return

        # 5) Stabilise cohorte
        sort_key = self.soft_fill_sort if self.soft_fill_sort in {"vol24h", "liqUsd"} else "vol24h"
        kept.sort(key=lambda item: float(item.get(sort_key) or 0.0), reverse=True)
        kept = kept[: self.max_results]

        # 6) Dedup open positions
        symbols, addresses = self._open_sets()
        pruned: List[Dict[str, Any]] = []
        for item in kept:
            sym = (item.get("symbol") or "").upper()
            addr = item.get("address") or ""
            if sym in symbols or _address_in_open_positions(addr, addresses):
                log.debug("[DEDUP] skip already open %s (%s)", item.get("symbol"), addr)
                continue
            pruned.append(item)
        if not pruned:
            log.debug("[DEDUP] 0 candidates after de-duplication")
            return

        # 7) Preload prices (pré-décision)
        address_list = [it.get("address") or "" for it in pruned if it.get("address")]
        best_price_by_address = preload_best_prices(address_list)

        # 8) STATISTICS SCORE (gate #2)
        engine = ScoringEngine().fit(pruned)
        stat_ready: List[Dict[str, Any]] = []
        for it in pruned:
            s = engine.stat_score(it)
            it["statScore"] = s
            if s >= self.min_statistics_score:
                stat_ready.append(it)
            else:
                log.debug("[STATS][DROP] %s — statScore=%.2f<%.2f",
                          it.get("symbol"), s, self.min_statistics_score)
        if not stat_ready:
            log.info("[STATS] 0 candidates after gate #2")
            return

        # 9) Gatekeeping hors scoring (recently traded, risk, price sanity)
        cooldown_minutes = int(settings.DEXSCREENER_REBUY_COOLDOWN_MIN)
        max_price_deviation = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)

        eligible: List[Dict[str, Any]] = []
        for item in sorted(stat_ready, key=lambda x: x["statScore"], reverse=True):
            addr = item.get("address") or ""

            if addr and recently_traded(addr, minutes=cooldown_minutes):
                log.debug("[GATE][COOLDOWN] %s", item.get("symbol"))
                continue

            decision = self.risk_manager.pre_entry_decision(item)
            if not decision.should_buy:
                log.debug("[GATE][RISK] %s — %s", item.get("symbol"), decision.reason)
                continue

            dex_price = _price_get(best_price_by_address, addr)
            if dex_price is None or dex_price <= 0:
                log.debug("[GATE][PRICE] invalid DEX price for %s", item.get("symbol"))
                continue

            quoted_price = float(item.get("price") or 0.0)
            if dex_price and quoted_price:
                low, high = sorted([dex_price, quoted_price])
                if low > 0 and (high / low) > max_price_deviation:
                    log.debug("[GATE][DEV] %s dex=%.6f quote=%.6f", item.get("symbol"), dex_price, quoted_price)
                    continue

            item["dex_price"] = dex_price
            eligible.append(item)

        if not eligible:
            log.info("[GATE] 0 candidates after risk/price checks")
            return

        # 10) AI GATE (gate #3) + BUY au fil de l'eau
        free_cash = self._free_cash()
        per_buy_usd = self._per_buy_budget(free_cash)
        min_free_cash_usd = float(settings.TREND_MIN_FREE_CASH_USD)
        max_buys_per_run = int(settings.TREND_MAX_BUYS_PER_RUN)

        simulated_cash = free_cash
        executed_buys = 0
        ai_budget = max(0, self.chart_ai_top_k)

        for item in sorted(eligible, key=lambda x: x["statScore"], reverse=True):
            if executed_buys >= max_buys_per_run:
                log.debug("[BUY] Max buys per run reached (%d)", max_buys_per_run)
                break

            # IA si budget (sinon entryScore = statScore)
            entry_score = float(item["statScore"])
            if ai_budget > 0:
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
                    signal = None
                ai_budget -= 1

                if signal is not None:
                    item["aiDelta"] = float(signal.quality_score_delta)
                    item["aiBuyProb"] = float(signal.probability_tp1_before_sl)
                    entry_score = engine.apply_ai_adjustment(item["statScore"], item["aiDelta"])

            item["entryScore"] = entry_score

            # Gate #3 : entryScore minimal
            if entry_score < self.min_entry_score:
                log.debug("[AI][DROP] %s — entryScore=%.2f<%.2f (stat=%.2f aiΔ=%.2f prob=%.3f)",
                          item.get("symbol"), entry_score, self.min_entry_score,
                          item["statScore"], item.get("aiDelta", 0.0), item.get("aiBuyProb", 0.0))
                continue

            # Sizing & cash checks
            size_multiplier = self.risk_manager.size_multiplier(item)
            order_notional = max(0.0, per_buy_usd * size_multiplier)
            if simulated_cash < order_notional or (simulated_cash - order_notional) < min_free_cash_usd:
                log.debug("[BUY][CASH_SKIP] %s need=%.2f have=%.2f min_free=%.2f",
                          item.get("symbol"), order_notional, simulated_cash, min_free_cash_usd)
                continue

            payload = dict(item)
            payload["order_notional"] = order_notional

            self.trader.buy(payload)
            executed_buys += 1
            simulated_cash -= order_notional
            log.info(
                "[BUY] %s quality=%.1f stat=%.1f entry=%.1f aiΔ=%.2f prob=%.3f size×=%.2f notional=%.2f",
                item.get("symbol"),
                item.get("qualityScore", 0.0),
                item["statScore"],
                entry_score,
                item.get("aiDelta", 0.0),
                item.get("aiBuyProb", 0.0),
                size_multiplier,
                order_notional,
            )

        log.info("[SUMMARY] executed=%d / %d candidates (cash=%.2f → %.2f)",
                 executed_buys, len(eligible), free_cash, simulated_cash)

    def run(self) -> None:
        self.run_once()
