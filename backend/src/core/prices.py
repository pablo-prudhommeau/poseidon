from __future__ import annotations

from typing import Dict, Iterable

from src.logging.logger import get_logger

log = get_logger(__name__)


def merge_prices_with_entry(positions: Iterable[object], live: Dict[str, float]) -> Dict[str, float]:
    """
    Map adresse -> prix pour **affichage/valorisation** :
      live si dispo (>0), sinon fallback = entry (>0). Clés = adresses d’origine.
    """
    m: Dict[str, float] = {}
    for p in positions:
        addr = getattr(p, "address", None) or ""
        if not addr:
            continue
        v = live.get(addr)
        if v is not None and float(v) > 0:
            m[addr] = float(v)
            continue
        entry = float(getattr(p, "entry", 0.0) or 0.0)
        if entry > 0:
            m[addr] = entry
    return m
