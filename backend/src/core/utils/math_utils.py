import math


def _clamp(value: float, lower: float, upper: float) -> float:
    """Clamp value to [lower, upper]."""
    return max(lower, min(upper, value))


def _squash_pct(pct: float) -> float:
    """
    Smooth percentage with a logistic squashing function.
    Input is a delta in percentage points (e.g., +5.0 for +5%).
    """
    return 1.0 / (1.0 + math.exp(-pct / 5.0))
