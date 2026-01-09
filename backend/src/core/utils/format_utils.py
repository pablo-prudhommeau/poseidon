import time
from math import isnan
from typing import Optional, Union
from datetime import datetime

def format_currency(value: Optional[Union[float, int]], currency: str = "USD") -> str:
    """
    Format a float as a currency string.
    Example: 1234.56 -> "$1,234.56" or "1,234.56 €"
    """
    if value is None or (isinstance(value, float) and isnan(value)):
        return "N/A"

    try:
        float_val = float(value)
        formatted = f"{float_val:,.2f}"

        if currency == "USD":
            return f"${formatted}"
        elif currency == "EUR":
            return f"{formatted} €"
        else:
            return f"{formatted} {currency}"

    except (ValueError, TypeError):
        return "N/A"


def format_percent(value: Optional[float], decimals: int = 2) -> str:
    """
    Format a float as a percentage string.
    Example: 0.054 -> "5.40%"
    """
    if value is None or isnan(value):
        return "N/A"

    try:
        return f"{value * 100:.{decimals}f}%"
    except (ValueError, TypeError):
        return "N/A"


def _format(value: Optional[float]) -> str:
    """Legacy helper: Format a float for logs, or 'NA' if missing."""
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
        parsed = float(value) # type: ignore
        return None if isnan(parsed) else parsed
    except (ValueError, TypeError):
        return None


def _age_hours(ms: int) -> float:
    """Compute age in hours from a Unix timestamp in milliseconds."""
    if not ms or ms <= 0:
        return 0.0
    return max(0.0, (time.time() - (ms / 1000.0)) / 3600.0)