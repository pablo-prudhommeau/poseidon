from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from math import isnan
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from src.configuration.config import settings
from src.core.utils import timezone_now
from src.integrations.dexscreener_client import fetch_prices_by_addresses_sync
from src.logging.logger import get_logger
from src.persistence.db import _session
from src.persistence.models import Trade

log = get_logger(__name__)


def _format(value: Optional[float]) -> str:
    """Format a float for logs, or 'NA' if missing."""
    return "NA" if value is None else f"{value:.2f}"


def _tail(address: str, n: int = 6) -> str:
    """Return last n characters of a lowercased address (for concise logs)."""
    addr = (address or "").lower()
    return addr[-n:] if len(addr) >= n else addr


def _num(x: Any) -> Optional[float]:
    """Parse a number, returning None on invalid/NaN values."""
    try:
        value = float(x)
        return None if isnan(value) else value
    except Exception:
        return None


def _age_hours(ms: int) -> float:
    """Age in hours from a unix ms timestamp."""
    if not ms or ms <= 0:
        return 0.0
    return max(0.0, (time.time() - (ms / 1000.0)) / 3600.0)


def _passes_thresholds(item: Dict[str, Any], interval: str, th5: float, th1: float, th24: float) -> bool:
    """Check percent-change thresholds depending on the selected interval."""
    p5 = _num(item.get("pct5m"))
    p1 = _num(item.get("pct1h"))
    p24 = _num(item.get("pct24h"))
    if interval == "5m":
        return (p5 is not None and p5 >= th5) or (p24 is not None and p24 >= th24)
    if interval == "1h":
        return (p1 is not None and p1 >= th1) or (p24 is not None and p24 >= th24)
    return p24 is not None and p24 >= th24


def _is_number(x: Any) -> bool:
    """Return True if x can be interpreted as a finite float."""
    try:
        f = float(x)
        return not math.isnan(f) and not math.isinf(f)
    except Exception:
        return False

def _has_valid_intraday_bars(candidate: dict) -> bool:
    """True if both m1 and m5 are numeric (proxy for fresh OHLCV)."""
    return _is_number(candidate.get("pct5m")) and _is_number(candidate.get("pct1h"))


def _buy_sell_score(txns: dict) -> float:
    """Return the fraction of buys over total transactions in [0.0..1.0]."""
    if not isinstance(txns, dict):
        return 0.5
    bucket = txns.get("h1") or txns.get("h24") or {}
    buys = float(bucket.get("buys") or 0.0)
    sells = float(bucket.get("sells") or 0.0)
    total = buys + sells
    return 0.5 if total <= 0 else buys / total


def _momentum_ok(p5: Optional[float], p1: Optional[float], p24: Optional[float]) -> bool:
    """Conservative sanity checks against spiky/choppy momentum."""
    cap_m5 = float(settings.DEXSCREENER_MAX_ABS_M5_PCT)
    cap_h1 = float(settings.DEXSCREENER_MAX_ABS_H1_PCT)
    if p5 is not None and abs(p5) > cap_m5:
        return False
    if p1 is not None and abs(p1) > cap_h1:
        return False
    values = [v for v in (p5, p1, p24) if v is not None]
    if len(values) >= 2 and any(values[i] > values[i + 1] + 2.0 for i in range(len(values) - 1)):
        return False
    return True


def filter_strict(
        rows: List[Dict[str, Any]],
        *,
        interval: str,
        min_vol_usd: float,
        min_liq_usd: float,
        th5: float,
        th1: float,
        th24: float,
        max_results: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Hard filters for trending candidates; returns (kept, rejection_counts).
    """
    kept: List[Dict[str, Any]] = []
    rejected: Dict[str, int] = {"excl": 0, "lowvol": 0, "lowliq": 0, "lowpct": 0}

    for item in rows:
        symbol = item.get("symbol")
        volume_24h_usd = float(item.get("vol24h") or 0.0)
        liquidity_usd = float(item.get("liqUsd") or 0.0)

        if volume_24h_usd < min_vol_usd:
            log.debug("[BASELINE:REJECT] %s — vol=%.0f<%.0f", symbol, volume_24h_usd, min_vol_usd)
            rejected["lowvol"] += 1
            continue
        if liquidity_usd < min_liq_usd:
            log.debug("[BASELINE:REJECT] %s — liq=%.0f<%.0f", symbol, liquidity_usd, min_liq_usd)
            rejected["lowliq"] += 1
            continue
        if not _passes_thresholds(item, interval, th5, th1, th24):
            log.debug("[BASELINE:REJECT] %s — fails pct thresholds for %s", symbol, interval)
            rejected["lowpct"] += 1
            continue

        kept.append(item)
        if len(kept) >= max_results:
            log.debug("[BASELINE] Reached max results %d", max_results)
            break

    for item in kept:
        symbol_upper = (item.get("symbol") or "").upper()
        short_address = _tail(item.get("address") or "")
        volume_24h_usd = float(item.get("vol24h") or 0.0)
        liquidity_usd = float(item.get("liqUsd") or 0.0)
        p5 = _num(item.get("pct5m"))
        p1 = _num(item.get("pct1h"))
        p24 = _num(item.get("pct24h"))

        via = "24h"
        if interval == "5m" and p5 is not None and p5 >= th5:
            via = "5m"
        elif interval == "1h" and p1 is not None and p1 >= th1:
            via = "1h"
        elif p24 is not None and p24 >= th24:
            via = "24h"

        log.debug(
            "[BASELINE:KEEP] %s (%s) — vol=%.0f≥%.0f liq=%.0f≥%.0f p5=%s(th=%.2f) p1=%s(th=%.2f) p24=%s(th=%.2f) via=%s",
            symbol_upper,
            short_address,
            volume_24h_usd,
            min_vol_usd,
            liquidity_usd,
            min_liq_usd,
            _format(p5),
            th5,
            _format(p1),
            th1,
            _format(p24),
            th24,
            via,
        )

    return kept, rejected


def soft_fill(
        universe: List[Dict[str, Any]],
        kept: List[Dict[str, Any]],
        *,
        need_min: int,
        min_vol_usd: float,
        min_liq_usd: float,
        sort_key: str,
) -> List[Dict[str, Any]]:
    """
    If needed, top up the kept list using a looser pool sorted by a given key.
    """
    if need_min <= 0 or len(kept) >= need_min:
        return kept

    pool = [
        row
        for row in universe
        if (row not in kept)
           and float(row.get("vol24h") or 0.0) >= min_vol_usd
           and float(row.get("liqUsd") or 0.0) >= min_liq_usd
           and ((_num(row.get("pct1h")) or 0.0) >= 0.0 or (_num(row.get("pct24h")) or 0.0) >= 0.0)
    ]
    key = sort_key if sort_key in {"vol24h", "liqUsd"} else "vol24h"
    pool.sort(key=lambda x: float(x.get(key) or 0.0), reverse=True)

    for row in pool:
        if len(kept) >= need_min:
            break
        log.debug(
            "[SOFT-FILL:KEEP] %s — vol=%.0f liq=%.0f p1=%s p24=%s",
            (row.get("symbol") or "").upper(),
            float(row.get("vol24h") or 0.0),
            float(row.get("liqUsd") or 0.0),
            _num(row.get("pct1h")) or 0.0,
            _num(row.get("pct24h")) or 0.0,
            )
        kept.append(row)
    return kept


def recently_traded(address: str, minutes: int = 45) -> bool:
    """Return True if a trade for this address exists more recently than `minutes`."""
    if not address:
        return False
    with _session() as db:
        query = select(Trade).where(Trade.address == address.lower()).order_by(Trade.created_at.desc())
        trade = db.execute(query).scalars().first()
        if not trade:
            return False
        now = timezone_now()
        created = trade.created_at.astimezone()
        return (now - created) < timedelta(minutes=minutes)


def preload_best_prices(addresses: List[str]) -> Dict[str, float]:
    """
    Deduplicate and fetch best prices for a list of addresses (address → price).

    EVM addresses are lowercased; Solana mints keep their original casing.
    """
    if not addresses:
        return {}
    seen: set[str] = set()
    normalized: List[str] = []

    for raw in (a for a in addresses if a):
        key = raw.lower() if raw.startswith("0x") else raw
        if key in seen:
            continue
        seen.add(key)
        normalized.append(key)  # EVM already lower; SOL unchanged

    if not normalized:
        return {}
    return fetch_prices_by_addresses_sync(normalized)
