from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AnalyticsOutcomeRecord(BaseModel):
    token_symbol: str
    token_address: str
    quality_score: float
    ai_adjusted_quality_score: float
    liquidity_usd: float
    market_cap_usd: float
    volume_m5_usd: float
    volume_h1_usd: float
    volume_h6_usd: float
    volume_h24_usd: float
    price_change_percentage_m5: float
    price_change_percentage_h1: float
    price_change_percentage_h6: float
    price_change_percentage_h24: float
    token_age_hours: float
    transaction_count_m5: int
    transaction_count_h1: int
    transaction_count_h6: int
    transaction_count_h24: int
    buy_to_sell_ratio: float
    fully_diluted_valuation_usd: float
    dexscreener_boost: float

    has_outcome: bool
    realized_profit_and_loss_usd: float
    realized_profit_and_loss_percentage: float
    holding_duration_minutes: float
    is_profitable: bool
    exit_reason: str
    occurred_at: Optional[datetime] = None
