# src/offchain/cmc_client.py
from __future__ import annotations
import requests
from typing import List, Dict, Any, Optional
from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)

BASE = "https://dapi.coinmarketcap.com/dex/v1/tokens/trending/list"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://coinmarketcap.com/",
    "Origin": "https://coinmarketcap.com",
    "Accept": "application/json,text/plain,*/*",
}

# -------------------- helpers --------------------
def _float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # NaN -> None
    except Exception:
        return None

def _float0(v: Any) -> float:
    x = _float(v)
    return x if x is not None else 0.0

def _looks_like_evm(addr: str) -> bool:
    return isinstance(addr, str) and addr.startswith("0x") and len(addr) == 42

def _is_eth(item: Dict[str, Any]) -> bool:
    """
    Vrai si:
      - plt ∈ {ethereum, eth, mainnet}
      - OU l’adresse ressemble à une adresse EVM
    """
    plt = str(item.get("plt") or "").lower()
    if plt in {"ethereum", "eth", "mainnet"}:
        return True
    return _looks_like_evm(str(item.get("addr") or ""))

def _pct(item: Dict[str, Any], key: str) -> Optional[float]:
    v = item.get(key)
    return _float(v) if v is not None else None

# -------------------- HTTP --------------------
def _request(params: dict) -> dict:
    if settings.DEBUG_HTTP:
        log.debug("CMC DAPI GET %s params=%s", BASE, params)
    r = requests.get(BASE, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    js = r.json()
    if settings.DEBUG_HTTP:
        log.debug("CMC DAPI HTTP %s → status=%s keys=%s", r.url, r.status_code, list(js.keys()))
    return js

# -------------------- fetch --------------------
def fetch_cmc_dapi_trending(interval: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """
    Normalise chaque entrée en:
      {
        name, symbol, address, chain,
        price, pct5m, pct1h, pct24h,
        vol24h, liqUsd, txns24h,
        raw
      }
    Clés brutes CMC observées: n, sym, addr, plt, v24h, liqUsd, ch5m/ch1h/ch24h, p, pt, t24h, ...
    """
    params = {
        "sortType": "desc",
        "interval": interval,   # 5m|1h|4h|24h (impacte l’ordre renvoyé)
        "pageSize": page_size,
        "nextPageIndex": 1,
        # CMC ne respecte pas toujours le filtre → on le refait côté client
        "chain": settings.TREND_CHAIN,
        "chainId": settings.TREND_CHAIN_ID,
        "chainIds": settings.TREND_CHAIN,
    }
    js = _request(params)
    rows = (js.get("data") or {}).get("leaderboardList") or []
    n = len(rows)
    if n == 0:
        log.warning("CMC DAPI Trending %s: 0 rows", interval)
        return []

    # Aperçu debug des 1ers items
    for i, item in enumerate(rows[: settings.DEBUG_SAMPLE_ROWS], 1):
        log.debug("[CMC RAW] #%d keys=%s", i, list(item.keys()))

    kept: List[Dict[str, Any]] = []
    non_eth = 0

    for item in rows:
        if not _is_eth(item):
            non_eth += 1
            continue

        name   = (item.get("n") or "").strip()
        symbol = (item.get("sym") or "").strip().upper()
        addr   = (item.get("addr") or "").strip()
        price  = _float(item.get("p"))

        if not _looks_like_evm(addr):
            log.debug("[CMC ETH][WARN] address suspecte name=%s sym=%s addr=%s", name, symbol, addr)

        kept.append({
            "name":    name,
            "symbol":  symbol,
            "address": addr.lower() if _looks_like_evm(addr) else "",
            "chain":   (item.get("plt") or "ethereum").lower(),
            "price":   price,
            "pct5m":   _pct(item, "ch5m"),
            "pct1h":   _pct(item, "ch1h"),   # si absent => None (on ne “recalcule” pas)
            "pct24h":  _pct(item, "ch24h"),
            "vol24h":  _float0(item.get("v24h")),
            "liqUsd":  _float0(item.get("liqUsd")),
            "txns24h": int(_float0(item.get("t24h"))),
            "raw":     item,
        })

    log.info("CMC DAPI Trending %s: %d rows — ETH_kept=%d non-ETH=%d", interval, n, len(kept), non_eth)

    # Preview formatée
    for i, it in enumerate(kept[: settings.DEBUG_SAMPLE_ROWS], 1):
        log.debug(
            "[CMC ETH] #%d %s (%s) Δ5m=%s Δ1h=%s Δ24h=%s Vol24h=$%.0f Liq=$%.0f 0x…%s",
            i, it["symbol"], it["name"],
            it.get("pct5m"), it.get("pct1h"), it.get("pct24h"),
            it["vol24h"], it["liqUsd"],
            (it["address"][-6:] if it["address"] else "--"),
        )

    return kept
