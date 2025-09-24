from __future__ import annotations
import asyncio, logging
from typing import Iterable, Dict, List
import httpx
from src.config import settings

log = logging.getLogger(__name__)

def _chunked(items: List[str], n: int) -> List[List[str]]:
    return [items[i:i+n] for i in range(0, len(items), n)]

def _select_best_pair(pairs: list[dict]) -> dict | None:
    # Heuristique simple: priorité à la plus grosse liquidité USD, sinon volume 24h
    if not pairs:
        return None
    def score(p):
        liq = float(p.get("liquidity", {}).get("usd") or 0.0)
        vol = float(p.get("volume", {}).get("h24") or 0.0)
        return (liq, vol)
    return sorted(pairs, key=score, reverse=True)[0]

async def fetch_prices_by_addresses(addresses: Iterable[str]) -> Dict[str, float]:
    """
    Retourne {lowercased_address: priceUsd_float} pour chaque adresse trouvée sur DexScreener.
    Les adresses inconnues sont simplement ignorées.
    """
    addrs = [a.strip().lower() for a in addresses if a]
    if not addrs:
        return {}

    base = settings.DEXSCREENER_BASE_URL.rstrip("/")
    path = f"{base}/latest/dex/tokens"

    out: Dict[str, float] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for batch in _chunked(addrs, max(1, settings.DEXSCREENER_MAX_ADDRESSES_PER_CALL)):
            url = f"{path}/" + ",".join(batch)
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json() or {}
                pairs = data.get("pairs", [])
                # Grouper par baseToken.address
                by_addr: Dict[str, list] = {}
                for p in pairs:
                    addr = (p.get("baseToken", {}) or {}).get("address", "")
                    if addr:
                        by_addr.setdefault(addr.lower(), []).append(p)
                for addr, lst in by_addr.items():
                    best = _select_best_pair(lst)
                    if not best:
                        continue
                    price = best.get("priceUsd")
                    try:
                        price_f = float(price)
                        if price_f > 0:
                            out[addr] = price_f
                    except Exception:
                        continue
            except httpx.HTTPError as e:
                log.warning("DexScreener fetch failed for batch of %d: %s", len(batch), e)
            await asyncio.sleep(0)  # yield
    return out
