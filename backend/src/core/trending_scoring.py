from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from src.configuration.config import settings
from src.core.trending_utils import _num, _age_hours, _buy_sell_score, _momentum_ok, _format, _tail, \
    _has_valid_intraday_bars
from src.logging.logger import get_logger

log = get_logger(__name__)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _squash_pct(pct: float) -> float:
    return 1.0 / (1.0 + math.exp(-(pct) / 5.0))


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    invert: bool = False


class RobustMinMax:
    def __init__(self, lower_percentile: float = 5.0, upper_percentile: float = 95.0) -> None:
        if not (0.0 <= lower_percentile < upper_percentile <= 100.0):
            raise ValueError("Invalid percentile bounds")
        self._lp = lower_percentile
        self._up = upper_percentile
        self._a: float | None = None
        self._b: float | None = None

    @staticmethod
    def _percentile(sorted_values: List[float], p: float) -> float:
        if not sorted_values:
            return 0.0
        k = (len(sorted_values) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_values[int(k)]
        d0 = sorted_values[int(f)] * (c - k)
        d1 = sorted_values[int(c)] * (k - f)
        return d0 + d1

    def fit(self, values: Iterable[float]) -> "RobustMinMax":
        arr = sorted(float(v) for v in values if not math.isnan(float(v)))
        if not arr:
            self._a = 0.0
            self._b = 1.0
            return self
        a = self._percentile(arr, self._lp)
        b = self._percentile(arr, self._up)
        if b <= a:
            b = a + 1.0
        self._a, self._b = float(a), float(b)
        return self

    def transform(self, value: float) -> float:
        a = 0.0 if self._a is None else self._a
        b = 1.0 if self._b is None else self._b
        x = (float(value) - a) / (b - a)
        return _clamp(x, 0.0, 1.0)


class ScoringEngine:
    """
    Terminologie unifiée :
      - statScore ∈ [0..100]  → **Statistics score** (ex-« base »)
      - entryScore ∈ [0..100] → **AI score** (statScore ajusté par l’IA)
    """

    FEATURE_SPECS: Tuple[FeatureSpec, ...] = (
        FeatureSpec("liquidity_usd", invert=False),
        FeatureSpec("volume_24h_usd", invert=False),
        FeatureSpec("age_hours", invert=True),
        FeatureSpec("momentum_score", invert=False),
        FeatureSpec("order_flow_score", invert=False),
    )

    def __init__(self) -> None:
        self._scalers: dict[str, RobustMinMax] = {spec.key: RobustMinMax() for spec in self.FEATURE_SPECS}

    def fit(self, candidates: Iterable[Dict[str, Any]]) -> "ScoringEngine":
        raw_features = [self._compute_raw_features(it) for it in candidates]
        for spec in self.FEATURE_SPECS:
            values = [feat[spec.key] for feat in raw_features]
            self._scalers[spec.key].fit(values)
        log.debug("[STATS] fitted scalers on %d candidates", len(raw_features))
        return self

    # --- Statistics score (ex-base) ------------------------------------------

    def stat_score(self, item: Dict[str, Any]) -> float:
        """Compute non-AI statistics score in [0..100]."""
        raw = self._compute_raw_features(item)
        weighted_sum = 0.0
        total_weight = 0.0

        for key, weight in self._weights().items():
            scaler = self._scalers.get(key)
            if not scaler:
                continue
            normalized = scaler.transform(raw[key])
            if self._is_inverted(key):
                normalized = 1.0 - normalized
            weighted_sum += weight * normalized
            total_weight += weight

        score = 100.0 * (weighted_sum / max(total_weight, 1e-9))
        score = _clamp(score, 0.0, 100.0)
        log.debug("[SCORING][STATS] %s → %.2f (raw=%s)",
                  item.get("symbol") or item.get("address") or "<unknown>", score, raw)
        return score

    # Backward-compat (si des imports externes appellent encore base_score)
    def base_score(self, item: Dict[str, Any]) -> float:
        return self.stat_score(item)

    # --- AI → Entry score -----------------------------------------------------

    def apply_ai_adjustment(self, stat_score: float, ai_delta: float) -> float:
        """
        entryScore = clamp(statScore + clamp(ai_delta * MULT, ±MAX_POINTS), 0, 100)
        """
        multiplier = float(getattr(settings, "SCORE_AI_DELTA_MULTIPLIER", 1.0))
        max_abs = float(getattr(settings, "SCORE_AI_MAX_ABS_DELTA_POINTS", 18.0))

        scaled = float(ai_delta) * multiplier
        capped = _clamp(scaled, -max_abs, +max_abs)
        entry = _clamp(float(stat_score) + capped, 0.0, 100.0)
        log.debug("[SCORING][AI] stats=%.2f aiΔ=%.2f → entry=%.2f", stat_score, capped, entry)
        return entry

    # --- Internals ------------------------------------------------------------

    def _weights(self) -> Dict[str, float]:
        return {
            "liquidity_usd": float(getattr(settings, "SCORE_WEIGHT_LIQUIDITY", 1.0)),
            "volume_24h_usd": float(getattr(settings, "SCORE_WEIGHT_VOLUME", 1.0)),
            "age_hours": float(getattr(settings, "SCORE_WEIGHT_AGE", 0.7)),
            "momentum_score": float(getattr(settings, "SCORE_WEIGHT_MOMENTUM", 1.3)),
            "order_flow_score": float(getattr(settings, "SCORE_WEIGHT_ORDER_FLOW", 1.0)),
        }

    def _is_inverted(self, key: str) -> bool:
        for spec in self.FEATURE_SPECS:
            if spec.key == key:
                return spec.invert
        return False

    def _compute_raw_features(self, item: Dict[str, Any]) -> Dict[str, float]:
        liquidity_usd = float(item.get("liqUsd") or 0.0)
        volume_24h_usd = float(item.get("vol24h") or 0.0)
        age_hours = _age_hours(int(item.get("pairCreatedAt") or 0))
        pct_5m = _num(item.get("pct5m")) or 0.0
        pct_1h = _num(item.get("pct1h")) or 0.0
        pct_24h = _num(item.get("pct24h")) or 0.0
        momentum = self._blend_momentum(pct_5m, pct_1h, pct_24h)
        order_flow = _buy_sell_score(item.get("txns") or {})
        return {
            "liquidity_usd": liquidity_usd,
            "volume_24h_usd": volume_24h_usd,
            "age_hours": age_hours,
            "momentum_score": momentum,
            "order_flow_score": order_flow,
        }

    @staticmethod
    def _blend_momentum(p5: float, h1: float, h24: float) -> float:
        def squash(pct: float) -> float:
            return 1.0 / (1.0 + math.exp(-pct / 5.0))

        s5 = squash(p5);
        s1 = squash(h1);
        s24 = squash(h24)
        return float(0.6 * s5 + 0.3 * s1 + 0.1 * s24)


def _compute_quality_score(item: Dict[str, Any]) -> Tuple[bool, float, str, Dict[str, float]]:
    """
    QUALITY SCORE (gate #1) — admissibilité avant tout ranking.
    Retourne (is_ok, score[0..100], reason, ctx).
    """
    liquidity_usd = float(item.get("liqUsd") or 0.0)
    volume_24h_usd = float(item.get("vol24h") or 0.0)
    pct_5m = _num(item.get("pct5m"))
    pct_1h = _num(item.get("pct1h"))
    pct_24h = _num(item.get("pct24h"))
    age_hours = _age_hours(int(item.get("pairCreatedAt") or 0))
    order_flow = _buy_sell_score(item.get("txns") or {})

    min_liquidity_usd = float(settings.TREND_MIN_LIQ_USD)
    min_volume_24h_usd = float(settings.TREND_MIN_VOL_USD)
    min_age_hours = float(settings.DEXSCREENER_MIN_AGE_HOURS)
    max_age_hours = float(settings.DEXSCREENER_MAX_AGE_HOURS)

    if liquidity_usd < min_liquidity_usd:
        log.debug("[QUALITY][DROP:LOW_LIQ] %s — %.0f < %.0f", item.get("symbol"), liquidity_usd, min_liquidity_usd)
        return False, 0.0, "low_liquidity", {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours,
                                             "bs": order_flow, "p5": pct_5m, "p1": pct_1h, "p24": pct_24h}

    if volume_24h_usd < min_volume_24h_usd:
        log.debug("[QUALITY][DROP:LOW_VOL] %s — %.0f < %.0f", item.get("symbol"), volume_24h_usd, min_volume_24h_usd)
        return False, 0.0, "low_volume", {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours,
                                          "bs": order_flow, "p5": pct_5m, "p1": pct_1h, "p24": pct_24h}

    if age_hours < min_age_hours or age_hours > max_age_hours:
        log.debug("[QUALITY][DROP:AGE] %s — %.1fh not in [%.1f..%.1f]",
                  item.get("symbol"), age_hours, min_age_hours, max_age_hours)
        return False, 0.0, "age_out_of_bounds", {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours,
                                                 "bs": order_flow, "p5": pct_5m, "p1": pct_1h, "p24": pct_24h}

    if not _momentum_ok(pct_5m, pct_1h, pct_24h):
        log.debug("[QUALITY][DROP:MOMENTUM] %s — m5=%s m1=%s m24=%s",
                  item.get("symbol"), _format(pct_5m), _format(pct_1h), _format(pct_24h))
        return False, 0.0, "choppy_or_spiky", {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours,
                                               "bs": order_flow, "p5": pct_5m, "p1": pct_1h, "p24": pct_24h}

    s5 = _squash_pct((pct_5m or 0.0))
    s1 = _squash_pct((pct_1h or 0.0))
    s24 = _squash_pct((pct_24h or 0.0))
    momentum_score = 0.6 * s5 + 0.3 * s1 + 0.1 * s24

    liquidity_component = min(1.0, liquidity_usd / (min_liquidity_usd * 4.0))
    volume_component = min(1.0, volume_24h_usd / (min_volume_24h_usd * 4.0))

    quality_score = 100.0 * (0.45 * momentum_score + 0.25 * liquidity_component +
                             0.20 * volume_component + 0.10 * order_flow)
    ctx = {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours, "bs": order_flow,
           "p5": pct_5m, "p1": pct_1h, "p24": pct_24h, "momentum": momentum_score,
           "liq_score": liquidity_component, "vol_score": volume_component}
    return True, float(quality_score), "ok", ctx


def apply_quality_filter(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Gate #1 — ne garde que ceux au-dessus du qualityScore minimal & barres intraday valides."""
    if not candidates:
        return []

    minimum_quality_score = float(settings.SCORE_MIN_QUALITY)
    kept: List[Dict[str, Any]] = []

    for candidate in candidates:
        is_ok, score, _, ctx = _compute_quality_score(candidate)
        candidate["qualityScore"] = score
        symbol_upper = (candidate.get("symbol") or "").upper()
        short_address = _tail(candidate.get("address") or "")

        if is_ok and score >= minimum_quality_score:
            if not _has_valid_intraday_bars(candidate):
                log.debug("[QUALITY][DROP:BARS] %s — intraday bars missing (m1/m5=NA)", candidate.get("symbol"))
                continue
            kept.append(candidate)
            log.debug("[QUALITY][KEEP] %s (%s) — quality=%.2f≥%.2f", symbol_upper, short_address,
                      score, minimum_quality_score)

    return kept
