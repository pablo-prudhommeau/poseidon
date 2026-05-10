from __future__ import annotations

from enum import Enum


class CacheRealm(str, Enum):
    PRICES = "prices"
    POSITIONS = "positions"
    TRADES = "trades"
    AVAILABLE_CASH = "available_cash"
    PORTFOLIO = "portfolio"
    DCA_STRATEGIES = "dca_strategies"
    SHADOW_META = "shadow_meta"
    SHADOW_INTELLIGENCE_SNAPSHOT = "shadow_intelligence_snapshot"
    SHADOW_VERDICT_CHRONICLE = "shadow_verdict_chronicle"
    SHADOW_VERDICT_CHRONICLE_DELTA = "shadow_verdict_chronicle_delta"
