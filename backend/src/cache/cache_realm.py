from __future__ import annotations

from enum import Enum


class CacheRealm(str, Enum):
    PRICES = "prices"
    POSITIONS = "positions"
    POSITION_PRICES = "position_prices"
    TRADES = "trades"
    AVAILABLE_CASH = "available_cash"
    PORTFOLIO = "portfolio"
    DCA_STRATEGIES = "dca_strategies"
    SHADOWING_SNAPSHOT = "shadowing_snapshot"
    SHADOWING_VERDICT_CHRONICLE = "shadowing_verdict_chronicle"
