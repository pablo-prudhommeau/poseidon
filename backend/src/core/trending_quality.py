from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src.configuration.config import settings
from src.core.trending_utils import _num, _age_hours, _buy_sell_score, _momentum_ok, _tail, _has_valid_intraday_bars, \
    _format
from src.logging.logger import get_logger

log = get_logger(__name__)


def _compute_quality_score(it: Dict[str, Any]) -> Tuple[bool, float, str, Dict[str, float]]:
    """Compute a quality score and decision for a candidate."""
    liq = float(it.get("liqUsd") or 0.0)
    vol = float(it.get("vol24h") or 0.0)
    p5 = _num(it.get("pct5m"))
    p1 = _num(it.get("pct1h"))
    p24 = _num(it.get("pct24h"))
    age = _age_hours(int(it.get("pairCreatedAt") or 0))
    bs = _buy_sell_score(it.get("txns") or {})

    min_liq = float(settings.TREND_MIN_LIQ_USD)
    min_vol = float(settings.TREND_MIN_VOL_USD)
    min_age = float(settings.DEXSCREENER_MIN_AGE_HOURS)
    max_age = float(settings.DEXSCREENER_MAX_AGE_HOURS)

    if liq < min_liq:
        log.debug("[QUALITY:LOW_LIQ] %s — %.0f < %.0f", it.get("symbol"), liq, min_liq)
        return (False, 0.0, "low_liquidity",
                {"liq": liq, "vol": vol, "age_h": age, "bs": bs, "p5": p5, "p1": p1, "p24": p24})
    if vol < min_vol:
        log.debug("[QUALITY:LOW_VOL] %s — %.0f < %.0f", it.get("symbol"), vol, min_vol)
        return (False, 0.0, "low_volume",
                {"liq": liq, "vol": vol, "age_h": age, "bs": bs, "p5": p5, "p1": p1, "p24": p24})
    if age < min_age or age > max_age:
        log.debug("[QUALITY:AGE_OUT] %s — %.1fh not in [%.1f..%.1f]", it.get("symbol"), age, min_age, max_age)
        return (False, 0.0, "age_out_of_bounds",
                {"liq": liq, "vol": vol, "age_h": age, "bs": bs, "p5": p5, "p1": p1, "p24": p24})
    if not _momentum_ok(p5, p1, p24):
        log.debug("[QUALITY:CHOPPY] %s — m5=%s m1=%s m24=%s", it.get("symbol"), _format(p5), _format(p1), _format(p24))
        return (False, 0.0, "choppy_or_spiky",
                {"liq": liq, "vol": vol, "age_h": age, "bs": bs, "p5": p5, "p1": p1, "p24": p24})

    m5 = max(0.0, p5 or 0.0)
    m1 = max(0.0, p1 or 0.0)
    m24 = max(0.0, p24 or 0.0)
    momentum = (m5 * 0.2) + (m1 * 0.4) + (m24 * 0.4)
    liq_score = min(1.0, liq / (min_liq * 4.0))
    vol_score = min(1.0, vol / (min_vol * 4.0))
    score = 100.0 * (0.45 * momentum / 100.0 + 0.25 * liq_score + 0.20 * vol_score + 0.10 * bs)

    ctx = {
        "liq": liq,
        "vol": vol,
        "age_h": age,
        "bs": bs,
        "p5": p5,
        "p1": p1,
        "p24": p24,
        "momentum": momentum,
        "liq_score": liq_score,
        "vol_score": vol_score,
    }

    return True, float(score), "ok", ctx


def apply_quality_filter(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only candidates above the minimum quality score."""
    if not candidates:
        return []
    min_score = float(settings.DEXSCREENER_MIN_QUALITY_SCORE)
    out: List[Dict[str, Any]] = []
    for candidate in candidates:
        ok, score, _, ctx = _compute_quality_score(candidate)
        sym = (candidate.get("symbol") or "").upper()
        addr = _tail(candidate.get("address") or "")
        candidate["qualityScore"] = score
        if ok and score >= min_score:
            if not _has_valid_intraday_bars(candidate):
                log.debug("[QUALITY:DROP] %s — intraday bars missing (m1/m5=NA)", candidate.get("symbol"))
                continue
            out.append(candidate)
            log.debug(
                "[QUALITY:KEEP] %s (%s) — score=%.2f≥%.2f  liq=%.0f vol=%.0f age=%.1fh bs=%.2f  m5=%s m1=%s m24=%s  components(momentum=%.2f liqSc=%.2f volSc=%.2f)",
                sym,
                addr,
                score,
                min_score,
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

    return out
