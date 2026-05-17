from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy
from pydantic import BaseModel, ConfigDict

from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexCandidateFeatureSnapshot,
    TradingCortexShadowMetricFeatureSnapshot,
    TradingCortexShadowRegimeFeatureSnapshot,
)


class TradingCortexShadowTrainingRecord(BaseModel):
    probe_identifier: int
    resolved_at: datetime
    candidate_features: TradingCortexCandidateFeatureSnapshot
    shadow_regime_features: TradingCortexShadowRegimeFeatureSnapshot
    shadow_metric_features: list[TradingCortexShadowMetricFeatureSnapshot]
    realized_profit_and_loss_percentage: float
    realized_profit_and_loss_usd: float
    holding_duration_minutes: float
    is_profitable: bool
    exit_reason: str


class TradingCortexPreparedTrainingDataset(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    feature_set_version: str
    ordered_feature_names: list[str]
    training_feature_matrix: numpy.ndarray
    validation_feature_matrix: numpy.ndarray
    training_success_labels: numpy.ndarray
    validation_success_labels: numpy.ndarray
    training_toxicity_labels: numpy.ndarray
    validation_toxicity_labels: numpy.ndarray
    training_expected_profit_and_loss_percentages: numpy.ndarray
    validation_expected_profit_and_loss_percentages: numpy.ndarray
    training_exit_reasons: list[str]
    training_record_count: int
    validation_record_count: int
    excluded_staled_verdict_count: int
    dataset_window_start_at: datetime
    dataset_window_end_at: datetime


class TradingCortexModelEvaluationMetrics(BaseModel):
    training_record_count: int
    validation_record_count: int
    success_probability_log_loss: float
    success_probability_accuracy: float
    toxicity_probability_log_loss: float
    toxicity_probability_accuracy: float
    expected_profit_and_loss_root_mean_squared_error: float


class TradingCortexInsufficientTrainingDataError(Exception):
    def __init__(self, required_count: int, found_count: int) -> None:
        self.required_count = required_count
        self.found_count = found_count
        super().__init__(f"Expected at least {required_count} labeled records, found {found_count}")


class TradingCortexTrainedModelArtifacts(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    success_probability_model_path: str
    toxicity_probability_model_path: str
    expected_profit_and_loss_percentage_model_path: str
    model_version: str
    feature_set_version: str
    ordered_feature_names: list[str]
    metrics: TradingCortexModelEvaluationMetrics


class TradingCortexTrainingRunRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    feature_set_version: str
    model_output_directory: str
    validation_fraction: float
    minimum_labeled_record_count: int
    preferred_training_device: str


class TradingCortexTrainingRunSummary(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_output_directory: str
    model_version: str
    feature_set_version: str
    ordered_feature_names: list[str]
    metrics: TradingCortexModelEvaluationMetrics
    training_device_used: str
    latest_resolved_at: Optional[datetime] = None


class TradingCortexTrainingFeatureImportanceEntry(BaseModel):
    feature_name: str
    gain: float
    weight: float
    cover: float


class TradingCortexTrainingLabelDistribution(BaseModel):
    total_count: int
    positive_count: int
    negative_count: int
    positive_ratio: float
    scale_pos_weight: float


class TradingCortexTrainingTargetDistribution(BaseModel):
    total_count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    standard_deviation: float
    percentile_5: float
    percentile_25: float
    percentile_75: float
    percentile_95: float


class TradingCortexTrainingExitReasonDistribution(BaseModel):
    take_profit_2_count: int
    stop_loss_count: int
    lethargic_count: int
    take_profit_2_ratio: float
    stop_loss_ratio: float
    lethargic_ratio: float


class TradingCortexTrainingSummary(BaseModel):
    training_device: str
    xgboost_parameters: dict[str, object]
    best_iteration_success_probability: Optional[int] = None
    best_iteration_toxicity_probability: Optional[int] = None
    best_iteration_expected_profit_and_loss: Optional[int] = None
    success_label_distribution: TradingCortexTrainingLabelDistribution
    toxicity_label_distribution: TradingCortexTrainingLabelDistribution
    expected_profit_and_loss_target_distribution: TradingCortexTrainingTargetDistribution
    exit_reason_distribution: TradingCortexTrainingExitReasonDistribution
    feature_importance_by_gain: list[TradingCortexTrainingFeatureImportanceEntry]
    excluded_staled_verdict_count: int
