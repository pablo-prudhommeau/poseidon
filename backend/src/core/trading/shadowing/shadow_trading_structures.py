from __future__ import annotations

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
