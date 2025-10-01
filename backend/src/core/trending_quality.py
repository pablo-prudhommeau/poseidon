from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from src.configuration.config import settings
from src.core.trending_utils import (
    _num,
    _age_hours,
    _buy_sell_score,
    _momentum_ok,
    _tail,
    _has_valid_intraday_bars,
    _format,
)
from src.logging.logger import get_logger

log = get_logger(__name__)


def _squash_pct(pct: float) -> float:
    """Map a percent change to [0..1] (≈0 at -20%, 0.5 à 0%, ≈1 à +20%)."""
    return 1.0 / (1.0 + math.exp(-(pct) / 5.0))


def _compute_quality_score(item: Dict[str, Any]) -> Tuple[bool, float, str, Dict[str, float]]:
    """
    Compute an admissibility-oriented quality score for a trending candidate.

    Notes
    -----
    - This score is used as a gate/heuristic before the main ranking.
    - It purposefully does NOT include any Chart AI blending (kept strictly as filtering logic).
    - The score is roughly on a 0..100 scale, combining momentum, liquidity, volume and order-flow proxy.
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
        log.debug("[QUALITY:LOW_LIQUIDITY] %s — %.0f < %.0f", item.get("symbol"), liquidity_usd, min_liquidity_usd)
        return (
            False,
            0.0,
            "low_liquidity",
            {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours, "bs": order_flow,
             "p5": pct_5m, "p1": pct_1h, "p24": pct_24h},
        )

    if volume_24h_usd < min_volume_24h_usd:
        log.debug("[QUALITY:LOW_VOLUME] %s — %.0f < %.0f", item.get("symbol"), volume_24h_usd, min_volume_24h_usd)
        return (
            False,
            0.0,
            "low_volume",
            {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours, "bs": order_flow,
             "p5": pct_5m, "p1": pct_1h, "p24": pct_24h},
        )

    if age_hours < min_age_hours or age_hours > max_age_hours:
        log.debug(
            "[QUALITY:AGE_OUT_OF_BOUNDS] %s — %.1fh not in [%.1f..%.1f]",
            item.get("symbol"),
            age_hours,
            min_age_hours,
            max_age_hours,
        )
        return (
            False,
            0.0,
            "age_out_of_bounds",
            {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours, "bs": order_flow,
             "p5": pct_5m, "p1": pct_1h, "p24": pct_24h},
        )

    if not _momentum_ok(pct_5m, pct_1h, pct_24h):
        log.debug(
            "[QUALITY:CHOPPY_OR_SPIKY] %s — m5=%s m1=%s m24=%s",
            item.get("symbol"),
            _format(pct_5m),
            _format(pct_1h),
            _format(pct_24h),
        )
        return (
            False,
            0.0,
            "choppy_or_spiky",
            {"liq": liquidity_usd, "vol": volume_24h_usd, "age_h": age_hours, "bs": order_flow,
             "p5": pct_5m, "p1": pct_1h, "p24": pct_24h},
        )

    # Momentum component (ignore negatives for a conservative “green momentum only” gate)
    s5 = _squash_pct((pct_5m or 0.0))
    s1 = _squash_pct((pct_1h or 0.0))
    s24 = _squash_pct((pct_24h or 0.0))
    momentum_score = 0.6 * s5 + 0.3 * s1 + 0.1 * s24  # pondération “très court terme”

    # Normalize liquidity / volume around configured minimums; saturate at 1.0
    liquidity_component = min(1.0, liquidity_usd / (min_liquidity_usd * 4.0))
    volume_component = min(1.0, volume_24h_usd / (min_volume_24h_usd * 4.0))

    # Aggregate (0..100)
    quality_score = 100.0 * (
            0.45 * momentum_score
            + 0.25 * liquidity_component
            + 0.20 * volume_component
            + 0.10 * order_flow
    )
    context = {
        "liq": liquidity_usd,
        "vol": volume_24h_usd,
        "age_h": age_hours,
        "bs": order_flow,
        "p5": pct_5m,
        "p1": pct_1h,
        "p24": pct_24h,
        "momentum": momentum_score,
        "liq_score": liquidity_component,
        "vol_score": volume_component,
    }

    return True, float(quality_score), "ok", context


def apply_quality_filter(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Keep only candidates above the minimum quality score and with valid intraday bars.
    Annotates each candidate with 'qualityScore'.
    """
    if not candidates:
        return []

    minimum_quality_score = float(settings.DEXSCREENER_MIN_QUALITY_SCORE)
    kept: List[Dict[str, Any]] = []

    for candidate in candidates:
        is_ok, score, _, ctx = _compute_quality_score(candidate)
        symbol_upper = (candidate.get("symbol") or "").upper()
        short_address = _tail(candidate.get("address") or "")
        candidate["qualityScore"] = score

        if is_ok and score >= minimum_quality_score:
            if not _has_valid_intraday_bars(candidate):
                log.debug("[QUALITY:DROP] %s — intraday bars missing (m1/m5=NA)", candidate.get("symbol"))
                continue

            kept.append(candidate)
            log.debug(
                "[QUALITY:KEEP] %s (%s) — score=%.2f≥%.2f  liq=%.0f vol=%.0f age=%.1fh bs=%.2f  m5=%s m1=%s m24=%s  components(momentum=%.2f liqSc=%.2f volSc=%.2f)",
                symbol_upper,
                short_address,
                score,
                minimum_quality_score,
                ctx["liq"],
                ctx["vol"],
                ctx["age_h"],
                ctx["bs"],
                _format(ctx["p5"]),
                _format(ctx["p1"]),
                _format(ctx["p24"]),
                ctx["momentum"],
                ctx["liq_score"],
                ctx["vol_score"],
            )

    return kept
