from __future__ import annotations

from enum import Enum


class CacheRealm(str, Enum):
    PRICES = "prices"
    POSITIONS = "positions"
    TRADES = "trades"
    AVAILABLE_CASH = "available_cash"
    PORTFOLIO = "portfolio"
    DCA_STRATEGIES = "dca_strategies"
    SHADOW_INTELLIGENCE_SNAPSHOT = "shadow_intelligence_snapshot"
