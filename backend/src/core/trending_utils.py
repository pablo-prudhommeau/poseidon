# src/core/trending_utils.py
from __future__ import annotations
import time
from math import isnan
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from src.configuration.config import settings
from src.persistence.db import SessionLocal
from src.persistence.models import Trade
from src.integrations.dexscreener_client import fetch_prices_by_addresses

from src.logging.logger import get_logger

log = get_logger(__name__)

def _fmt(v):
    return "NA" if v is None else f"{v:.2f}"

def _tail(addr: str, n: int = 6) -> str:
    a = (addr or "").lower()
    return a[-n:] if len(a) >= n else a

def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return None if isnan(v) else v
    except Exception:
        return None

def _age_hours(ms: int) -> float:
    if not ms or ms <= 0:
        return 0.0
    return max(0.0, (time.time() - (ms / 1000.0)) / 3600.0)

def _excluded_symbol(symbol: str, exclude_stables: bool, exclude_majors: bool) -> bool:
    stables = {"USDT","USDC","DAI","USDS","TUSD","FDUSD","PYUSD","USDV","USDD"}
    majors  = {"ETH","WETH","WBTC","BTC","STETH","WSTETH","BNB","MKR"}
    s = (symbol or "").upper()
    if exclude_stables and s in stables:
        return True
    if exclude_majors and s in majors:
        return True
    return False

def _passes_thresholds(it: Dict[str, Any], interval: str, th5: float, th1: float, th24: float) -> bool:
    p5  = _num(it.get("pct5m"))
    p1  = _num(it.get("pct1h"))
    p24 = _num(it.get("pct24h"))
    if interval == "5m":
        return (p5 is not None and p5 >= th5) or (p24 is not None and p24 >= th24)
    if interval == "1h":
        return (p1 is not None and p1 >= th1) or (p24 is not None and p24 >= th24)
    return (p24 is not None and p24 >= th24)


# ---------- baseline filters ----------
def filter_strict(
        rows: List[Dict[str, Any]],
        *, interval: str,
        min_vol_usd: float, min_liq_usd: float,
        th5: float, th1: float, th24: float,
        exclude_stables: bool, exclude_majors: bool,
        max_results: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    kept: List[Dict[str, Any]] = []
    rej = {"excl": 0, "lowvol": 0, "lowliq": 0, "lowpct": 0}
    for it in rows:
        sym = it.get("symbol")
        vol = float(it.get("vol24h") or 0.0)
        liq = float(it.get("liqUsd") or 0.0)
        if _excluded_symbol(sym, exclude_stables, exclude_majors):
            rej["excl"] += 1; continue
        if vol < min_vol_usd:
            rej["lowvol"] += 1; continue
        if liq < min_liq_usd:
            rej["lowliq"] += 1; continue
        if not _passes_thresholds(it, interval, th5, th1, th24):
            rej["lowpct"] += 1; continue
        kept.append(it)
        if len(kept) >= max_results:
            break
    for it in kept:
        sym = (it.get("symbol") or "").upper()
        addr = _tail(it.get("address") or "")
        vol  = float(it.get("vol24h") or 0.0)
        liq  = float(it.get("liqUsd") or 0.0)
        p5   = _num(it.get("pct5m"))
        p1   = _num(it.get("pct1h"))
        p24  = _num(it.get("pct24h"))

        via = "24h"
        if interval == "5m" and p5 is not None and p5 >= th5: via = "5m"
        elif interval == "1h" and p1 is not None and p1 >= th1: via = "1h"
        elif p24 is not None and p24 >= th24: via = "24h"

        log.debug(
            "[BASELINE:KEEP] %s (%s) — vol=%.0f≥%.0f liq=%.0f≥%.0f "
            "p5=%s(th=%.2f) p1=%s(th=%.2f) p24=%s(th=%.2f) via=%s",
            sym, addr, vol, min_vol_usd, liq, min_liq_usd,
            _fmt(p5), th5, _fmt(p1), th1, _fmt(p24), th24, via
        )

    return kept, rej

def softfill(
        universe: List[Dict[str, Any]],
        kept: List[Dict[str, Any]],
        *, need_min: int, min_vol_usd: float, min_liq_usd: float, sort_key: str
) -> List[Dict[str, Any]]:
    if need_min <= 0 or len(kept) >= need_min:
        return kept
    pool = [
        r for r in universe
        if (r not in kept)
           and float(r.get("vol24h") or 0.0) >= min_vol_usd
           and float(r.get("liqUsd") or 0.0) >= min_liq_usd
           and ((_num(r.get("pct1h")) or 0.0) >= 0.0 or (_num(r.get("pct24h")) or 0.0) >= 0.0)
    ]
    key = sort_key if sort_key in {"vol24h", "liqUsd"} else "vol24h"
    pool.sort(key=lambda x: float(x.get(key) or 0.0), reverse=True)
    for r in pool:
        if len(kept) >= need_min:
            break
        kept.append(r)
    return kept


# ---------- quality analysis ----------
def _buy_sell_score(txns: dict) -> float:
    if not isinstance(txns, dict):
        return 0.5
    bucket = txns.get("h1") or txns.get("h24") or {}
    b = float(bucket.get("buys")  or 0.0)
    s = float(bucket.get("sells") or 0.0)
    tot = b + s
    return 0.5 if tot <= 0 else b / tot

def _momentum_ok(p5: Optional[float], p1: Optional[float], p24: Optional[float]) -> bool:
    cap_m5 = float(getattr(settings, "DS_MAX_ABS_M5_PCT", 25.0))
    cap_h1 = float(getattr(settings, "DS_MAX_ABS_H1_PCT", 60.0))
    if p5 is not None and abs(p5) > cap_m5:
        return False
    if p1 is not None and abs(p1) > cap_h1:
        return False
    vals = [v for v in (p5, p1, p24) if v is not None]
    if len(vals) >= 2 and any(vals[i] > vals[i + 1] + 2.0 for i in range(len(vals) - 1)):
        return False
    return True

def quality_score(it: Dict[str, Any]) -> Tuple[bool, float, str, Dict[str, float]]:
    liq = float(it.get("liqUsd") or 0.0)
    vol = float(it.get("vol24h") or 0.0)
    p5  = _num(it.get("pct5m"))
    p1  = _num(it.get("pct1h"))
    p24 = _num(it.get("pct24h"))
    age = _age_hours(int(it.get("pairCreatedAt") or 0))
    bs  = _buy_sell_score(it.get("txns") or {})

    min_liq = float(getattr(settings, "TREND_MIN_LIQ_USD", 50_000.0))
    min_vol = float(getattr(settings, "TREND_MIN_VOL_USD", 100_000.0))
    min_age = float(getattr(settings, "DS_MIN_AGE_HOURS", 2.0))
    max_age = float(getattr(settings, "DS_MAX_AGE_HOURS", 240.0))

    if liq < min_liq: return False, 0.0, "low_liquidity", {"liq": liq, "vol": vol, "age_h": age, "bs": bs, "p5": p5, "p1": p1, "p24": p24}
    if vol < min_vol: return False, 0.0, "low_volume",    {"liq": liq, "vol": vol, "age_h": age, "bs": bs, "p5": p5, "p1": p1, "p24": p24}
    if age < min_age or age > max_age:
        return False, 0.0, "age_out_of_bounds", {"liq": liq, "vol": vol, "age_h": age, "bs": bs, "p5": p5, "p1": p1, "p24": p24}
    if not _momentum_ok(p5, p1, p24):
        return False, 0.0, "choppy_or_spiky",   {"liq": liq, "vol": vol, "age_h": age, "bs": bs, "p5": p5, "p1": p1, "p24": p24}

    m5 = max(0.0, p5 or 0.0)
    m1 = max(0.0, p1 or 0.0)
    m24 = max(0.0, p24 or 0.0)
    momentum = (m5 * 0.2) + (m1 * 0.4) + (m24 * 0.4)
    liq_score = min(1.0, liq / (min_liq * 4.0))
    vol_score = min(1.0, vol / (min_vol * 4.0))
    score = 100.0 * (0.45 * momentum / 100.0 + 0.25 * liq_score + 0.20 * vol_score + 0.10 * bs)

    ctx = {
        "liq": liq, "vol": vol, "age_h": age, "bs": bs,
        "p5": p5, "p1": p1, "p24": p24,
        "momentum": momentum, "liq_score": liq_score, "vol_score": vol_score
    }
    return True, float(score), "ok", ctx

def apply_quality_filter(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not candidates:
        return []
    min_score = float(getattr(settings, "DS_MIN_QUALITY_SCORE", 12.0))
    out: List[Dict[str, Any]] = []
    for it in candidates:
        ok, s, _, ctx = quality_score(it)
        if ok and s >= min_score:
            it["qualityScore"] = s
            out.append(it)

            sym  = (it.get("symbol") or "").upper()
            addr = _tail(it.get("address") or "")
            log.debug(
                "[QUALITY:KEEP] %s (%s) — score=%.2f≥%.2f  liq=%.0f vol=%.0f "
                "age=%.1fh bs=%.2f  m5=%s m1=%s m24=%s  components(momentum=%.2f liqSc=%.2f volSc=%.2f)",
                sym, addr, s, min_score,
                ctx["liq"], ctx["vol"], ctx["age_h"], ctx["bs"],
                _fmt(ctx["p5"]), _fmt(ctx["p1"]), _fmt(ctx["p24"]),
                ctx["momentum"], ctx["liq_score"], ctx["vol_score"]
            )
    return out


# ---------- guards / db ----------
def recently_traded(address: str, minutes: int = 45) -> bool:
    if not address:
        return False
    with SessionLocal() as db:
        q = select(Trade).where(Trade.address == address.lower()).order_by(Trade.created_at.desc())
        t = db.execute(q).scalars().first()
        if not t:
            return False
        return (datetime.utcnow() - t.created_at) < timedelta(minutes=minutes)


# ---------- pricing ----------
def preload_best_prices(addresses: List[str]) -> Dict[str, float]:
    uniq = [a.lower() for a in dict.fromkeys([x for x in addresses if x])]
    if not uniq:
        return {}
    return asyncio_run_fetch(uniq)

def asyncio_run_fetch(addrs: List[str]) -> Dict[str, float]:
    # Isoler asyncio.run pour éviter les imports en haut
    import asyncio  # local import pour rester compact
    return asyncio.run(fetch_prices_by_addresses(addrs))
