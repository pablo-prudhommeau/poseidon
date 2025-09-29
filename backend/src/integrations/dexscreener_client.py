from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Iterable, List, Optional

import httpx

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)

BASE = settings.DEXSCREENER_BASE_URL.rstrip("/")
LATEST_TOKENS = f"{BASE}/latest/dex/tokens"  # /latest/dex/tokens/{addr1,addr2,...}
TOKEN_PROFILES = f"{BASE}/token-profiles/latest/v1"
TOKEN_BOOSTS_LATEST = f"{BASE}/token-boosts/latest/v1"
TOKEN_BOOSTS_TOP = f"{BASE}/token-boosts/top/v1"

DEFAULT_MAX_PER: int = max(1, int(settings.DEXSCREENER_MAX_ADDRESSES_PER_CALL))
TOTAL_CAP: int = max(1, int(settings.DEXSCREENER_MAX_ADDRESSES))

_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")


async def _safe_fetch_pairs_batch(client: httpx.AsyncClient, batch: List[str]) -> Dict[str, List[dict]]:
    """Call /latest/dex/tokens/{a,b,c}. On 400 (often invalid item or limit),
    split the batch and retry down to granularity 1.
    """
    if not batch:
        return {}
    url = f"{LATEST_TOKENS}/" + ",".join(batch)
    try:
        data = await _get_json(client, url)
        pairs = (data or {}).get("pairs", []) if isinstance(data, dict) else []
        by_addr: Dict[str, List[dict]] = {}
        for pair in pairs:
            base_token = pair.get("baseToken") or {}
            address = (base_token.get("address") or "").lower()
            if address:
                by_addr.setdefault(address, []).append(pair)
        return by_addr
    except httpx.HTTPStatusError as exc:
        # 400 => split batch and retry
        if exc.response.status_code == 400 and len(batch) > 1:
            mid = len(batch) // 2
            left = await _safe_fetch_pairs_batch(client, batch[:mid])
            right = await _safe_fetch_pairs_batch(client, batch[mid:])
            out: Dict[str, List[dict]] = {}
            out.update(left)
            for k, v in right.items():
                out.setdefault(k, []).extend(v)
            return out
        log.warning("DexScreener pairs request failed (batch=%d): %s", len(batch), exc)
        return {}
    except httpx.HTTPError as exc:
        log.warning("DexScreener pairs request failed (batch=%d): %s", len(batch), exc)
        return {}


def _is_evm_addr(address: str) -> bool:
    address = (address or "").lower()
    if not (address.startswith("0x") and len(address) == 42):
        return False
    try:
        int(address[2:], 16)
        return True
    except Exception:
        return False


def _is_solana_addr(address: str) -> bool:
    address = (address or "").strip()
    # Solana: 32..44 chars, base58 alphabet
    return 32 <= len(address) <= 44 and bool(_BASE58_RE.fullmatch(address))


_SUFFIXES = ("pump", "bonk", "rev", "to", "tr")  # cases seen in logs


def _strip_known_suffix(address: str) -> str:
    """If the address ends with a known 'pairId' suffix, strip it."""
    for suffix in _SUFFIXES:
        if address.endswith(suffix) and len(address) > len(suffix):
            candidate = address[: -len(suffix)]
            if _is_solana_addr(candidate) or _is_evm_addr(candidate):
                return candidate
    return address


def _chunked(items: List[str], n: int) -> List[List[str]]:
    n = max(1, int(n or 1))
    return [items[i: i + n] for i in range(0, len(items), n)]


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    r = await client.get(url, timeout=15.0)
    r.raise_for_status()
    try:
        return r.json()  # may be list OR dict
    except ValueError:
        return None


def _select_best_pair(pairs: List[dict]) -> Optional[dict]:
    """Pick the most liquid/highest 24h volume pair as 'best'."""
    if not pairs:
        return None

    def score(p: dict) -> tuple[float, float]:
        liquidity_usd = float((p.get("liquidity") or {}).get("usd") or 0.0)
        volume_h24 = float((p.get("volume") or {}).get("h24") or 0.0)
        return liquidity_usd, volume_h24

    return sorted(pairs, key=score, reverse=True)[0]


def _normalize_row_from_pair(address: str, pair: dict) -> dict:
    """Flatten Dexscreener 'pair' into our unified row format."""
    base_token = pair.get("baseToken") or {}
    price_change = pair.get("priceChange") or {}
    volume = pair.get("volume") or {}
    liquidity = pair.get("liquidity") or {}

    def _flt(x: Any) -> Optional[float]:
        try:
            return float(x)
        except Exception:
            return None

    return {
        "name": (base_token.get("name") or "").strip(),
        "symbol": (base_token.get("symbol") or "").strip().upper(),
        "address": (address or "").lower(),
        "chain": (pair.get("chainId") or "").lower(),
        "price": _flt(pair.get("priceUsd")),
        "pct5m": _flt(price_change.get("m5")) if price_change.get("m5") is not None else None,
        "pct1h": _flt(price_change.get("h1")) if price_change.get("h1") is not None else None,
        "pct24h": _flt(price_change.get("h24")) if price_change.get("h24") is not None else None,
        "vol24h": float(volume.get("h24") or 0.0),
        "liqUsd": float(liquidity.get("usd") or 0.0),
        "pairCreatedAt": int(pair.get("pairCreatedAt") or 0),
        "txns": pair.get("txns") or {},
        "fdv": _flt(pair.get("fdv")) if pair.get("fdv") is not None else None,
        "marketCap": _flt(pair.get("marketCap")) if pair.get("marketCap") is not None else None,
    }


def _clean_addresses(addresses: Iterable[str], cap: int) -> List[str]:
    """Sanitize and clip an iterable of addresses.

    Steps:
      - trim/lower
      - remove whitespace/punctuations that indicate malformed tokens
      - strip known 'pairId' suffixes (pump/bonk/rev/to/tr)
      - keep only EVM (0x...) or base58 Solana (32..44)
      - deduplicate & cap to `cap`
    """
    cleaned: List[str] = []
    seen: set[str] = set()
    dropped_count = 0

    for raw in (str(x).strip() for x in addresses if x):
        candidate = raw.lower()
        if any(ch in candidate for ch in (" ", ",", ".", "/", ":")):
            dropped_count += 1
            continue

        candidate = _strip_known_suffix(candidate)

        if not (_is_evm_addr(candidate) or _is_solana_addr(candidate)):
            dropped_count += 1
            continue

        if candidate not in seen:
            seen.add(candidate)
            cleaned.append(candidate)
        if len(cleaned) >= cap:
            break

    if dropped_count:
        log.debug("DexScreener: filtered invalid addresses=%d kept=%d", dropped_count, len(cleaned))
    return cleaned


def _extract_addresses(payload: Any) -> List[str]:
    """Extract potential token addresses from various Dexscreener payload shapes."""
    addresses: List[str] = []

    def _from_item(item: dict) -> None:
        address = (item.get("tokenAddress") or item.get("address") or "")
        if not address:
            base_token = item.get("baseToken") or item.get("token") or {}
            address = base_token.get("address") or ""
        address = address.lower().strip()
        if address:
            addresses.append(address)

    if payload is None:
        return addresses
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                _from_item(item)
    elif isinstance(payload, dict):
        for key in ("data", "tokens", "profiles", "pairs"):
            items = payload.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        _from_item(item)
    return addresses


async def fetch_pairs_by_addresses(addresses: Iterable[str]) -> Dict[str, List[dict]]:
    """Fetch raw pairs for a list of addresses (best-effort)."""
    addrs = _clean_addresses(addresses, cap=TOTAL_CAP)
    if not addrs:
        return {}
    out: Dict[str, List[dict]] = {a: [] for a in addrs}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for batch in _chunked(addrs, DEFAULT_MAX_PER):
            by_addr = await _safe_fetch_pairs_batch(client, batch)
            for addr, pairs in by_addr.items():
                out[addr] = pairs
            await asyncio.sleep(0)
    return out


async def fetch_prices_by_addresses(addresses: Iterable[str]) -> Dict[str, float]:
    """Fetch best price (USD) per address using Dexscreener pairs."""
    addrs = _clean_addresses(addresses, cap=TOTAL_CAP)
    if not addrs:
        return {}
    prices: Dict[str, float] = {}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for batch in _chunked(addrs, DEFAULT_MAX_PER):
            by_addr = await _safe_fetch_pairs_batch(client, batch)
            for addr, pairs in by_addr.items():
                best = _select_best_pair(pairs)
                if not best:
                    continue
                try:
                    px = float(best.get("priceUsd") or 0.0)
                    if px > 0:
                        prices[addr] = px
                except Exception:
                    log.debug("DexScreener price parse failed for %s", addr)
                    pass
            await asyncio.sleep(0)
    return prices


async def fetch_trending_candidates(page_size: int = 100) -> List[dict]:
    """Aggregate trending candidates from multiple Dexscreener sources."""
    addresses: List[str] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for url in (TOKEN_BOOSTS_LATEST, TOKEN_BOOSTS_TOP, TOKEN_PROFILES):
            try:
                payload = await _get_json(client, url)
                extracted = _extract_addresses(payload)
                addresses.extend(extracted)
                log.debug(
                    "DexScreener %s → items=%s extracted=%s",
                    url.rsplit("/", 2)[-2:],
                    (len(payload) if isinstance(payload, list) else len(payload or {})),
                    len(extracted),
                )
            except httpx.HTTPError as exc:
                log.warning("DexScreener read failed: %s (%s)", url, exc)

    uniq = _clean_addresses(addresses, cap=max(page_size * 3, 300))
    if not uniq:
        log.info("DexScreener sources yielded 0 usable addresses (after sanitize).")
        return []
    else:
        log.debug("DexScreener: addresses collected=%d sanitized=%d", len(addresses), len(uniq))

    pairs_map = await fetch_pairs_by_addresses(uniq)
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

    return rows
