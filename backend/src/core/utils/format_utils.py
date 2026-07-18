import time
from math import isnan
from typing import Optional, Union


def format_currency(value: Optional[Union[float, int]], currency: str = "USD") -> str:
    if value is None or (isinstance(value, float) and isnan(value)):
        return "N/A"

    try:
        float_val = float(value)
        formatted = f"{float_val:,.2f}"

        if currency == "USD":
            return f"${formatted}"
        if currency == "EUR":
            return f"{formatted} €"
        return f"{formatted} {currency}"

    except (ValueError, TypeError):
        return "N/A"


def format_percent(value: Optional[float], decimals: int = 2) -> str:
    if value is None or isnan(value):
        return "N/A"

    try:
        return f"{value * 100:.{decimals}f}%"
    except (ValueError, TypeError):
        return "N/A"


def tail(address: str, n: int = 6) -> str:
    addr = (address or "").lower()
    return addr[-n:] if len(addr) >= n else addr


def age_hours(ms: int) -> float:
    if not ms or ms <= 0:
        return 0.0
    return max(0.0, (time.time() - (ms / 1000.0)) / 3600.0)
