from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict


class AnalyticsMarketSnapshot(BaseModel):
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
    promotion_score: Optional[float] = None


class AnalyticsResolvedTradeOutcome(BaseModel):
    realized_profit_and_loss_usd: float
    realized_profit_and_loss_percentage: float
    holding_duration_minutes: float
    is_profitable: bool
    exit_reason: str
    occurred_at: datetime


class AnalyticsOutcomeRecord(BaseModel):
    market_snapshot: AnalyticsMarketSnapshot
    resolved_outcome: Optional[AnalyticsResolvedTradeOutcome] = None

    @property
    def has_outcome(self) -> bool:
        return self.resolved_outcome is not None

    @property
    def token_symbol(self) -> str:
        return self.market_snapshot.token_symbol

    @property
    def token_address(self) -> str:
        return self.market_snapshot.token_address

    @property
    def quality_score(self) -> float:
        return self.market_snapshot.quality_score

    @property
    def liquidity_usd(self) -> float:
        return self.market_snapshot.liquidity_usd

    @property
    def market_cap_usd(self) -> float:
        return self.market_snapshot.market_cap_usd

    @property
    def volume_m5_usd(self) -> float:
        return self.market_snapshot.volume_m5_usd

    @property
    def volume_h1_usd(self) -> float:
        return self.market_snapshot.volume_h1_usd

    @property
    def volume_h6_usd(self) -> float:
        return self.market_snapshot.volume_h6_usd

    @property
    def volume_h24_usd(self) -> float:
        return self.market_snapshot.volume_h24_usd

    @property
    def price_change_percentage_m5(self) -> float:
        return self.market_snapshot.price_change_percentage_m5

    @property
    def price_change_percentage_h1(self) -> float:
        return self.market_snapshot.price_change_percentage_h1

    @property
    def price_change_percentage_h6(self) -> float:
        return self.market_snapshot.price_change_percentage_h6

    @property
    def price_change_percentage_h24(self) -> float:
        return self.market_snapshot.price_change_percentage_h24

    @property
    def token_age_hours(self) -> float:
        return self.market_snapshot.token_age_hours

    @property
    def transaction_count_m5(self) -> int:
        return self.market_snapshot.transaction_count_m5

    @property
    def transaction_count_h1(self) -> int:
        return self.market_snapshot.transaction_count_h1

    @property
    def transaction_count_h6(self) -> int:
        return self.market_snapshot.transaction_count_h6

    @property
    def transaction_count_h24(self) -> int:
        return self.market_snapshot.transaction_count_h24

    @property
    def buy_to_sell_ratio(self) -> float:
        return self.market_snapshot.buy_to_sell_ratio

    @property
    def fully_diluted_valuation_usd(self) -> float:
        return self.market_snapshot.fully_diluted_valuation_usd

    @property
    def promotion_score(self) -> Optional[float]:
        return self.market_snapshot.promotion_score

    @property
    def realized_profit_and_loss_usd(self) -> float:
        if self.resolved_outcome is None:
            return 0.0
        return self.resolved_outcome.realized_profit_and_loss_usd

    @property
    def realized_profit_and_loss_percentage(self) -> float:
        if self.resolved_outcome is None:
            return 0.0
        return self.resolved_outcome.realized_profit_and_loss_percentage

    @property
    def holding_duration_minutes(self) -> float:
        if self.resolved_outcome is None:
            return 0.0
        return self.resolved_outcome.holding_duration_minutes

    @property
    def is_profitable(self) -> bool:
        if self.resolved_outcome is None:
            return False
        return self.resolved_outcome.is_profitable

    @property
    def exit_reason(self) -> str:
        if self.resolved_outcome is None:
            return ""
        return self.resolved_outcome.exit_reason

    @property
    def occurred_at(self) -> Optional[datetime]:
        if self.resolved_outcome is None:
            return None
        return self.resolved_outcome.occurred_at


class MetricDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    key: str
    label: str
    accessor: Callable[[AnalyticsOutcomeRecord], float]
    unit: str


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
