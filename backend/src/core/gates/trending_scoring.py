# backend/src/core/gates/trending_scoring.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

from src.configuration.config import settings
from src.core.structures.structures import Candidate
from src.core.utils.format_utils import _age_hours, _format, _num, _tail
from src.core.utils.math_utils import _clamp, _squash_pct
from src.core.utils.trending_utils import _momentum_ok, _has_valid_intraday_bars, _buy_sell_score
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class FeatureValues:
    """Raw features used by the statistics scorer."""
    liquidity_usd: float
    volume_24h_usd: float
    age_hours: float
    momentum_score: float
    order_flow_score: float


@dataclass
class FeatureScalers:
    """
    Scalers for each feature.
    Provides a cohesive place to fit/transform consistently.
    """
    liquidity_usd: RobustMinMax
    volume_24h_usd: RobustMinMax
    age_hours: RobustMinMax
    momentum_score: RobustMinMax
    order_flow_score: RobustMinMax

    @classmethod
    def new_unfitted(cls) -> "FeatureScalers":
        return cls(
            liquidity_usd=RobustMinMax(),
            volume_24h_usd=RobustMinMax(),
            age_hours=RobustMinMax(),
            momentum_score=RobustMinMax(),
            order_flow_score=RobustMinMax(),
        )

    def fit_from_features(self, features: Sequence[FeatureValues]) -> None:
        """Fit each scaler from a cohort of feature rows."""
        self.liquidity_usd.fit([f.liquidity_usd for f in features])
        self.volume_24h_usd.fit([f.volume_24h_usd for f in features])
        self.age_hours.fit([f.age_hours for f in features])
        self.momentum_score.fit([f.momentum_score for f in features])


@dataclass(frozen=True)
class ScoringWeights:
    """Per-feature weights for the statistics score."""
    liquidity_weight: float
    volume_weight: float
    age_weight: float
    momentum_weight: float
    order_flow_weight: float

    @classmethod
    def from_settings(cls) -> "ScoringWeights":
        return cls(
            liquidity_weight=float(settings.SCORE_WEIGHT_LIQUIDITY),
            volume_weight=float(settings.SCORE_WEIGHT_VOLUME),
            age_weight=float(settings.SCORE_WEIGHT_AGE),
            momentum_weight=float(settings.SCORE_WEIGHT_MOMENTUM),
            order_flow_weight=float(settings.SCORE_WEIGHT_ORDER_FLOW),
        )

    @property
    def total(self) -> float:
        return (
                self.liquidity_weight
                + self.volume_weight
                + self.age_weight
                + self.momentum_weight
                + self.order_flow_weight
        )


class RobustMinMax:
    """
    Robust linear scaler based on percentiles to mitigate outliers.

    After `fit`, `transform(x)` returns values within [0.0, 1.0].

    Notes:
        - NaN values in `fit` input are ignored.
        - If the percentile span collapses (b <= a), a minimal margin is added
          to avoid division by zero.
    """

    def __init__(self, lower_percentile: float = 5.0, upper_percentile: float = 95.0) -> None:
        if not (0.0 <= lower_percentile < upper_percentile <= 100.0):
            raise ValueError("Percentile bounds must satisfy 0.0 <= lower < upper <= 100.0")
        self._lower_percentile = lower_percentile
        self._upper_percentile = upper_percentile
        self._a: Optional[float] = None
        self._b: Optional[float] = None

    @staticmethod
    def _percentile(sorted_values: Sequence[float], p: float) -> float:
        """Compute the p-th percentile (0..100) from a sorted array using linear interpolation."""
        if not sorted_values:
            return 0.0
        k = (len(sorted_values) - 1) * (p / 100.0)
        floor_index = math.floor(k)
        ceil_index = math.ceil(k)
        if floor_index == ceil_index:
            return float(sorted_values[int(k)])
        d0 = float(sorted_values[int(floor_index)]) * (ceil_index - k)
        d1 = float(sorted_values[int(ceil_index)]) * (k - floor_index)
        return d0 + d1

    def fit(self, values: Sequence[float]) -> RobustMinMax:
        """Fit the scaler from a sequence of numeric values (NaNs ignored)."""
        cleaned_values = [float(v) for v in values if not math.isnan(float(v))]
        cleaned_values.sort()
        if not cleaned_values:
            self._a = 0.0
            self._b = 1.0
            return self

        a = self._percentile(cleaned_values, self._lower_percentile)
        b = self._percentile(cleaned_values, self._upper_percentile)
        if b <= a:
            b = a + 1.0

        self._a, self._b = float(a), float(b)
        return self

    def transform(self, value: float) -> float:
        """Normalize a value to [0.0, 1.0] using fitted percentiles."""
        a = 0.0 if self._a is None else self._a
        b = 1.0 if self._b is None else self._b
        normalized = (float(value) - a) / (b - a)
        return _clamp(normalized, 0.0, 1.0)


class ScoringEngine:
    """
    Statistics scoring engine.

    Terminology:
        - statistics_score ∈ [0..100]  (previously `statScore`)
        - entry_score       ∈ [0..100]  (statistics_score + AI delta)

    Workflow:
        Candidate -> FeatureValues -> Robust normalization -> Weighted sum
    """

    def __init__(self) -> None:
        self._scalers: FeatureScalers = FeatureScalers.new_unfitted()
        self._weights: ScoringWeights = ScoringWeights.from_settings()

    def fit(self, cohort: Sequence[Candidate]) -> ScoringEngine:
        """
        Fit internal scalers on a cohort of candidates.

        Args:
            cohort: Structured candidates.
        """
        feature_rows = [self._compute_raw_features(c) for c in cohort]
        self._scalers.fit_from_features(feature_rows)
        log.debug("[TREND][SCORING][FIT] fitted_scalers=5 candidates=%d", len(feature_rows))
        return self

    def stat_score(self, candidate: Candidate) -> float:
        """
        Compute the statistics score (pre-AI) in [0.0, 100.0].

        Args:
            candidate: Structured candidate.

        Returns:
            Statistics score in [0.0, 100.0].
        """
        f = self._compute_raw_features(candidate)

        n_liq = self._scalers.liquidity_usd.transform(f.liquidity_usd)
        n_vol = self._scalers.volume_24h_usd.transform(f.volume_24h_usd)
        n_age = 1.0 - self._scalers.age_hours.transform(f.age_hours)
        n_mom = self._scalers.momentum_score.transform(f.momentum_score)
        n_flow = self._scalers.order_flow_score.transform(f.order_flow_score)

        w = self._weights
        weighted_sum = (
                w.liquidity_weight * n_liq
                + w.volume_weight * n_vol
                + w.age_weight * n_age
                + w.momentum_weight * n_mom
                + w.order_flow_weight * n_flow
        )
        total_weight = w.total if w.total > 0.0 else 1e-9

        score = 100.0 * (weighted_sum / total_weight)
        score = _clamp(score, 0.0, 100.0)

        symbol_display = candidate.dexscreener_token_information.base_token.symbol
        log.debug(
            "[TREND][SCORING][STAT] symbol=%s score=%.2f "
            "f={liq:%.0f,vol:%.0f,age:%.1f,mom:%.3f,flow:%.3f} "
            "n={liq:%.3f,vol:%.3f,age:%.3f,mom:%.3f,flow:%.3f}",
            symbol_display,
            score,
            f.liquidity_usd, f.volume_24h_usd, f.age_hours, f.momentum_score, f.order_flow_score,
            n_liq, n_vol, n_age, n_mom, n_flow
        )
        return score

    def base_score(self, candidate: Candidate) -> float:
        """Backward-compatible alias for `stat_score`."""
        return self.stat_score(candidate)

    def apply_ai_adjustment(self, statistics_score: float, ai_delta_model_output: float) -> float:
        """
        Apply AI delta on top of the statistics score with clamping.

        entry_score = clamp(
            statistics_score + clamp(ai_delta_model_output * SCORE_AI_DELTA_MULTIPLIER,
                                     ±SCORE_AI_MAX_ABS_DELTA_POINTS),
            0, 100
        )
        """
        multiplier = float(settings.SCORE_AI_DELTA_MULTIPLIER)
        max_abs_points = float(settings.SCORE_AI_MAX_ABS_DELTA_POINTS)

        scaled_delta = ai_delta_model_output * multiplier
        bounded_delta = _clamp(scaled_delta, -max_abs_points, +max_abs_points)
        entry_score = _clamp(statistics_score + bounded_delta, 0.0, 100.0)

        log.debug(
            "[TREND][SCORING][AI] stat=%.2f ai_delta=%.2f -> entry=%.2f",
            statistics_score,
            bounded_delta,
            entry_score,
        )
        return entry_score

    def _compute_raw_features(self, candidate: Candidate) -> FeatureValues:
        """
        Extract and compute raw features used by the statistics scorer.
        Strictly uses the structured `Candidate` to avoid dict-based access.
        """
        token_information = candidate.dexscreener_token_information
        liquidity_usd = float(token_information.liquidity.usd)
        volume_24h_usd = float(token_information.volume.h24)

        age_hours = (
            float(token_information.age_hours)
            if token_information.age_hours > 0.0
            else float(_age_hours(int(token_information.pair_created_at)))
        )

        percent_5m = float(_num(token_information.price_change.m5) or 0.0)
        percent_1h = float(_num(token_information.price_change.h1) or 0.0)
        percent_6h = float(_num(token_information.price_change.h6) or 0.0)
        percent_24h = float(_num(token_information.price_change.h24) or 0.0)
        momentum_score = self._blend_momentum(percent_5m, percent_1h, percent_6h, percent_24h)
        flow_score = _buy_sell_score(token_information.txns)

        return FeatureValues(
            liquidity_usd=liquidity_usd,
            volume_24h_usd=volume_24h_usd,
            age_hours=age_hours,
            momentum_score=momentum_score,
            order_flow_score=flow_score
        )

    @staticmethod
    def _blend_momentum(percent_5m: float, percent_1h: float, percent_6h, percent_24h: float) -> float:
        """
        Blend short/medium/long momentum with a logistic squash per horizon.

        Returns:
            Blended momentum score within [0.0, 1.0].
        """
        s5 = _squash_pct(percent_5m)
        s1 = _squash_pct(percent_1h)
        s6 = _squash_pct(percent_6h)
        s24 = _squash_pct(percent_24h)
        return 0.6 * s5 + 0.4 * s1 + 0.25 * s6 + 0.1 * s24


@dataclass(frozen=True)
class QualityContext:
    """Context breakdown for the quality score decision."""
    liq: float
    vol5m: float
    vol1h: float
    vol6h: float
    vol24h: float
    age_h: float
    p5: float
    p1: float
    p6: float
    p24: float
    momentum: float
    liq_score: float
    vol_score: float
    order_flow_score: float


@dataclass(frozen=True)
class QualityGateResult:
    """Result of the quality gate decision."""
    admissible: bool
    score: float
    reason: str
    context: QualityContext


def _compute_quality_score(candidate: Candidate) -> QualityGateResult:
    """
    Gate #1 — quality score & admissibility before any ranking.

    Operates on a structured `Candidate` and avoids dict reads entirely.
    """
    token_information = candidate.dexscreener_token_information
    base_token = token_information.base_token

    liquidity_usd = float(token_information.liquidity.usd)

    volume_5m_usd = float(token_information.volume.m5)
    volume_1h_usd = float(token_information.volume.h1)
    volume_6h_usd = float(token_information.volume.h6)
    volume_24h_usd = float(token_information.volume.h24)

    pct_5m = _num(token_information.price_change.m5)
    pct_1h = _num(token_information.price_change.h1)
    pct_6h = _num(token_information.price_change.h6)
    pct_24h = _num(token_information.price_change.h24)

    age_hours = (
        float(token_information.age_hours)
        if token_information.age_hours > 0.0
        else float(_age_hours(int(token_information.pair_created_at)))
    )

    order_flow_score = _buy_sell_score(token_information.txns)

    min_liquidity_usd = float(settings.TREND_MIN_LIQ_USD)

    min_volume_5m_usd = float(settings.TREND_MIN_VOL5M_USD)
    min_volume_1h_usd = float(settings.TREND_MIN_VOL1H_USD)
    min_volume_6h_usd = float(settings.TREND_MIN_VOL6H_USD)
    min_volume_24h_usd = float(settings.TREND_MIN_VOL24H_USD)

    min_age_hours = float(settings.DEXSCREENER_MIN_AGE_HOURS)
    max_age_hours = float(settings.DEXSCREENER_MAX_AGE_HOURS)

    if liquidity_usd < min_liquidity_usd:
        log.debug("[TREND][QUALITY][DROP:LOW_LIQ] %s — %.0f < %.0f", base_token.symbol, liquidity_usd,
                  min_liquidity_usd)
        return QualityGateResult(
            admissible=False,
            score=0.0,
            reason="low_liquidity",
            context=QualityContext(
                liq=liquidity_usd,
                vol5m=volume_5m_usd, vol1h=volume_1h_usd, vol6h=volume_6h_usd, vol24h=volume_24h_usd,
                age_h=age_hours,
                p5=float(pct_5m or 0.0), p1=float(pct_1h or 0.0), p6=float(pct_6h or 0.0), p24=float(pct_24h or 0.0),
                momentum=0.0, liq_score=0.0, vol_score=0.0, order_flow_score=order_flow_score
            ),
        )

    if volume_24h_usd < min_volume_24h_usd:
        log.debug("[TREND][QUALITY][DROP:LOW_VOL] %s — %.0f < %.0f", base_token.symbol, volume_24h_usd,
                  min_volume_24h_usd)
        return QualityGateResult(
            admissible=False,
            score=0.0,
            reason="low_volume",
            context=QualityContext(
                liq=liquidity_usd,
                vol5m=volume_5m_usd, vol1h=volume_1h_usd, vol6h=volume_6h_usd, vol24h=volume_24h_usd,
                age_h=age_hours,
                p5=float(pct_5m or 0.0), p1=float(pct_1h or 0.0), p6=float(pct_6h or 0.0), p24=float(pct_24h or 0.0),
                momentum=0.0, liq_score=0.0, vol_score=0.0, order_flow_score=order_flow_score
            ),
        )

    if age_hours < min_age_hours or age_hours > max_age_hours:
        log.debug(
            "[TREND][QUALITY][DROP:AGE] %s — %.1fh not in [%.1f .. %.1f]",
            base_token.symbol, age_hours, min_age_hours, max_age_hours,
        )
        return QualityGateResult(
            admissible=False,
            score=0.0,
            reason="age_out_of_bounds",
            context=QualityContext(
                liq=liquidity_usd,
                vol5m=volume_5m_usd, vol1h=volume_1h_usd, vol6h=volume_6h_usd, vol24h=volume_24h_usd,
                age_h=age_hours,
                p5=float(pct_5m or 0.0), p1=float(pct_1h or 0.0), p6=float(pct_6h or 0.0), p24=float(pct_24h or 0.0),
                momentum=0.0, liq_score=0.0, vol_score=0.0, order_flow_score=order_flow_score
            ),
        )

    if not _momentum_ok(pct_5m, pct_1h, pct_6h, pct_24h):
        log.debug(
            "[TREND][QUALITY][DROP:MOMENTUM] %s — m5=%s m1=%s m6=%s m24=%s",
            base_token.symbol, _format(pct_5m), _format(pct_1h), _format(pct_6h), _format(pct_24h)
        )
        return QualityGateResult(
            admissible=False,
            score=0.0,
            reason="choppy_or_spiky",
            context=QualityContext(
                liq=liquidity_usd,
                vol5m=volume_5m_usd, vol1h=volume_1h_usd, vol6h=volume_6h_usd, vol24h=volume_24h_usd,
                age_h=age_hours,
                p5=float(pct_5m or 0.0), p1=float(pct_1h or 0.0), p6=float(pct_6h or 0.0), p24=float(pct_24h or 0.0),
                momentum=0.0, liq_score=0.0, vol_score=0.0, order_flow_score=order_flow_score
            ),
        )

    s5 = _squash_pct(float(pct_5m or 0.0))
    s1 = _squash_pct(float(pct_1h or 0.0))
    s6 = _squash_pct(float(pct_6h or 0.0))
    s24 = _squash_pct(float(pct_24h or 0.0))

    momentum_score = 0.6 * s5 + 0.4 * s1 + 0.25 * s6 + 0.1 * s24

    liquidity_component = min(1.0, liquidity_usd / (min_liquidity_usd * 4.0))

    volume_5m_component = min(1.0, volume_5m_usd / (min_volume_5m_usd * 4.0))
    volume_1h_component = min(1.0, volume_1h_usd / (min_volume_1h_usd * 4.0))
    volume_6h_component = min(1.0, volume_6h_usd / (min_volume_6h_usd * 4.0))
    volume_24h_component = min(1.0, volume_24h_usd / (min_volume_24h_usd * 4.0))
    volume_component = (
            0.4 * volume_5m_component
            + 0.3 * volume_1h_component
            + 0.2 * volume_6h_component
            + 0.1 * volume_24h_component
    )

    quality_score = 100.0 * (
            0.45 * momentum_score
            + 0.25 * liquidity_component
            + 0.30 * volume_component
    )

    context = QualityContext(
        liq=liquidity_usd,
        vol5m=volume_5m_usd,
        vol1h=volume_1h_usd,
        vol6h=volume_6h_usd,
        vol24h=volume_24h_usd,
        age_h=age_hours,
        p5=float(pct_5m or 0.0),
        p1=float(pct_1h or 0.0),
        p6=float(pct_6h or 0.0),
        p24=float(pct_24h or 0.0),
        momentum=momentum_score,
        liq_score=liquidity_component,
        vol_score=volume_component,
        order_flow_score=order_flow_score
    )

    return QualityGateResult(admissible=True, score=quality_score, reason="ok", context=context)


def _attach_quality_score(candidate: Candidate, score: float) -> None:
    """
    Attach the computed quality score to the candidate via attribute assignment.

    If the attribute is not assignable, a verbose log is emitted; no dict fallback.
    """
    try:
        setattr(candidate, "quality_score", float(score))
    except Exception:
        log.debug(
            "[TREND][QUALITY][WARN] Unable to set quality_score attribute on type=%s",
            type(candidate).__name__,
        )


def apply_quality_filter(rows: Sequence[Candidate]) -> List[Candidate]:
    """
    Gate #1 — keep only candidates above the minimal quality score and
    with valid intraday bars (m1/m5 present).

    Args:
        rows: Structured candidates.

    Returns:
        A filtered list of candidates. Each kept candidate receives `quality_score`
        (attribute) when possible.
    """
    if not rows:
        log.info("[TREND][QUALITY] 0 candidates provided to gate #1.")
        return []

    minimum_quality_score = float(settings.SCORE_MIN_QUALITY)
    kept: List[Candidate] = []

    for candidate in rows:
        result = _compute_quality_score(candidate)
        _attach_quality_score(candidate, result.score)

        base_token = candidate.dexscreener_token_information.base_token
        symbol_for_logs = base_token.symbol
        short_address = _tail(base_token.address)

        if result.admissible and result.score >= minimum_quality_score:
            if not _has_valid_intraday_bars(candidate):
                log.debug("[TREND][QUALITY][DROP:BARS] %s — intraday bars missing (m1/m5=NA)", base_token.symbol)
                continue

            kept.append(candidate)
            log.debug(
                "[TREND][QUALITY][KEEP] %s (%s) — quality=%.2f ≥ %.2f",
                symbol_for_logs, short_address, result.score, minimum_quality_score,
            )
        else:
            log.debug(
                "[TREND][QUALITY][DROP:SCORE] %s (%s) — quality=%.2f < %.2f ctx=%s",
                symbol_for_logs, short_address, result.score, minimum_quality_score, result.context,
            )

    if not kept:
        log.info("[TREND][QUALITY] 0 candidates passed gate #1.")
    else:
        log.info("[TREND][QUALITY] %d/%d candidates passed gate #1.", len(kept), len(rows))

    return kept
