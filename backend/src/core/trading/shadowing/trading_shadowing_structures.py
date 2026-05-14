from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TradingShadowingPhase(Enum):
    DISABLED = "DISABLED"
    LEARNING = "LEARNING"
    ACTIVE = "ACTIVE"


class TradingShadowingIntelligenceMetricSnapshot(BaseModel):
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


class TradingShadowingIntelligenceMetric(BaseModel):
    metric_key: str
    candidate_value: Optional[float] = None
    bucket_index: Optional[int] = None
    bucket_win_rate: Optional[float] = None
    bucket_average_pnl: Optional[float] = None
    bucket_average_holding_time: Optional[float] = None
    bucket_capital_velocity: Optional[float] = None
    bucket_outlier_hit_rate: Optional[float] = None
    bucket_sample_count: Optional[int] = None
    is_toxic: bool = False
    is_golden: bool = False
    normalized_influence: Optional[float] = None


class TradingShadowingIntelligenceSummary(BaseModel):
    phase: TradingShadowingPhase
    total_outcomes_analyzed: int
    resolved_outcome_count: int = 0
    resolved_shadowing_and_cortex_inference_aware_outcome_count: int = 0
    elapsed_hours: float = 0.0
    meta_win_rate: Optional[float] = None
    meta_average_pnl: Optional[float] = None
    meta_average_holding_time_hours: Optional[float] = None
    meta_capital_velocity: Optional[float] = None
    meta_profit_factor: Optional[float] = None
    meta_expected_value_usd: Optional[float] = None
    chronicle_profit_factor: Optional[float] = None
    sparse_expected_value_usd: Optional[float] = None
    chronicle_profit_factor_threshold: Optional[float] = None
    sparse_expected_value_usd_threshold: Optional[float] = None


class TradingShadowingIntelligenceSnapshot(BaseModel):
    summary: TradingShadowingIntelligenceSummary
    metric_snapshots: list[TradingShadowingIntelligenceMetricSnapshot] = Field(default_factory=list)
    metrics: list[TradingShadowingIntelligenceMetric] = Field(default_factory=list)


class TradingShadowingStatusSummary(BaseModel):
    resolved_outcome_count: int
    resolved_shadowing_and_cortex_inference_aware_outcome_count: int
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
