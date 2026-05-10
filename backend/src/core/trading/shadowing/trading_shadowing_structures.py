from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field


class ShadowIntelligenceMetricSnapshot(BaseModel):
    metric_key: str
    bucket_edges: list[float]
    bucket_win_rates: list[float]
    bucket_average_pnl: list[float]
    bucket_average_holding_time: list[float]
    bucket_capital_velocity: list[float]
    bucket_outlier_hit_rates: list[float]
    bucket_sample_counts: list[int]
    bucket_is_golden: list[bool]
    bucket_is_toxic: list[bool]
    influence_score: float
    winner_deviation: float


class ShadowIntelligenceSnapshot(BaseModel):
    metric_snapshots: list[ShadowIntelligenceMetricSnapshot]
    total_outcomes_analyzed: int
    is_activated: bool
    resolved_outcome_count: int = 0
    elapsed_hours: float = 0.0
    meta_win_rate: float = 0.0
    meta_average_pnl: float = 0.0
    meta_average_holding_time_hours: float = 0.0
    meta_capital_velocity: float = 0.0
    meta_profit_factor: float = 0.0
    meta_expected_value_usd: float = 0.0
    empirical_profit_factor: float = 0.0
    chronicle_profit_factor: float = 0.0
    sparse_expected_value_usd: float = 0.0
    chronicle_profit_factor_threshold: float = 0.0


class ShadowIntelligenceSnapshotMetricPayload(BaseModel):
    metric_key: str
    candidate_value: Optional[float] = None
    bucket_index: int
    bucket_win_rate: float
    bucket_average_pnl: float
    bucket_average_holding_time: float = 0.0
    bucket_capital_velocity: float = 0.0
    bucket_outlier_hit_rate: float = 0.0
    bucket_sample_count: int = 0
    is_toxic: bool = False
    is_golden: bool = False
    normalized_influence: float = 0.0


class ShadowIntelligenceSnapshotPayload(BaseModel):
    evaluated_metrics: list[ShadowIntelligenceSnapshotMetricPayload] = Field(default_factory=list)


class ShadowIntelligenceStatusSummary(BaseModel):
    resolved_outcome_count: int
    elapsed_hours: float


class TradingShadowingVerdictChronicleBucketConfiguration(BaseModel):
    label: str
    lookback: timedelta
    granularity_seconds: int


class TradingShadowingVerdictChronicleVerdict(BaseModel):
    id: int
    resolved_at: datetime
    realized_pnl_percentage: float
    realized_pnl_usd: float
    is_profitable: bool
    exit_reason: str
    order_notional_value_usd: float


class TradingShadowingVerdictChronicleMetricPoint(BaseModel):
    timestamp_milliseconds: int
    average_pnl_percentage: float
    average_win_rate_percentage: float
    expected_value_per_trade_usd: float
    profit_factor: float
    capital_velocity_per_hour: float


class TradingShadowingVerdictChronicleVolumePoint(BaseModel):
    timestamp_milliseconds: int
    verdict_count: int


class TradingShadowingVerdictChronicleVerdictPoint(BaseModel):
    verdict_id: int
    timestamp_milliseconds: int
    pnl_percentage: float
    pnl_usd: float
    exit_reason: str
    order_notional_usd: float
    point_size: float
    is_profitable: bool


class TradingShadowingVerdictChronicleBucket(BaseModel):
    bucket_label: str
    granularity_seconds: int
    from_datetime: datetime
    to_datetime: datetime
    metrics: list[TradingShadowingVerdictChronicleMetricPoint]
    volumes: list[TradingShadowingVerdictChronicleVolumePoint]
    verdict_cloud: list[TradingShadowingVerdictChronicleVerdictPoint]


class TradingShadowingVerdictChronicle(BaseModel):
    generated_at: datetime
    as_of: datetime
    from_datetime: datetime
    to_datetime: datetime
    total_verdicts_considered: int
    source: str
    buckets: list[TradingShadowingVerdictChronicleBucket]


class TradingShadowingVerdictChronicleComputationResult(BaseModel):
    chronicle: TradingShadowingVerdictChronicle
    verdicts: list[TradingShadowingVerdictChronicleVerdict]
