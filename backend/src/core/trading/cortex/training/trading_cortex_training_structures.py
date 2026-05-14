from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy
from pydantic import BaseModel, ConfigDict

from src.core.trading.cortex.trading_cortex_structures import TradingCortexCandidateFeatureSnapshot


class TradingCortexShadowTrainingRecord(BaseModel):
    probe_identifier: int
    resolved_at: datetime
    candidate_features: TradingCortexCandidateFeatureSnapshot
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
    training_record_count: int
    validation_record_count: int
    dataset_window_start_at: Optional[datetime]
    dataset_window_end_at: Optional[datetime]


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
