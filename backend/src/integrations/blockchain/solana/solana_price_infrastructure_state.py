from __future__ import annotations

import time

_solana_price_infrastructure_failure_monotonic: float = 0.0


def mark_solana_price_infrastructure_unavailable() -> None:
    global _solana_price_infrastructure_failure_monotonic
    _solana_price_infrastructure_failure_monotonic = time.monotonic()


def was_solana_price_infrastructure_recently_unavailable(cooldown_seconds: float = 60.0) -> bool:
    if _solana_price_infrastructure_failure_monotonic <= 0.0:
        return False
    return (time.monotonic() - _solana_price_infrastructure_failure_monotonic) < cooldown_seconds


def clear_solana_price_infrastructure_unavailable_marker() -> None:
    global _solana_price_infrastructure_failure_monotonic
    _solana_price_infrastructure_failure_monotonic = 0.0
