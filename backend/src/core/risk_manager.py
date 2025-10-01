from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass
class Thresholds:
    """Container for per-position thresholds computed ex-ante."""
    take_profit_tp1: float
    take_profit_tp2: float
    stop_loss: float


@dataclass
class PreEntryDecision:
    """Decision and diagnostics for whether we should buy now."""
    should_buy: bool
    reason: str
    diagnostics: Dict[str, float]


class AdaptiveRiskManager:
    """
    Adaptive risk & execution utilities:
    - Pre-entry anti-chase filter (avoid top-ticking exhaustion spikes)
    - ATR-like volatility proxy to derive TP1/TP2/SL
    - Risk-based sizing multiplier
    - Post-TP1 stop tightening helper
    """

    def __init__(self) -> None:
        self.max_abs_pct_5m: float = float(getattr(settings, "DEXSCREENER_MAX_ABS_M5_PCT"))
        self.max_abs_pct_1h: float = float(getattr(settings, "DEXSCREENER_MAX_ABS_H1_PCT"))
        self.min_liquidity_usd: float = float(getattr(settings, "TREND_MIN_LIQ_USD"))
        self.tp1_exit_fraction_default: float = float(getattr(settings, "TRENDING_TP1_EXIT_FRACTION"))
        self.tp2_exit_fraction_default: float = float(getattr(settings, "TRENDING_TP2_EXIT_FRACTION"))
        self.stop_loss_fraction_floor: float = float(getattr(settings, "TRENDING_STOP_LOSS_FRACTION_FLOOR"))
        self.stop_loss_fraction_cap: float = float(getattr(settings, "TRENDING_STOP_LOSS_FRACTION_CAP"))

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _percent_array_to_returns(prices: Iterable[float]) -> List[float]:
        """Convert a sequence of prices to simple returns."""
        arr = [float(x) for x in prices if x is not None]
        if len(arr) < 2:
            return []
        returns: List[float] = []
        for i in range(1, len(arr)):
            a, b = arr[i - 1], arr[i]
            if a <= 0.0 or b <= 0.0:
                continue
            returns.append((b - a) / a)
        return returns

    def _atr_like(self, candidate: Dict[str, Any]) -> Optional[float]:
        """
        Robust ATR proxy (fractional, e.g. 0.07 for 7%):
        - Prefer sparkline arrays when present
        - Fallback to dispersion of pct5m/pct1h if needed
        """
        for key in ("sparkline5m", "sparkline30m", "prices", "sparkline"):
            seq = candidate.get(key)
            if isinstance(seq, (list, tuple)) and len(seq) >= 10:
                rets = self._percent_array_to_returns(seq)
                if len(rets) >= 5:
                    vol = statistics.fmean(abs(r) for r in rets[-20:])
                    return float(vol)

        p5 = self._to_float(candidate.get("pct5m"))
        p1 = self._to_float(candidate.get("pct1h"))
        if p5 is None and p1 is None:
            return None
        vals = [abs(x) / 100.0 for x in (p5 or 0.0, p1 or 0.0) if x is not None]
        if not vals:
            return None
        return float(max(0.01, min(0.30, statistics.fmean(vals))))

    def pre_entry_decision(self, candidate: Dict[str, Any]) -> PreEntryDecision:
        """Decide if we should skip a buy now (anti-chase + basic sanity checks)."""
        symbol = candidate.get("symbol") or "?"
        liq_usd = self._to_float(candidate.get("liqUsd")) or 0.0
        pct_5m = self._to_float(candidate.get("pct5m"))
        pct_1h = self._to_float(candidate.get("pct1h"))

        txns: Dict[str, Any] = candidate.get("txns") or {}
        bucket = txns.get("h1") or txns.get("h24") or {}
        buys = float(bucket.get("buys") or 0.0)
        sells = float(bucket.get("sells") or 0.0)
        total = buys + sells
        buy_ratio = (buys / total) if total > 0 else 0.5

        if liq_usd < self.min_liquidity_usd:
            log.debug("[PRE-ENTRY:LOW_LIQ] %s liq=%.0f < %.0f", symbol, liq_usd, self.min_liquidity_usd)
            return PreEntryDecision(False, "low_liquidity", {"liq": liq_usd, "buy_ratio": buy_ratio})

        if pct_5m is not None and abs(pct_5m) > self.max_abs_pct_5m and (pct_1h or 0.0) > self.max_abs_pct_1h * 0.7:
            log.debug("[PRE-ENTRY:SPIKE] %s pct5m=%.1f pct1h=%.1f", symbol, pct_5m or -1, pct_1h or -1)
            return PreEntryDecision(False, "overextended_spike", {"pct5m": pct_5m or 0.0, "pct1h": pct_1h or 0.0})

        if buy_ratio < 0.48 and (pct_5m or 0.0) > 6.0:
            log.debug("[PRE-ENTRY:WEAK_FLOW] %s buy_ratio=%.2f", symbol, buy_ratio)
            return PreEntryDecision(False, "weak_buy_flow", {"buy_ratio": buy_ratio})

        return PreEntryDecision(True, "ok", {"liq": liq_usd, "buy_ratio": buy_ratio, "pct5m": pct_5m or 0.0})

    def compute_thresholds(self, entry_price: float, candidate: Dict[str, Any]) -> Thresholds:
        """
        Compute TP1/TP2/SL using an ATR-like volatility proxy.
        Clamps the stop to a safe floor/cap to avoid both noise exits
        and catastrophic risk.
        """
        entry = float(entry_price or 0.0)
        if entry <= 0.0:
            raise ValueError("entry_price must be > 0")

        vol = self._atr_like(candidate) or 0.08
        stop_frac = float(min(self.stop_loss_fraction_cap, max(self.stop_loss_fraction_floor, 1.8 * vol)))
        tp1_frac = float(max(self.tp1_exit_fraction_default, stop_frac * 0.9))
        tp2_frac = float(max(self.tp2_exit_fraction_default, tp1_frac * 1.8))

        tp1 = entry * (1.0 + tp1_frac)
        tp2 = entry * (1.0 + tp2_frac)
        stop = entry * (1.0 - stop_frac)

        log.info(
            "[RISK][THRESHOLDS] entry=%.10f vol≈%.3f tp1=%.6f tp2=%.6f stop=%.6f",
            entry, vol, tp1, tp2, stop
        )
        log.debug(
            "[RISK][DETAILS] stop_frac=%.3f tp1_frac=%.3f tp2_frac=%.3f (defaults tp1=%.3f tp2=%.3f)",
            stop_frac, tp1_frac, tp2_frac,
            self.tp1_exit_fraction_default, self.tp2_exit_fraction_default
        )
        return Thresholds(take_profit_tp1=tp1, take_profit_tp2=tp2, stop_loss=stop)

    def post_tp1_adjustments(self, entry_price: float, current_stop: float, tp1_price: float) -> float:
        """Raise stop after TP1 to lock in profit while keeping trend continuation room."""
        entry = float(entry_price or 0.0)
        stop = float(current_stop or 0.0)
        tp1 = float(tp1_price or 0.0)

        target = entry + 0.002 * entry  # ~0.2% buffer for fees/slippage
        cushion = max(0.0, 0.35 * (tp1 - entry))
        new_stop = max(stop, target + cushion)

        log.info("[RISK][AFTER_TP1] stop: %.6f → %.6f", stop, new_stop)
        return new_stop

    def size_multiplier(self, candidate: Dict[str, Any]) -> float:
        """Return a down-sizing multiplier in [0.5..1.0] depending on realized volatility."""
        vol = self._atr_like(candidate) or 0.08
        target_vol = 0.10
        mult = float(max(0.5, min(1.0, target_vol / max(vol, 1e-6))))
        log.debug("[RISK][SIZING] vol≈%.3f → size_mult=%.2f", vol, mult)
        return mult
