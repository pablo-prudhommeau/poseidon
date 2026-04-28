from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ShadowIntelligenceMetricSnapshot(BaseModel):
    metric_key: str
    decile_edges: list[float]
    decile_win_rates: list[float]
    decile_average_pnl: list[float]
    influence_score: float
    winner_deviation: float


class ShadowIntelligenceSnapshot(BaseModel):
    metric_snapshots: list[ShadowIntelligenceMetricSnapshot]
    total_outcomes_analyzed: int
    is_activated: bool
    resolved_outcome_count: int = 0
    elapsed_hours: float = 0.0


class ShadowIntelligenceSnapshotMetricPayload(BaseModel):
    metric_key: str
    candidate_value: Optional[float] = None
    decile_index: int
    decile_win_rate: float
    decile_average_pnl: float
    is_toxic: bool = False
    is_golden: bool = False
    normalized_influence: float = 0.0


class ShadowIntelligenceSnapshotPayload(BaseModel):
    evaluated_metrics: list[ShadowIntelligenceSnapshotMetricPayload] = Field(default_factory=list)


class ShadowIntelligenceStatusSummary(BaseModel):
    resolved_outcome_count: int
    elapsed_hours: float
