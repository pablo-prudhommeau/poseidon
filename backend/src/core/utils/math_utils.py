from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def squash_positive_percentage(percentage: float) -> float:
    raw_sigmoid = 1.0 / (1.0 + math.exp(-percentage / 5.0))
    return max(0.0, 2.0 * (raw_sigmoid - 0.5))


def quantize_2dp(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def decimal_from_primitive(value: float | int | str | None) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def is_finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False
