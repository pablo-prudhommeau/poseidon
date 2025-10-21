from __future__ import annotations

from typing import Dict, Iterable

from src.logging.logger import get_logger

log = get_logger(__name__)


def merge_prices_with_entry(positions: Iterable[object], live: Dict[str, float]) -> Dict[str, float]:
    """
    Build a mapping **key -> price** for valuation and display.

    Key selection (pool-aware):
      - Prefer 'pairAddress' if present and non-empty on the position.
      - Otherwise fall back to 'address' (legacy) or 'tokenAddress'.

    Value selection:
      - Use 'live[key]' if present and strictly positive.
      - Otherwise fall back to position.entry (>0).

    Returns:
        Dict[str, float]: mapping using the SAME keys as chosen above.
    """
    mapping: Dict[str, float] = {}
    for p in positions:
        key = (
                (getattr(p, "pairAddress", None) or "").strip()
                or (getattr(p, "address", None) or "").strip()
                or (getattr(p, "tokenAddress", None) or "").strip()
        )
        if not key:
            continue

        live_value = live.get(key)
        if live_value is not None and float(live_value) > 0.0:
            mapping[key] = float(live_value)
            continue

        entry_value = float(getattr(p, "entry", 0.0) or 0.0)
        if entry_value > 0.0:
            mapping[key] = entry_value

    return mapping
