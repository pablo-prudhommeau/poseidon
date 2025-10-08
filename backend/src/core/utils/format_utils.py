import time
from cmath import isnan
from typing import Optional


def _format(value: Optional[float]) -> str:
    """Format a float for logs, or 'NA' if missing."""
    return "NA" if value is None else f"{value:.2f}"


def _tail(address: str, n: int = 6) -> str:
    """Return the last n characters of a lowercased address (for concise logs)."""
    addr = (address or "").lower()
    return addr[-n:] if len(addr) >= n else addr


def _num(value: object) -> Optional[float]:
    """
    Safely parse a number. Returns None for invalid or NaN inputs.
    """
    try:
        parsed = float(value)
        return None if isnan(parsed) else parsed
    except Exception:
        return None


def _age_hours(ms: int) -> float:
    """Compute age in hours from a Unix timestamp in milliseconds."""
    if not ms or ms <= 0:
        return 0.0
    return max(0.0, (time.time() - (ms / 1000.0)) / 3600.0)
