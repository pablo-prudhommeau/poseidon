import re
from typing import List, Dict
import requests
from bs4 import BeautifulSoup

from ..config import settings
from ..logger import get_logger

log = get_logger(__name__)

COIN_LINK_RE = re.compile(r"^/currencies/([^/]+)/?$")
UPPER_RE = re.compile(r"^[A-Z0-9]{2,12}$")

def _headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

def make_url(window: str) -> str:
    typ = (settings.CMC_TRENDING_TYPE or "tokens").lower()
    return f"https://coinmarketcap.com/?type={typ}&tableRankBy=trending_all_{window}"

def _rows(html: str):
    soup = BeautifulSoup(html, "html.parser")
    tb = soup.find("tbody")
    return tb.find_all("tr", recursive=False) if tb else soup.find_all("tr")

def _extract_slug(tr) -> str | None:
    a = tr.find("a", href=COIN_LINK_RE)
    if not a:
        return None
    m = COIN_LINK_RE.match(a.get("href", ""))
    return m.group(1) if m else None

def _extract_symbol(tr) -> str:
    # 1) classes les plus fréquentes
    for cls in ("coin-item-symbol", "crypto-symbol"):
        el = tr.find(["p", "span"], class_=re.compile(cls))
        if el:
            s = (el.get_text(strip=True) or "").upper()
            if UPPER_RE.match(s):
                return s

    # 2) fallback: premier petit texte en MAJ dans les 2-3 premières cellules
    for td in tr.find_all("td")[:3]:
        for el in td.find_all(["p", "span", "div"], recursive=True):
            s = (el.get_text(strip=True) or "").upper()
            if UPPER_RE.match(s):
                return s

    return ""

def _name_from_slug(slug: str) -> str:
    # Reconstruit un nom "propre" depuis le slug (suffisant pour la log)
    parts = [p for p in slug.split("-") if p]
    return " ".join(w.capitalize() for w in parts) or slug

DENYLIST_L1 = {
    "BTC","ETH","BNB","SOL","XRP","ADA","TRX","DOGE","TON","BCH","XLM","HBAR",
    "SUI","APT","NEAR","LTC","ETC","OKB","TAO","BGB","ARB","OP","AVAX","DOT"
}

def fetch_trending_list(windows: List[str]) -> List[Dict]:
    out: List[Dict] = []
    limit = int(settings.TREND_LIST_LIMIT)

    for wnd in windows:
        url = make_url(wnd)
        r = requests.get(url, headers=_headers(), timeout=12)
        r.raise_for_status()

        rows = _rows(r.text)
        items: List[Dict] = []
        for idx, tr in enumerate(rows, start=1):
            slug = _extract_slug(tr)
            if not slug:
                continue
            symbol = _extract_symbol(tr).upper()
            name = _name_from_slug(slug)

            # filtre brutal anti-"top coins" (L1 / grosses coins)
            if symbol in DENYLIST_L1:
                continue

            items.append({
                "slug": slug,
                "name": name,
                "symbol": symbol,
                "rank": idx,
                "window": wnd,
            })
            if len(items) >= limit:
                break

        log.info("CMC Trending %s: %d rows (after denylist)", wnd, len(items))
        # (plus de dump DEBUG ligne-par-ligne ici)
        out.extend(items)

    return out
