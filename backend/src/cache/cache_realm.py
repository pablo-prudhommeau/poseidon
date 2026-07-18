from __future__ import annotations

from enum import Enum


class CacheRealm(str, Enum):
    PRICES = "prices"
    POSITIONS = "positions"
    POSITION_PRICES = "position_prices"
    TRADES = "trades"
    AVAILABLE_CASH = "available_cash"
    PORTFOLIO = "portfolio"
    AAVE_DCA_STRATEGIES = "aave_dca_strategies"
    SHADOWING_SNAPSHOT = "shadowing_snapshot"
    SHADOWING_VERDICT_CHRONICLE = "shadowing_verdict_chronicle"
    AAVE_SENTINEL_POSITION = "aave_sentinel_position"
    AAVE_SENTINEL_CAPITAL_FLOW = "aave_sentinel_capital_flow"
    AAVE_SENTINEL_PERFORMANCE = "aave_sentinel_performance"
