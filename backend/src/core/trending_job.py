from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple, Set, Coroutine, Optional

from src.ai.chart_signal_provider import ChartAiSignalProvider
from src.configuration.config import settings
from src.core.risk_manager import AdaptiveRiskManager
from src.core.trader import Trader
from src.core.trending_scoring import apply_quality_filter, ScoringEngine
from src.core.trending_utils import (
    filter_strict,
    soft_fill,
    recently_traded,
    preload_best_prices,
    _age_hours,
)
from src.core.telemetry import TelemetryService
from src.core.utils import timezone_now
from src.logging.logger import get_logger
from src.persistence.dao.portfolio_snapshots import get_latest_portfolio
from src.persistence.dao.positions import get_open_positions
from src.persistence.db import _session
from src.persistence.models import Analytics

log = get_logger(__name__)


def _run_coro_in_fresh_loop(coro: Coroutine[Any, Any, Any], *, debug_label: str = "") -> Any:
    """
    Run a coroutine in a fresh event loop when the current one is closed.
    This protects long-lived processes that may recycle their loop.
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
    Explicit gate pipeline:
      1) QUALITY GATE     → qualityScore >= min
      2) STATISTICS GATE  → statScore   >= min
      3) AI GATE          → entryScore  >= min
      (then sizing & buy along the way)

    This version persists EVERY evaluated candidate (including SKIP reasons)
    and broadcasts each row as 'analytics' on WebSocket for the Analytics UI.
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

    # --------------------------- Helpers (cash / positions) ---------------------------

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

    # --------------------------- Telemetry persistence ---------------------------

    def _persist_and_broadcast(
            self,
            item: Dict[str, Any],
            rank: int,
            decision: str,
            reason: str,
            dex_price: float = 0.0,
            quoted_price: float = 0.0,
            sizing_multiplier: float = 0.0,
            order_notional_usd: float = 0.0,
            free_cash_before_usd: float = 0.0,
            free_cash_after_usd: float = 0.0,
    ) -> None:
        """
        Build a strict payload (no nulls), persist analytics, and broadcast it.

        All *raw* blobs are filled to guarantee full auditability from the UI.
        """
        components = item.get("scoreComponents") or {}
        quality_score = float(item.get("qualityScore") or components.get("qualityScore") or 0.0)
        statistics_score = float(item.get("statScore") or components.get("statisticsScore") or 0.0)
        entry_score = float(item.get("entryScore") or components.get("entryScore") or statistics_score)
        final_score = float(item.get("entryScore") or item.get("scoreFinal") or entry_score)

        payload = Analytics(
            symbol=(item.get("symbol") or "").upper(),
            chain=str(item.get("chain") or "unknown"),
            address=str(item.get("address") or ""),
            rank=int(rank),

            quality_score=quality_score,
            statistics_score=statistics_score,
            entry_score=entry_score,
            final_score=final_score,

            ai_probability_tp1_before_sl=float(item.get("aiBuyProb") or 0.0),
            ai_quality_score_delta=float(item.get("aiDelta") or 0.0),

            token_age_hours=float(item.get("token_age_hours") or 0.0),
            volume24h_usd=float(item.get("vol24h") or item.get("volume24hUsd") or 0.0),
            liquidity_usd=float(item.get("liqUsd") or item.get("liquidityUsd") or 0.0),
            pct_5m=float(item.get("pct5m") or 0.0),
            pct_1h=float(item.get("pct1h") or 0.0),
            pct_24h=float(item.get("pct24h") or 0.0),

            evaluated_at=timezone_now(),  # authoritative on server

            decision=(decision or "UNKNOWN").upper(),
            decision_reason=reason or "",

            sizing_multiplier=float(sizing_multiplier or 0.0),
            order_notional_usd=float(order_notional_usd or 0.0),
            free_cash_before_usd=float(free_cash_before_usd or 0.0),
            free_cash_after_usd=float(free_cash_after_usd or 0.0),

            # RAW blobs
            raw_dexscreener=dict(item),
            raw_ai={
                "qualityDelta": float(item.get("aiDelta") or 0.0),
                "probabilityTp1BeforeSl": float(item.get("aiBuyProb") or 0.0),
            },
            raw_risk={"skipReason": reason} if reason else {},
            raw_pricing={
                "dexPrice": float(dex_price or item.get("dex_price") or 0.0),
                "quotedPrice": float(quoted_price or item.get("price") or 0.0),
            },
            raw_settings={
                "SCORE_MIN_STATISTICS": float(getattr(settings, "SCORE_MIN_STATISTICS")),
                "SCORE_MIN_ENTRY": float(getattr(settings, "SCORE_MIN_ENTRY")),
                "REBUY_COOLDOWN_MIN": int(getattr(settings, "DEXSCREENER_REBUY_COOLDOWN_MIN")),
                "MAX_PRICE_DEV": float(getattr(settings, "TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER")),
                "PER_BUY_FRACTION": float(getattr(settings, "TREND_PER_BUY_FRACTION")),
                "MIN_FREE_CASH_USD": float(getattr(settings, "TREND_MIN_FREE_CASH_USD")),
                "MAX_BUYS_PER_RUN": int(getattr(settings, "TREND_MAX_BUYS_PER_RUN")),
            },
            raw_order_result={
                "decision": (decision or "UNKNOWN").upper(),
                "reason": reason or "",
                "sizingMultiplier": float(sizing_multiplier or 0.0),
                "orderNotionalUsd": float(order_notional_usd or 0.0),
                "freeCashBeforeUsd": float(free_cash_before_usd or 0.0),
                "freeCashAfterUsd": float(free_cash_after_usd or 0.0),
            },
        )
        TelemetryService.record_analytics_event(payload)

    # --------------------------- Main loop ---------------------------

    def run_once(self) -> None:
        if not settings.TREND_ENABLE:
            log.info("Trending disabled.")
            return

        # 1) Fetch candidates
        try:
            rows = _fetch_trending_candidates_sync()
        except Exception as exc:
            log.warning("DexScreener trending fetch failed: %s", exc)
            rows = []

        if not rows:
            log.info("Trending: 0 candidates.")
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

        # 3) Soft-fill to stabilize cohort size
        need_minimum = max(self.soft_fill_min, len(kept))
        kept = soft_fill(
            rows, kept,
            need_min=need_minimum,
            min_vol_usd=self.min_volume_usd,
            min_liq_usd=self.min_liquidity_usd,
            sort_key=self.soft_fill_sort,
        )

        # 4) QUALITY GATE
        kept = apply_quality_filter(kept)
        if not kept:
            log.info("[QUALITY] 0 candidates after gate #1.")
            return

        # 5) Cohort ordering
        sort_key = self.soft_fill_sort if self.soft_fill_sort in {"vol24h", "liqUsd"} else "vol24h"
        kept.sort(key=lambda item: float(item.get(sort_key) or 0.0), reverse=True)
        kept = kept[: self.max_results]

        # 6) Deduplicate open positions (symbol/address)
        symbols, addresses = self._open_sets()
        pruned: List[Dict[str, Any]] = []
        for item in kept:
            sym = (item.get("symbol") or "").upper()
            addr = item.get("address") or ""
            if sym in symbols or _address_in_open_positions(addr, addresses):
                log.debug("[DEDUP] Skip already open %s (%s).", item.get("symbol"), addr)
                continue
            pruned.append(item)

        if not pruned:
            log.debug("[DEDUP] 0 candidates after de-duplication.")
            return

        # 7) Preload best prices (pre-decision)
        address_list = [it.get("address") or "" for it in pruned if it.get("address")]
        best_price_by_address = preload_best_prices(address_list)

        # 8) STATISTICS GATE
        engine = ScoringEngine().fit(pruned)
        statistics_ready: List[Dict[str, Any]] = []
        for item in pruned:
            statistics_score = engine.stat_score(item)
            item["statScore"] = statistics_score
            if statistics_score >= self.min_statistics_score:
                statistics_ready.append(item)
            else:
                log.debug("[STATS][DROP] %s — statScore=%.2f<%.2f",
                          item.get("symbol"), statistics_score, self.min_statistics_score)

        if not statistics_ready:
            log.info("[STATS] 0 candidates after gate #2.")
            return

        # 9) Gatekeeping (cooldown, risk, price sanity)
        cooldown_minutes = int(settings.DEXSCREENER_REBUY_COOLDOWN_MIN)
        max_price_deviation = float(settings.TRENDING_MAX_PRICE_DEVIATION_MULTIPLIER)

        eligible: List[Dict[str, Any]] = []
        for item in sorted(statistics_ready, key=lambda x: x["statScore"], reverse=True):
            address = item.get("address") or ""

            if address and recently_traded(address, minutes=cooldown_minutes):
                log.debug("[GATE][COOLDOWN] %s", item.get("symbol"))
                self._persist_and_broadcast(item, rank=len(eligible) + 1, decision="SKIP", reason="COOLDOWN")
                continue

            pre_decision = self.risk_manager.pre_entry_decision(item)
            if not pre_decision.should_buy:
                log.debug("[GATE][RISK] %s — %s", item.get("symbol"), pre_decision.reason)
                self._persist_and_broadcast(item, rank=len(eligible) + 1,
                                            decision="SKIP", reason=f"RISK:{pre_decision.reason}")
                continue

            dex_price = _price_get(best_price_by_address, address)
            if dex_price is None or dex_price <= 0.0:
                log.debug("[GATE][PRICE] invalid DEX price for %s", item.get("symbol"))
                self._persist_and_broadcast(item, rank=len(eligible) + 1,
                                            decision="SKIP", reason="NO_DEX_PRICE")
                continue

            quoted_price = float(item.get("price") or 0.0)
            if dex_price and quoted_price:
                low, high = sorted([dex_price, quoted_price])
                if low > 0 and (high / low) > max_price_deviation:
                    log.debug("[GATE][DEV] %s dex=%.10f quote=%.10f", item.get("symbol"), dex_price, quoted_price)
                    self._persist_and_broadcast(item, rank=len(eligible) + 1,
                                                decision="SKIP", reason="PRICE_DEVIATION",
                                                dex_price=dex_price, quoted_price=quoted_price)
                    continue

            item["dex_price"] = dex_price
            eligible.append(item)

        if not eligible:
            log.info("[GATE] 0 candidates after risk/price checks.")
            return

        # 10) AI GATE + BUY as we go
        free_cash = self._free_cash()
        per_buy_usd = self._per_buy_budget(free_cash)
        min_free_cash_usd = float(settings.TREND_MIN_FREE_CASH_USD)
        max_buys_per_run = int(settings.TREND_MAX_BUYS_PER_RUN)

        simulated_cash = free_cash
        executed_buys = 0
        ai_budget_remaining = max(0, self.chart_ai_top_k)

        for rank, item in enumerate(sorted(eligible, key=lambda x: x["statScore"], reverse=True), start=1):
            if executed_buys >= max_buys_per_run:
                log.debug("[BUY] Max buys per run reached (%d).", max_buys_per_run)
                break

            # Token age for analytics
            item["token_age_hours"] = float(_age_hours(int(item.get("pairCreatedAt") or 0)))

            # Entry score starts from statistics score; may be adjusted by AI.
            entry_score = float(item["statScore"])
            ai_probability = 0.0
            ai_delta = 0.0

            if ai_budget_remaining > 0:
                try:
                    signal = self.chart_ai.predict(
                        symbol=(item.get("symbol") or ""),
                        chain_name=item.get("chain") or None,
                        pair_address=item.get("address") or None,
                        timeframe_minutes=self.chart_ai_timeframe,
                        lookback_minutes=self.chart_ai_lookback,
                        token_age_hours=float(item["token_age_hours"]),
                    )
                except Exception:
                    log.exception("[AI] ChartAI failed for %s", item.get("symbol") or item.get("address"))
                    signal = None
                ai_budget_remaining -= 1

                if signal is not None:
                    ai_delta = float(signal.quality_score_delta)
                    ai_probability = float(signal.probability_tp1_before_sl)
                    # IMPORTANT: call instance method (fixes previous crash)
                    entry_score = engine.apply_ai_adjustment(float(item["statScore"]), ai_delta)

            item["aiDelta"] = ai_delta
            item["aiBuyProb"] = ai_probability
            item["entryScore"] = entry_score

            # Gate #3: minimal entry score
            if entry_score < self.min_entry_score:
                reason = "ENTRY_SCORE_BELOW_MIN"
                self._persist_and_broadcast(
                    item, rank=rank, decision="SKIP", reason=reason,
                    dex_price=float(item.get("dex_price") or 0.0),
                    quoted_price=float(item.get("price") or 0.0),
                )
                log.debug(
                    "[AI][DROP] %s — entryScore=%.2f<%.2f (stat=%.2f aiΔ=%.2f prob=%.3f)",
                    item.get("symbol"), entry_score, self.min_entry_score,
                    item["statScore"], ai_delta, ai_probability,
                )
                continue

            # Sizing and cash checks
            size_multiplier = self.risk_manager.size_multiplier(item)
            order_notional = max(0.0, per_buy_usd * size_multiplier)

            if simulated_cash < order_notional or (simulated_cash - order_notional) < min_free_cash_usd:
                reason = "INSUFFICIENT_CASH"
                self._persist_and_broadcast(
                    item, rank=rank, decision="SKIP", reason=reason,
                    dex_price=float(item.get("dex_price") or 0.0),
                    quoted_price=float(item.get("price") or 0.0),
                    sizing_multiplier=size_multiplier,
                    order_notional_usd=order_notional,
                    free_cash_before_usd=simulated_cash,
                    free_cash_after_usd=simulated_cash,
                )
                log.debug(
                    "[BUY][CASH_SKIP] %s need=%.2f have=%.2f min_free=%.2f",
                    item.get("symbol"), order_notional, simulated_cash, min_free_cash_usd,
                )
                continue

            # BUY flow — persist decision BEFORE execution to capture full intent
            self._persist_and_broadcast(
                item, rank=rank, decision="BUY", reason="OK",
                dex_price=float(item.get("dex_price") or 0.0),
                quoted_price=float(item.get("price") or 0.0),
                sizing_multiplier=size_multiplier,
                order_notional_usd=order_notional,
                free_cash_before_usd=simulated_cash,
                free_cash_after_usd=simulated_cash - order_notional,
            )

            # Execute the order
            order_payload = dict(item)
            order_payload["order_notional"] = order_notional
            self.trader.buy(order_payload)

            executed_buys += 1
            simulated_cash -= order_notional

            log.info(
                "[BUY] %s quality=%.1f stat=%.1f entry=%.1f aiΔ=%.2f prob=%.3f size×=%.2f notional=%.2f",
                item.get("symbol"),
                item.get("qualityScore", 0.0),
                item["statScore"],
                entry_score,
                ai_delta,
                ai_probability,
                size_multiplier,
                order_notional,
            )

        log.info(
            "[SUMMARY] executed=%d / %d candidates (cash=%.2f → %.2f)",
            executed_buys, len(eligible), free_cash, simulated_cash,
        )

    def run(self) -> None:
        self.run_once()
