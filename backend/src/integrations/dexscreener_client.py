from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Dict, List, Any, Optional

import httpx
from src.configuration.config import settings

log = logging.getLogger(__name__)

BASE = settings.DEXSCREENER_BASE_URL.rstrip("/")
TOKENS_V1 = f"{BASE}/tokens/v1"                 # /tokens/v1/{chainId}/{addr1,addr2,...}
LATEST_TOKENS = f"{BASE}/latest/dex/tokens"     # /latest/dex/tokens/{addr1,addr2,...}
TOKEN_PROFILES = f"{BASE}/token-profiles/latest/v1"
TOKEN_BOOSTS_LATEST = f"{BASE}/token-boosts/latest/v1"
TOKEN_BOOSTS_TOP = f"{BASE}/token-boosts/top/v1"


# ---------- helpers ----------
def _chunked(items: List[str], n: int) -> List[List[str]]:
    n = max(1, int(n or 1))
    return [items[i:i + n] for i in range(0, len(items), n)]

def _is_evm_address(a: str) -> bool:
    a = (a or "").lower()
    if not (a.startswith("0x") and len(a) == 42):
        return False
    try:
        int(a[2:], 16)
        return True
    except Exception:
        return False

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
    bt = pair.get("baseToken") or {}
    pc = pair.get("priceChange") or {}
    vol = pair.get("volume") or {}
    liq = pair.get("liquidity") or {}
    return {
        "name": (bt.get("name") or "").strip(),
        "symbol": (bt.get("symbol") or "").strip().upper(),
        "address": addr.lower(),
        "chain": (pair.get("chainId") or "").lower(),
        "price": float(pair.get("priceUsd") or 0.0) or None,
        "pct5m": float(pc.get("m5")) if pc.get("m5") is not None else None,
        "pct1h": float(pc.get("h1")) if pc.get("h1") is not None else None,
        "pct24h": float(pc.get("h24")) if pc.get("h24") is not None else None,
        "vol24h": float(vol.get("h24") or 0.0),
        "liqUsd": float(liq.get("usd") or 0.0),
        "pairCreatedAt": int(pair.get("pairCreatedAt") or 0),
        "txns": pair.get("txns") or {},
        "fdv": float(pair.get("fdv") or 0.0) if pair.get("fdv") is not None else None,
        "marketCap": float(pair.get("marketCap") or 0.0) if pair.get("marketCap") is not None else None,
    }


# ---------- core fetchers ----------
async def fetch_pairs_by_addresses(addresses: Iterable[str], chain_id: Optional[str] = None) -> Dict[str, List[dict]]:
    """Map {baseTokenAddress -> [pairs]}."""
    addrs = []
    for a in (a.strip().lower() for a in addresses if a):
        if "." in a or "," in a or " " in a:
            continue
        if chain_id and not _is_evm_address(a):
            # si on impose un chain_id EVM, on filtre les non-EVM
            continue
        addrs.append(a)
    addrs = list(dict.fromkeys(addrs))
    if not addrs:
        return {}

    max_per = max(1, int(getattr(settings, "DEXSCREENER_MAX_ADDRESSES_PER_CALL", 40)))
    out: Dict[str, List[dict]] = {a: [] for a in addrs}

    async with httpx.AsyncClient() as client:
        for batch in _chunked(addrs, max_per):
            if chain_id:
                url = f"{TOKENS_V1}/{chain_id}/" + ",".join(batch)
            else:
                url = f"{LATEST_TOKENS}/" + ",".join(batch)
            try:
                data = await _get_json(client, url)
                # data est dict {"pairs":[...]} ou None
                pairs = (data or {}).get("pairs", []) if isinstance(data, dict) else []
                by_addr: Dict[str, List[dict]] = {}
                for p in pairs:
                    bt = p.get("baseToken") or {}
                    a = (bt.get("address") or "").lower()
                    if a:
                        by_addr.setdefault(a, []).append(p)
                for a in batch:
                    if a in by_addr:
                        out[a] = by_addr[a]
            except httpx.HTTPError as e:
                log.warning("DexScreener fetch pairs failed (%d): %s", len(batch), e)
            await asyncio.sleep(0)
    return out


async def fetch_prices_by_addresses(addresses: Iterable[str], chain_id: Optional[str] = None) -> Dict[str, float]:
    """
    Map {address -> priceUsd} en choisissant la meilleure paire (liq/vol).
    Garde la compat d'import attendue par orchestrator/trader.
    """
    addrs = []
    for a in (a.strip().lower() for a in addresses if a):
        if "." in a or "," in a or " " in a:
            continue
        if chain_id and not _is_evm_address(a):
            continue
        addrs.append(a)
    addrs = list(dict.fromkeys(addrs))
    if not addrs:
        return {}

    max_per = max(1, int(getattr(settings, "DEXSCREENER_MAX_ADDRESSES_PER_CALL", 40)))
    out: Dict[str, float] = {}

    async with httpx.AsyncClient() as client:
        for batch in _chunked(addrs, max_per):
            if chain_id:
                url = f"{TOKENS_V1}/{chain_id}/" + ",".join(batch)
            else:
                url = f"{LATEST_TOKENS}/" + ",".join(batch)
            try:
                data = await _get_json(client, url)
                pairs = (data or {}).get("pairs", []) if isinstance(data, dict) else []
                by_addr: Dict[str, List[dict]] = {}
                for p in pairs:
                    a = ((p.get("baseToken") or {}).get("address") or "").lower()
                    if a:
                        by_addr.setdefault(a, []).append(p)
                for a, lst in by_addr.items():
                    best = _select_best_pair(lst)
                    if not best:
                        continue
                    try:
                        price = float(best.get("priceUsd") or 0.0)
                        if price > 0:
                            out[a] = price
                    except Exception:
                        pass
            except httpx.HTTPError as e:
                log.warning("DexScreener fetch prices failed (%d): %s", len(batch), e)
            await asyncio.sleep(0)
    return out


async def fetch_trending_candidates(
        interval: str,
        page_size: int = 100,
        chain: Optional[str] = None,
        chain_id: Optional[str] = None,
) -> List[dict]:
    """
    Compose un univers depuis boosts + profiles.
    Accepte payload list/dict, filtre les adresses invalides si chain_id, puis enrichit via /tokens.
    """

    def _extract_addresses(payload) -> List[str]:
        addrs: List[str] = []

        def _from_item(it: dict):
            a = (it.get("tokenAddress") or it.get("address") or "").lower()
            if not a:
                bt = it.get("baseToken") or it.get("token") or {}
                a = (bt.get("address") or "").lower()
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

    def _sanitize(addrs: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for a in (x.strip().lower() for x in addrs if x):
            if "." in a or "," in a or " " in a:
                continue
            if chain_id and not _is_evm_address(a):
                continue
            if a not in seen:
                seen.add(a)
                out.append(a)
            if len(out) >= max(page_size * 3, 100):
                break
        return out

    # 1) collect
    addresses: List[str] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for url in (TOKEN_BOOSTS_LATEST, TOKEN_BOOSTS_TOP, TOKEN_PROFILES):
            try:
                payload = await _get_json(client, url)
                addresses.extend(_extract_addresses(payload))
            except httpx.HTTPError as e:
                log.warning("DexScreener read failed: %s (%s)", url, e)

    uniq = _sanitize(addresses)
    if not uniq:
        log.info("Dexscreener sources returned 0 token addresses after sanitize (chain_id=%s).", chain_id)
        return []

    # 2) enrich
    pairs_map = await fetch_pairs_by_addresses(uniq, chain_id=chain_id)
    if not any(pairs_map.values()):
        log.info("No pairs with chain_id=%s; trying multi-chain fallback.", chain_id)
        pairs_map = await fetch_pairs_by_addresses(uniq, chain_id=None)

    # 3) normalize + sort
    rows: List[dict] = []
    for addr, pairs in pairs_map.items():
        best = _select_best_pair(pairs)
        if not best:
            continue
        rows.append(_normalize_row_from_pair(addr, best))

    rows.sort(key=lambda x: (float(x.get("vol24h") or 0.0), float(x.get("liqUsd") or 0.0)), reverse=True)
    return rows[:page_size]
