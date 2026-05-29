from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TradingShadowingPhase(Enum):
    DISABLED = "DISABLED"
    SYNCING = "SYNCING"
    SHADOWING = "SHADOWING"
    CORTEXING = "CORTEXING"
    BEAR = "BEAR"
    TRADABLE = "TRADABLE"

    @property
    def allows_live_trading(self) -> bool:
        return self in (TradingShadowingPhase.DISABLED, TradingShadowingPhase.TRADABLE)


class TradingShadowingMetricProfile(BaseModel):
    metric_key: str
    bucket_edges: list[float]
    bucket_win_rates: list[float]
    bucket_average_pnl: list[float]
    bucket_average_holding_time: list[float]
    bucket_expected_pnl_velocity: list[float]
    bucket_outlier_hit_rates: list[float]
    bucket_sample_counts: list[int]
    bucket_is_golden: list[bool]
    bucket_is_toxic: list[bool]
    influence_score: float
    winner_deviation: float


class TradingCandidateShadowingMetricEvaluation(BaseModel):
    metric_key: str
    candidate_value: Optional[float] = None
    bucket_index: Optional[int] = None
    bucket_win_rate: Optional[float] = None
    bucket_average_pnl: Optional[float] = None
    bucket_average_holding_time: Optional[float] = None
    bucket_expected_pnl_velocity: Optional[float] = None
    bucket_outlier_hit_rate: Optional[float] = None
    bucket_sample_count: Optional[int] = None
    is_toxic: bool = False
    is_golden: bool = False
    normalized_influence: Optional[float] = None


class TradingShadowingSnapshot(BaseModel):
    regime: TradingShadowingRegime
    metric_profiles: list[TradingShadowingMetricProfile] = Field(default_factory=list)


class TradingShadowingRegime(BaseModel):
    phase: TradingShadowingPhase
    edge_gate_enabled: bool
    cortex_gate_enabled: bool
    fundamentals_gate_enabled: bool
    toxic_metrics_gate_enabled: bool
    resolved_outcome_count: Optional[int] = None
    required_outcome_count: Optional[int] = None
    elapsed_hours: Optional[float] = None
    required_hours: Optional[float] = None
    edge_eligible_outcome_count: Optional[int] = None
    edge_required_outcome_count: Optional[int] = None
    edge_chronicle_profit_factor: Optional[float] = None
    edge_chronicle_profit_factor_threshold: Optional[float] = None
    edge_chronicle_profit_factor_lookback_days: Optional[float] = None
    edge_chronicle_profit_factor_bucket_width_seconds: Optional[int] = None
    edge_chronicle_profit_factor_moving_average_period: Optional[int] = None
    edge_sparse_expected_value_usd: Optional[float] = None
    edge_sparse_expected_value_usd_threshold: Optional[float] = None
    edge_sparse_expected_value_lookback_days: Optional[float] = None
    edge_sparse_expected_value_bucket_width_seconds: Optional[int] = None
    edge_sparse_expected_value_moving_average_period: Optional[int] = None
    metrics_meta_win_rate: Optional[float] = None
    metrics_meta_average_pnl: Optional[float] = None
    metrics_meta_average_holding_time_hours: Optional[float] = None
    metrics_meta_expected_pnl_velocity: Optional[float] = None
    metrics_meta_profit_factor: Optional[float] = None
    metrics_meta_expected_value_usd: Optional[float] = None
    cortex_training_eligible_outcome_count: Optional[int] = None
    cortex_training_required_outcome_count: Optional[int] = None


class TradingCandidateShadowingDiagnostics(BaseModel):
    toxic_metric_count: int = 0
    total_metrics_evaluated: int = 0
    toxic_metric_keys: list[str] = Field(default_factory=list)
    golden_metric_keys: list[str] = Field(default_factory=list)
    notional_boost_factor: float = 1.0
    evaluated_metrics: list[TradingCandidateShadowingMetricEvaluation] = Field(default_factory=list)


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
    cortex_probability: Optional[float] = None
    cortex_toxicity_probability: Optional[float] = None
    cortex_expected_pnl_percentage: Optional[float] = None
    cortex_predicted_holding_time_minutes: Optional[float] = None


class TradingShadowingVerdictChroniclePortfolioEquityPoint(BaseModel):
    timestamp_milliseconds: int
    total_equity_value: float


class TradingShadowingVerdictChronicleMetricPoint(BaseModel):
    timestamp_milliseconds: int
    average_pnl_percentage: float
    average_win_rate_percentage: float
    expected_value_per_trade_usd: float
    portfolio_equity_usd: float
    profit_factor: float
    closed_verdicts_per_hour: float
    average_cortex_prediction_win_rate_percentage: Optional[float] = None
    average_cortex_predicted_holding_time_minutes: Optional[float] = None
    cortex_skill_score_percentage: Optional[float] = None
    cortex_calibration_gap_percentage_points: Optional[float] = None
    cortex_high_conviction_accuracy_percentage: Optional[float] = None
    cortex_high_conviction_share_percentage: Optional[float] = None
    cortex_gate_precision_percentage: Optional[float] = None
    cortex_gate_pass_rate_percentage: Optional[float] = None


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
    cortex_probability: Optional[float] = None


class TradingShadowingVerdictChronicleCortexReliabilityBin(BaseModel):
    predicted_probability_bin_center: float
    mean_predicted_probability: float
    empirical_win_rate: float
    verdict_count: int


class TradingShadowingVerdictChronicleRegimeGatePoint(BaseModel):
    timestamp_milliseconds: int
    regime_profit_factor_sma: Optional[float] = None
    regime_sparse_expected_value_usd_sma: Optional[float] = None
    profit_factor_gate_open: bool = False
    sparse_expected_value_gate_open: bool = False
    hard_gate_open: bool = False


class TradingShadowingVerdictChronicleBucket(BaseModel):
    bucket_label: str
    granularity_seconds: int
    from_datetime: datetime
    to_datetime: datetime
    metrics: list[TradingShadowingVerdictChronicleMetricPoint]
    volumes: list[TradingShadowingVerdictChronicleVolumePoint]
    verdict_cloud: list[TradingShadowingVerdictChronicleVerdictPoint]
    cortex_reliability_diagram: list[TradingShadowingVerdictChronicleCortexReliabilityBin] = Field(default_factory=list)
    regime_gate: list[TradingShadowingVerdictChronicleRegimeGatePoint] = Field(default_factory=list)


class TradingShadowingVerdictChronicleCortexModelRollout(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    activated_at_milliseconds: int
    model_version: str
    feature_set_version: str
    training_record_count: int
    validation_record_count: int
    success_probability_accuracy: float
    is_active: bool
    label: str


class TradingShadowingVerdictChronicle(BaseModel):
    generated_at: datetime
    as_of: datetime
    from_datetime: datetime
    to_datetime: datetime
    total_verdicts_considered: int
    source: str
    buckets: list[TradingShadowingVerdictChronicleBucket]
    cortex_model_rollouts: list[TradingShadowingVerdictChronicleCortexModelRollout] = Field(default_factory=list)


class TradingShadowingVerdictChronicleComputationResult(BaseModel):
    chronicle: TradingShadowingVerdictChronicle
    verdicts: list[TradingShadowingVerdictChronicleVerdict]
