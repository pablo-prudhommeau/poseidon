import math


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _squash_positive_percentage(percentage: float) -> float:
    raw_sigmoid = 1.0 / (1.0 + math.exp(-percentage / 5.0))
    return max(0.0, 2.0 * (raw_sigmoid - 0.5))
