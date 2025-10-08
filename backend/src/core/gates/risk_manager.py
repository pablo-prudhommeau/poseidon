# backend/src/core/risk/risk_manager.py
from __future__ import annotations

import statistics
from typing import List, Optional, Sequence

from src.configuration.config import settings
from src.core.structures.structures import Candidate, PreEntryDecision, Thresholds, RiskDiagnostics
from src.logging.logger import get_logger

log = get_logger(__name__)


class AdaptiveRiskManager:
    """
    Adaptive risk & execution utilities:
      - Pre-entry anti-chase filter (avoid top-ticking exhaustion spikes)
      - ATR-like volatility proxy to derive TP1/TP2/SL
      - Risk-based sizing multiplier
      - Post-TP1 stop tightening helper
    """

    def __init__(self) -> None:
        self.max_abs_percent_5m: float = settings.DEXSCREENER_MAX_ABS_M5_PCT
        self.max_abs_percent_1h: float = settings.DEXSCREENER_MAX_ABS_H1_PCT
        self.min_liquidity_usd: float = settings.TREND_MIN_LIQ_USD
        self.tp1_exit_fraction_default: float = settings.TRENDING_TP1_EXIT_FRACTION
        self.tp2_exit_fraction_default: float = settings.TRENDING_TP2_EXIT_FRACTION
        self.stop_loss_fraction_floor: float = settings.TRENDING_STOP_LOSS_FRACTION_FLOOR
        self.stop_loss_fraction_cap: float = settings.TRENDING_STOP_LOSS_FRACTION_CAP
        self.default_volatility_fraction: float = 0.08
        self.target_position_volatility_fraction: float = 0.10

    @staticmethod
    def _prices_to_simple_returns(prices: Sequence[float]) -> List[float]:
        """
        Convert a sequence of positive prices into simple returns.
        Returns an empty list if not enough valid points are available.
        """
        if prices is None or len(prices) < 2:
            return []

        returns: List[float] = []
        for i in range(1, len(prices)):
            previous_price = float(prices[i - 1])
            current_price = float(prices[i])
            if previous_price <= 0.0 or current_price <= 0.0:
                continue
            returns.append((current_price - previous_price) / previous_price)
        return returns

    def _estimate_atr_like_volatility(self, candidate: Candidate) -> Optional[float]:
        """
        Robust ATR-like volatility proxy (fractional, e.g. 0.07 for 7%):
          - Prefer sparkline arrays when present
          - Fallback to dispersion of percent_5m / percent_1h if needed
        """
        pct_5m = candidate.percent_5m
        pct_1h = candidate.percent_1h

        window: List[float] = []
        if isinstance(pct_5m, (int, float)):
            window.append(abs(float(pct_5m)) / 100.0)
        if isinstance(pct_1h, (int, float)):
            window.append(abs(float(pct_1h)) / 100.0)

        if not window:
            return None

        return float(max(0.01, min(0.30, statistics.fmean(window))))

    def pre_entry_decision(self, candidate: Candidate) -> PreEntryDecision:
        """
        Decide if we should skip a buy now (anti-chase and basic sanity checks).

        Heuristics:
          - Enforce a minimum liquidity floor.
          - Prevent chasing when short-term (%5m) and hourly (%1h) are already extended.
          - Discourage entries with weak buy flow when price is already spiking.
        """
        symbol = candidate.symbol or "?"
        liquidity_usd = float(candidate.liquidity_usd)

        pct_5m_raw = candidate.percent_5m
        pct_1h_raw = candidate.percent_1h
        pct_5m = float(pct_5m_raw) if isinstance(pct_5m_raw, (int, float)) else None
        pct_1h = float(pct_1h_raw) if isinstance(pct_1h_raw, (int, float)) else None

        txns = candidate.txns
        bucket = txns.h1 or txns.h24
        buys = bucket.buys
        sells = bucket.sells
        total = buys + sells
        buy_ratio = (buys / total) if total > 0 else 0.5

        if liquidity_usd < self.min_liquidity_usd:
            log.debug("[RISK][PRE-ENTRY][DROP:LOW_LIQ] %s liq=%.0f < %.0f",
                      symbol, liquidity_usd, self.min_liquidity_usd)
            diag = RiskDiagnostics(
                liquidity_usd=liquidity_usd, percent_5m=float(pct_5m or 0.0), percent_1h=float(pct_1h or 0.0),
                buy_ratio=buy_ratio)
            return PreEntryDecision(should_buy=False, reason="low_liquidity", diagnostics=diag.as_plain_dict())

        if pct_5m is not None and abs(pct_5m) > self.max_abs_percent_5m and (
                pct_1h or 0.0) > self.max_abs_percent_1h * 0.7:
            log.debug("[RISK][PRE-ENTRY][DROP:SPIKE] %s pct5m=%.1f pct1h=%.1f", symbol, pct_5m or -1.0, pct_1h or -1.0)
            diag = RiskDiagnostics(
                liquidity_usd=liquidity_usd, percent_5m=float(pct_5m or 0.0), percent_1h=float(pct_1h or 0.0),
                buy_ratio=buy_ratio
            )
            return PreEntryDecision(should_buy=False, reason="overextended_spike", diagnostics=diag.as_plain_dict())

        if buy_ratio < 0.48 and (pct_5m or 0.0) > 6.0:
            log.debug("[RISK][PRE-ENTRY][DROP:WEAK_FLOW] %s buy_ratio=%.2f", symbol, buy_ratio)
            diag = RiskDiagnostics(
                liquidity_usd=liquidity_usd, percent_5m=float(pct_5m or 0.0), percent_1h=float(pct_1h or 0.0),
                buy_ratio=buy_ratio
            )
            return PreEntryDecision(should_buy=False, reason="weak_buy_flow", diagnostics=diag.as_plain_dict())

        diag = RiskDiagnostics(
            liquidity_usd=liquidity_usd, percent_5m=float(pct_5m or 0.0), percent_1h=float(pct_1h or 0.0),
            buy_ratio=buy_ratio
        )
        return PreEntryDecision(should_buy=True, reason="ok", diagnostics=diag.as_plain_dict())

    def compute_thresholds(self, entry_price: float, candidate: Candidate) -> Thresholds:
        """
        Compute TP1 / TP2 / SL using an ATR-like volatility proxy (fractional).
        The stop fraction is clamped to a safe floor/cap to avoid both noise exits
        and catastrophic risk.
        """
        if entry_price is None or entry_price <= 0.0:
            raise ValueError("entry_price must be > 0")

        entry = float(entry_price)
        volatility = self._estimate_atr_like_volatility(candidate) or self.default_volatility_fraction

        stop_fraction = float(min(self.stop_loss_fraction_cap, max(self.stop_loss_fraction_floor, 1.8 * volatility)))
        tp1_fraction = float(max(self.tp1_exit_fraction_default, stop_fraction * 0.9))
        tp2_fraction = float(max(self.tp2_exit_fraction_default, tp1_fraction * 1.8))

        tp1 = entry * (1.0 + tp1_fraction)
        tp2 = entry * (1.0 + tp2_fraction)
        stop = entry * (1.0 - stop_fraction)

        log.info(
            "[RISK][THRESHOLDS] entry=%.10f vol≈%.3f tp1=%.6f tp2=%.6f stop=%.6f",
            entry, volatility, tp1, tp2, stop,
        )
        log.debug(
            "[RISK][THRESHOLDS][DETAILS] stop_frac=%.3f tp1_frac=%.3f tp2_frac=%.3f (defaults tp1=%.3f tp2=%.3f)",
            stop_fraction, tp1_fraction, tp2_fraction, self.tp1_exit_fraction_default, self.tp2_exit_fraction_default,
        )
        return Thresholds(take_profit_tp1=tp1, take_profit_tp2=tp2, stop_loss=stop)

    def post_tp1_adjustments(self, entry_price: float, current_stop: float, tp1_price: float) -> float:
        """
        Raise the stop after TP1 to lock in profit while keeping room for trend continuation.
        Adds a small fee/slippage buffer and a cushion based on the TP1 distance.
        """
        if entry_price is None or entry_price <= 0.0:
            raise ValueError("entry_price must be > 0")
        if current_stop is None or current_stop <= 0.0:
            raise ValueError("current_stop must be > 0")
        if tp1_price is None or tp1_price <= 0.0:
            raise ValueError("tp1_price must be > 0")

        entry = float(entry_price)
        stop = float(current_stop)
        tp1 = float(tp1_price)

        buffer_target = entry + 0.002 * entry
        cushion = max(0.0, 0.35 * (tp1 - entry))
        new_stop = max(stop, buffer_target + cushion)

        log.info("[RISK][AFTER_TP1] stop: %.6f → %.6f", stop, new_stop)
        return new_stop

    def size_multiplier(self, candidate: Candidate) -> float:
        """
        Return a down-sizing multiplier in [0.5 .. 1.0] depending on realized volatility.
        Targets a stable per-position volatility exposure.
        """
        volatility = self._estimate_atr_like_volatility(candidate) or self.default_volatility_fraction
        target = self.target_position_volatility_fraction

        if target <= 0.0:
            log.debug("[RISK][SIZING][WARN] target_position_volatility_fraction <= 0; using 1.0")
            return 1.0

        multiplier = float(max(0.5, min(1.0, target / max(volatility, 1e-9))))
        log.debug("[RISK][SIZING] vol≈%.3f → size_mult=%.2f", volatility, multiplier)
        return multiplier
