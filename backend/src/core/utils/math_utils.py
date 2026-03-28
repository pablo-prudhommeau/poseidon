import math


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _squash_pct(pct: float) -> float:
    return 1.0 / (1.0 + math.exp(-pct / 5.0))
