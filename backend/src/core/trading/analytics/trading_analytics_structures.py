from __future__ import annotations

from datetime import datetime
from typing import Optional, Callable

from pydantic import BaseModel, ConfigDict


class MetricDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    key: str
    label: str
    accessor: Callable[[AnalyticsOutcomeRecord], float]
    unit: str


class AnalyticsOutcomeRecord(BaseModel):
    token_symbol: str
    token_address: str
    quality_score: float
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


class MetricBucketStatistics(BaseModel):
    range_min: float
    range_max: float
    sample_count: int
    win_count: int
    win_rate: float
    average_pnl: float
    average_holding_time_minutes: float
    expected_pnl_velocity: float
    outlier_hit_rate: float
    quartile_1_pnl: float
    quartile_3_pnl: float
    is_golden: bool
    is_toxic: bool


class MetricBucketProfile(BaseModel):
    metric_key: str
    bucket_edges: list[float]
    bucket_statistics: list[MetricBucketStatistics]
    influence_score: float
    winner_deviation: float


class AnalyticsTimelineOutcome(BaseModel):
    date_iso: str
    pnl_usd: float
    pnl_percentage: float
    is_profitable: bool


class AnalyticsDailyAggregation(BaseModel):
    pnl_usd: float = 0.0
    pnl_percentage: float = 0.0
    trade_count: int = 0
    win_count: int = 0


class MetaStatistics(BaseModel):
    win_rate: float = 0.0
    average_pnl: float = 0.0
    average_holding_time_hours: float = 0.0
    expected_pnl_velocity: float = 0.0
