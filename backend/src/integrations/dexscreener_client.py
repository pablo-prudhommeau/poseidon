# backend/src/integrations/dexscreener_client.py
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Dict, List, Any, Optional

import httpx
from src.configuration.config import settings

log = logging.getLogger(__name__)

BASE = getattr(settings, "DEXSCREENER_BASE_URL", "https://api.dexscreener.com").rstrip("/")
LATEST_TOKENS = f"{BASE}/latest/dex/tokens"       # /latest/dex/tokens/{addr1,addr2,...}
TOKEN_PROFILES = f"{BASE}/token-profiles/latest/v1"
TOKEN_BOOSTS_LATEST = f"{BASE}/token-boosts/latest/v1"
TOKEN_BOOSTS_TOP = f"{BASE}/token-boosts/top/v1"
DEFAULT_MAX_PER = max(1, int(getattr(settings, "DEXSCREENER_MAX_ADDRESSES_PER_CALL", 20)))  # ↓ 20 au lieu de 40

# ---------------- helpers ----------------
import re

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")  # alphabet base58

async def _safe_fetch_pairs_batch(client: httpx.AsyncClient, batch: list[str]) -> dict[str, list[dict]]:
    """
    Appelle /latest/dex/tokens/{a,b,c}. Si 400 (souvent un élément invalide ou limite),
    on splitte en deux et on réessaie, jusqu'à la granularité 1.
    """
    if not batch:
        return {}
    url = f"{LATEST_TOKENS}/" + ",".join(batch)
    try:
        data = await _get_json(client, url)
        pairs = (data or {}).get("pairs", []) if isinstance(data, dict) else []
        by_addr: dict[str, list[dict]] = {}
        for p in pairs:
            bt = p.get("baseToken") or {}
            a = (bt.get("address") or "").lower()
            if a:
                by_addr.setdefault(a, []).append(p)
        return by_addr
    except httpx.HTTPStatusError as e:
        # 400 => on split le batch et on réessaie
        if e.response.status_code == 400 and len(batch) > 1:
            mid = len(batch) // 2
            left  = await _safe_fetch_pairs_batch(client, batch[:mid])
            right = await _safe_fetch_pairs_batch(client, batch[mid:])
            # fusion
            out = {}
            out.update(left)
            for k, v in right.items():
                out.setdefault(k, []).extend(v)
            return out
        # autres codes: warn et on skip
        log.warning("DexScreener pairs failed (%d): %s", len(batch), e)
        return {}
    except httpx.HTTPError as e:
        log.warning("DexScreener pairs failed (%d): %s", len(batch), e)
        return {}


def _is_evm_addr(a: str) -> bool:
    a = (a or "").lower()
    if not (a.startswith("0x") and len(a) == 42):
        return False
    try:
        int(a[2:], 16)
        return True
    except Exception:
        return False

def _is_solana_addr(a: str) -> bool:
    a = (a or "").strip()
    # solana: 32..44 chars, alphabet base58
    return 32 <= len(a) <= 44 and bool(_BASE58_RE.fullmatch(a))

_SUFFIXES = ("pump", "bonk", "rev", "to", "tr")  # cas observés dans tes logs

def _strip_known_suffix(a: str) -> str:
    """Si l’adresse termine par un suffixe ‘pairId’ connu, on l’enlève."""
    for s in _SUFFIXES:
        if a.endswith(s) and len(a) > len(s):
            candidate = a[: -len(s)]
            if _is_solana_addr(candidate) or _is_evm_addr(candidate):
                return candidate
    return a

def _chunked(items: List[str], n: int) -> List[List[str]]:
    n = max(1, int(n or 1))
    return [items[i:i + n] for i in range(0, len(items), n)]

async def _get_json(client: httpx.AsyncClient, url: str):
    r = await client.get(url, timeout=15.0)
    r.raise_for_status()
    try:
        return r.json()  # peut être list OU dict
    except ValueError:
        return None

def _select_best_pair(pairs: list[dict]) -> dict | None:
    if not pairs:
        return None
    def score(p: dict) -> tuple[float, float]:
        liq = float((p.get("liquidity") or {}).get("usd") or 0.0)
        vol = float((p.get("volume") or {}).get("h24") or 0.0)
        return liq, vol
    return sorted(pairs, key=score, reverse=True)[0]

def _normalize_row_from_pair(addr: str, pair: dict) -> dict:
    bt  = pair.get("baseToken") or {}
    pc  = pair.get("priceChange") or {}
    vol = pair.get("volume") or {}
    liq = pair.get("liquidity") or {}
    def _flt(x):
        try: return float(x)
        except Exception: return None
    return {
        "name": (bt.get("name") or "").strip(),
        "symbol": (bt.get("symbol") or "").strip().upper(),
        "address": (addr or "").lower(),
        "chain": (pair.get("chainId") or "").lower(),
        "price": _flt(pair.get("priceUsd")),
        "pct5m": _flt(pc.get("m5"))  if pc.get("m5")  is not None else None,
        "pct1h": _flt(pc.get("h1"))  if pc.get("h1")  is not None else None,
        "pct24h": _flt(pc.get("h24")) if pc.get("h24") is not None else None,
        "vol24h": float(vol.get("h24") or 0.0),
        "liqUsd": float(liq.get("usd") or 0.0),
        "pairCreatedAt": int(pair.get("pairCreatedAt") or 0),
        "txns": pair.get("txns") or {},
        "fdv": _flt(pair.get("fdv")) if pair.get("fdv") is not None else None,
        "marketCap": _flt(pair.get("marketCap")) if pair.get("marketCap") is not None else None,
    }

def _clean_addresses(addrs: Iterable[str], cap: int) -> List[str]:
    """
    - trim/lower
    - retire espaces/virgules/points
    - strip suffixes 'pairId' (pump/bonk/rev/to/tr)
    - garde seulement EVM(0x...) ou base58 Solana (32..44)
    """
    out: List[str] = []
    seen = set()
    dropped = 0

    for raw in (str(x).strip() for x in addrs if x):
        a = raw.lower()
        if " " in a or "," in a or "." in a or "/" in a or ":" in a:
            dropped += 1
            continue

        a = _strip_known_suffix(a)

        ok = _is_evm_addr(a) or _is_solana_addr(a)
        if not ok:
            dropped += 1
            continue

        if a not in seen:
            seen.add(a)
            out.append(a)
        if len(out) >= cap:
            break

    if dropped:
        log.debug("DexScreener: filtered invalid addresses=%d kept=%d", dropped, len(out))
    return out

def _extract_addresses(payload: Any) -> List[str]:
    addrs: List[str] = []

    def _from_item(it: dict):
        a = (it.get("tokenAddress") or it.get("address") or "")
        if not a:
            bt = it.get("baseToken") or it.get("token") or {}
            a = bt.get("address") or ""
        a = a.lower().strip()
        if a:
            addrs.append(a)

    if payload is None:
        return addrs
    if isinstance(payload, list):
        for it in payload:
            if isinstance(it, dict):
                _from_item(it)
    elif isinstance(payload, dict):
        for key in ("data", "tokens", "profiles", "pairs"):
            arr = payload.get(key)
            if isinstance(arr, list):
                for it in arr:
                    if isinstance(it, dict):
                        _from_item(it)
    return addrs

# ---------------- public API ----------------

async def fetch_pairs_by_addresses(addresses: Iterable[str], chain_id: Optional[str] = None) -> Dict[str, List[dict]]:
    addrs = _clean_addresses(addresses, cap=max(1000, int(getattr(settings, "DEXSCREENER_MAX_ADDRESSES", 1000))))
    if not addrs:
        return {}
    out: Dict[str, List[dict]] = {a: [] for a in addrs}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for batch in _chunked(addrs, DEFAULT_MAX_PER):
            by_addr = await _safe_fetch_pairs_batch(client, batch)
            for a, lst in by_addr.items():
                out[a] = lst
            await asyncio.sleep(0)
    return out

async def fetch_prices_by_addresses(addresses: Iterable[str], chain_id: Optional[str] = None) -> Dict[str, float]:
    addrs = _clean_addresses(addresses, cap=max(1000, int(getattr(settings, "DEXSCREENER_MAX_ADDRESSES", 1000))))
    if not addrs:
        return {}
    prices: Dict[str, float] = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for batch in _chunked(addrs, DEFAULT_MAX_PER):
            by_addr = await _safe_fetch_pairs_batch(client, batch)
            for a, lst in by_addr.items():
                best = _select_best_pair(lst)
                if not best:
                    continue
                try:
                    px = float(best.get("priceUsd") or 0.0)
                    if px > 0:
                        prices[a] = px
                except Exception:
                    pass
            await asyncio.sleep(0)
    return prices

async def fetch_trending_candidates(
        interval: str,
        page_size: int = 100,
        chain: Optional[str] = None,
        chain_id: Optional[str] = None,  # ignoré (multi-chain)
) -> List[dict]:
    addresses: List[str] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for url in (TOKEN_BOOSTS_LATEST, TOKEN_BOOSTS_TOP, TOKEN_PROFILES):
            try:
                payload = await _get_json(client, url)
                extracted = _extract_addresses(payload)
                addresses.extend(extracted)
                log.debug("DexScreener %s -> items=%s extracted=%s",
                          url.rsplit("/", 2)[-2:],
                          (len(payload) if isinstance(payload, list) else len(payload or {})),
                          len(extracted))
            except httpx.HTTPError as e:
                log.warning("DexScreener read failed: %s (%s)", url, e)

    uniq = _clean_addresses(addresses, cap=max(page_size * 3, 300))
    if not uniq:
        log.info("DexScreener sources yielded 0 usable addresses (after sanitize).")
        return []
    else:
        log.debug("DexScreener: addresses collected=%d sanitized=%d", len(addresses), len(uniq))

    pairs_map = await fetch_pairs_by_addresses(uniq, chain_id=None)
    if not any(pairs_map.values()):
        log.info("DexScreener pairs empty for collected addresses.")
        return []

    rows: List[dict] = []
    for addr, pairs in pairs_map.items():
        best = _select_best_pair(pairs)
        if not best:
            continue
        rows.append(_normalize_row_from_pair(addr, best))

    rows.sort(key=lambda x: (float(x.get("vol24h") or 0.0), float(x.get("liqUsd") or 0.0)), reverse=True)
    rows = rows[:page_size]

    if rows:
        top = rows[0]
        log.debug("Trending sample: %s (%s) vol24h=%.0f liq=%.0f",
                  top.get("symbol"), (top.get("address") or "")[-6:],
                  float(top.get("vol24h") or 0.0), float(top.get("liqUsd") or 0.0))
    return rows
