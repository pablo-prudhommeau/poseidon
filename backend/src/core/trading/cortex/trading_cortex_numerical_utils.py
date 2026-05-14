from __future__ import annotations

import math
from typing import Optional


def clamp(value: float, minimum_value: float, maximum_value: float) -> float:
    return max(minimum_value, min(maximum_value, value))


def safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> float:
    if numerator is None or denominator is None or denominator == 0:
        return math.nan
    return numerator / denominator


def safe_logarithm_one_plus(value: Optional[float]) -> float:
    if value is None or value < 0:
        return math.nan
    return math.log1p(value)


def probability_to_centered_signal(probability_value: float) -> float:
    return clamp((probability_value * 2.0) - 1.0, -1.0, 1.0)


def bounded_hyperbolic_signal(value: Optional[float], temperature: float) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    if temperature <= 0:
        return clamp(value, -1.0, 1.0)
    return clamp(math.tanh(value / temperature), -1.0, 1.0)


def logistic_sigmoid(value: float) -> float:
    if value >= 0:
        exponential_value = math.exp(-value)
        return 1.0 / (1.0 + exponential_value)
    exponential_value = math.exp(value)
    return exponential_value / (1.0 + exponential_value)


def optional_float_to_feature_value(value: Optional[float]) -> float:
    if value is None:
        return math.nan
    return value
