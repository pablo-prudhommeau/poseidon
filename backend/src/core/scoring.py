from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from src.configuration.config import settings
from src.core.trending_utils import _num, _age_hours, _buy_sell_score
from src.logging.logger import get_logger

log = get_logger(__name__)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class FeatureSpec:
    """Describe how to normalize a feature into [0..1], with optional inversion."""
    key: str
    invert: bool = False


class RobustMinMax:
    """
    Percentile-based min-max scaler that is stable in the presence of outliers.
    Maps values to [0.0, 1.0].
    """

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
    Compute a normalized base score in [0..100] and apply the Chart AI adjustment at the very end.

    Features:
      - liquidity_usd
      - volume_24h_usd
      - age_hours (inverted: younger favored for very short-term trading)
      - momentum_score (blend of m5, h1, h24 percent changes)
      - order_flow_score (buy/sell pressure proxy)

    Final score:
      final = clamp(base + ai_delta_points, 0, 100)

    All weights and AI caps are read from Settings when present, with safe defaults otherwise.
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
        """Fit robust scalers from the current cohort."""
        raw_features = [self._compute_raw_features(it) for it in candidates]
        for spec in self.FEATURE_SPECS:
            values = [feat[spec.key] for feat in raw_features]
            self._scalers[spec.key].fit(values)
        log.debug("[SCORING] Fitted scalers on %d candidates", len(raw_features))
        return self

    def base_score(self, item: Dict[str, Any]) -> float:
        """Compute a 0..100 base score from raw features using configured weights."""
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

        score_0_100 = 100.0 * (weighted_sum / max(total_weight, 1e-9))
        log.debug(
            "[SCORING][BASE] %s → %.2f (raw=%s)",
            item.get("symbol") or item.get("address") or "<unknown>",
            score_0_100,
            raw,
            )
        return _clamp(score_0_100, 0.0, 100.0)

    def apply_ai_adjustment(self, base_score: float, ai_delta: float) -> float:
        """
        Combine the base score with the AI delta.

        ai_delta: value returned by Chart AI in [-20..+20] representing the quality adjustment.

        Controls (with safe defaults if absent in Settings):
          - SCORE_AI_DELTA_MULTIPLIER (default 1.0)
          - SCORE_AI_MAX_ABS_DELTA_POINTS (default 18.0)
        """
        multiplier = float(getattr(settings, "SCORE_AI_DELTA_MULTIPLIER", 1.0))
        max_abs = float(getattr(settings, "SCORE_AI_MAX_ABS_DELTA_POINTS", 18.0))

        scaled = float(ai_delta) * multiplier
        capped = _clamp(scaled, -max_abs, +max_abs)
        final_score = _clamp(base_score + capped, 0.0, 100.0)
        log.debug("[SCORING][AI] base=%.2f + ai=%.2f → final=%.2f", base_score, capped, final_score)
        return final_score

    def _weights(self) -> Dict[str, float]:
        """Read weights from Settings, falling back to robust defaults."""
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
        """
        Extract raw feature values from a candidate row.

        Expected keys in `item` (best effort; default 0.0 when missing):
          - "liqUsd": float
          - "vol24h": float
          - "pairCreatedAt": timestamp (ms)
          - "pct5m", "pct1h", "pct24h": recent percent changes (signed)
          - "txns": dict (buy/sell counts)
        """
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
        """
        Return a compact momentum score in [0..1] using a smooth logistic transform.

        Design
        ------
        - Short horizon has the highest weight for very short-term trading.
        - Guard against extreme spikes by saturating with a logistic mapping.
        """
        def squash(pct: float) -> float:
            # 0 at approx -20%, 0.5 at 0%, 1 at approx +20% (smoothly)
            return 1.0 / (1.0 + math.exp(-pct / 5.0))

        s5 = squash(p5)
        s1 = squash(h1)
        s24 = squash(h24)

        return float(0.6 * s5 + 0.3 * s1 + 0.1 * s24)
