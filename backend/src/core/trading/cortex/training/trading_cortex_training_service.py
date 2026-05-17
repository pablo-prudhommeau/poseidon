from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy
import xgboost

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_feature_catalog import trading_cortex_poseidon_shadow_ordered_feature_names
from src.core.trading.cortex.training.trading_cortex_training_dataset_service import TradingCortexTrainingDatasetService
from src.core.trading.cortex.training.trading_cortex_training_structures import (
    TradingCortexModelEvaluationMetrics,
    TradingCortexTrainedModelArtifacts,
    TradingCortexTrainingRunRequest,
    TradingCortexTrainingFeatureImportanceEntry,
    TradingCortexTrainingLabelDistribution,
    TradingCortexTrainingTargetDistribution,
    TradingCortexTrainingExitReasonDistribution,
    TradingCortexTrainingSummary,
)
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingCortexModelManifest

logger = get_application_logger(__name__)

TRADING_CORTEX_XGBOOST_TRAINING_PARAMETERS: dict[str, object] = {
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "min_child_weight": 8.0,
    "gamma": 0.3,
    "lambda": 1.0,
    "alpha": 0.0,
    "num_boost_round": 700,
    "early_stopping_rounds": 50,
}


class TradingCortexTrainingService:
    def __init__(self, training_dataset_service: TradingCortexTrainingDatasetService) -> None:
        self._training_dataset_service = training_dataset_service

    def run_training(self, training_run_request: TradingCortexTrainingRunRequest) -> TradingCortexTrainedModelArtifacts:
        if not settings.TRADING_SHADOWING_ENABLED:
            raise RuntimeError(
                "[TRADING][CORTEX][TRAINING] Shadowing must be enabled to train; "
                "training on data without shadow verdicts would produce biased models"
            )

        ordered_feature_names = self._resolve_ordered_feature_names(training_run_request.feature_set_version)
        prepared_training_dataset, latest_resolved_at = self._training_dataset_service.build_training_dataset(
            training_run_request=training_run_request,
            ordered_feature_names=ordered_feature_names,
        )

        training_start_time = time.perf_counter()

        success_probability_booster, success_training_device = self._train_binary_probability_model(
            training_feature_matrix=prepared_training_dataset.training_feature_matrix,
            training_labels=prepared_training_dataset.training_success_labels,
            validation_feature_matrix=prepared_training_dataset.validation_feature_matrix,
            validation_labels=prepared_training_dataset.validation_success_labels,
            preferred_training_device=training_run_request.preferred_training_device,
            evaluation_metric_name="logloss",
        )
        toxicity_probability_booster, toxicity_training_device = self._train_binary_probability_model(
            training_feature_matrix=prepared_training_dataset.training_feature_matrix,
            training_labels=prepared_training_dataset.training_toxicity_labels,
            validation_feature_matrix=prepared_training_dataset.validation_feature_matrix,
            validation_labels=prepared_training_dataset.validation_toxicity_labels,
            preferred_training_device=training_run_request.preferred_training_device,
            evaluation_metric_name="logloss",
        )
        expected_profit_and_loss_percentage_booster, regression_training_device = self._train_regression_model(
            training_feature_matrix=prepared_training_dataset.training_feature_matrix,
            training_targets=prepared_training_dataset.training_expected_profit_and_loss_percentages,
            validation_feature_matrix=prepared_training_dataset.validation_feature_matrix,
            validation_targets=prepared_training_dataset.validation_expected_profit_and_loss_percentages,
            preferred_training_device=training_run_request.preferred_training_device,
        )

        success_probability_predictions = success_probability_booster.inplace_predict(
            prepared_training_dataset.validation_feature_matrix
        )
        toxicity_probability_predictions = toxicity_probability_booster.inplace_predict(
            prepared_training_dataset.validation_feature_matrix
        )
        expected_profit_and_loss_predictions = expected_profit_and_loss_percentage_booster.inplace_predict(
            prepared_training_dataset.validation_feature_matrix
        )

        model_evaluation_metrics = TradingCortexModelEvaluationMetrics(
            training_record_count=prepared_training_dataset.training_record_count,
            validation_record_count=prepared_training_dataset.validation_record_count,
            success_probability_log_loss=self._compute_binary_log_loss(
                prepared_training_dataset.validation_success_labels,
                success_probability_predictions,
            ),
            success_probability_accuracy=self._compute_binary_accuracy(
                prepared_training_dataset.validation_success_labels,
                success_probability_predictions,
            ),
            toxicity_probability_log_loss=self._compute_binary_log_loss(
                prepared_training_dataset.validation_toxicity_labels,
                toxicity_probability_predictions,
            ),
            toxicity_probability_accuracy=self._compute_binary_accuracy(
                prepared_training_dataset.validation_toxicity_labels,
                toxicity_probability_predictions,
            ),
            expected_profit_and_loss_root_mean_squared_error=self._compute_root_mean_squared_error(
                prepared_training_dataset.validation_expected_profit_and_loss_percentages,
                expected_profit_and_loss_predictions,
            ),
        )

        model_version = datetime.now().astimezone().strftime("%Y-%m-%dT%H-%M-%S")
        model_output_directory = Path(training_run_request.model_output_directory) / model_version
        model_output_directory.mkdir(parents=True, exist_ok=True)

        success_model_path = model_output_directory / "success_probability.ubj"
        toxicity_model_path = model_output_directory / "toxicity_probability.ubj"
        expected_profit_and_loss_model_path = model_output_directory / "expected_profit_and_loss_percentage.ubj"

        success_probability_booster.save_model(success_model_path)
        toxicity_probability_booster.save_model(toxicity_model_path)
        expected_profit_and_loss_percentage_booster.save_model(expected_profit_and_loss_model_path)

        training_summary = self._build_training_summary(
            success_probability_booster=success_probability_booster,
            toxicity_probability_booster=toxicity_probability_booster,
            expected_profit_and_loss_percentage_booster=expected_profit_and_loss_percentage_booster,
            training_success_labels=prepared_training_dataset.training_success_labels,
            training_toxicity_labels=prepared_training_dataset.training_toxicity_labels,
            training_expected_profit_and_loss_percentages=prepared_training_dataset.training_expected_profit_and_loss_percentages,
            exit_reasons=prepared_training_dataset.training_exit_reasons,
            ordered_feature_names=ordered_feature_names,
            training_device=success_training_device,
            excluded_staled_verdict_count=prepared_training_dataset.excluded_staled_verdict_count,
        )

        with get_database_session() as session:
            from sqlalchemy import update
            session.execute(
                update(TradingCortexModelManifest)
                .where(TradingCortexModelManifest.is_active == True)
                .values(is_active=False)
            )

            new_manifest = TradingCortexModelManifest(
                model_version=model_version,
                feature_set_version=training_run_request.feature_set_version,
                ordered_feature_names=ordered_feature_names,
                success_probability_model_path=str(success_model_path),
                toxicity_probability_model_path=str(toxicity_model_path),
                expected_profit_and_loss_model_path=str(expected_profit_and_loss_model_path),
                training_record_count=model_evaluation_metrics.training_record_count,
                validation_record_count=model_evaluation_metrics.validation_record_count,
                training_duration_seconds=time.perf_counter() - training_start_time,
                dataset_window_start_at=prepared_training_dataset.dataset_window_start_at,
                dataset_window_end_at=prepared_training_dataset.dataset_window_end_at,
                success_probability_log_loss=model_evaluation_metrics.success_probability_log_loss,
                success_probability_accuracy=model_evaluation_metrics.success_probability_accuracy,
                toxicity_probability_log_loss=model_evaluation_metrics.toxicity_probability_log_loss,
                toxicity_probability_accuracy=model_evaluation_metrics.toxicity_probability_accuracy,
                expected_profit_and_loss_root_mean_squared_error=model_evaluation_metrics.expected_profit_and_loss_root_mean_squared_error,
                training_summary=training_summary.model_dump(),
                is_active=True,
                created_at=get_current_local_datetime(),
            )
            session.add(new_manifest)
            session.commit()

        logger.info(
            "[TRADING][CORTEX][TRAINING] Completed training version=%s train=%d validation=%d staled_excluded=%d",
            model_version,
            prepared_training_dataset.training_record_count,
            prepared_training_dataset.validation_record_count,
            prepared_training_dataset.excluded_staled_verdict_count,
        )

        return TradingCortexTrainedModelArtifacts(
            success_probability_model_path=str(success_model_path),
            toxicity_probability_model_path=str(toxicity_model_path),
            expected_profit_and_loss_percentage_model_path=str(expected_profit_and_loss_model_path),
            model_version=model_version,
            feature_set_version=training_run_request.feature_set_version,
            ordered_feature_names=ordered_feature_names,
            metrics=model_evaluation_metrics,
        )

    def _resolve_ordered_feature_names(self, feature_set_version: str) -> list[str]:
        if feature_set_version == settings.TRADING_CORTEX_FEATURE_SET_VERSION:
            return trading_cortex_poseidon_shadow_ordered_feature_names
        raise ValueError(f"Unsupported feature set version: {feature_set_version}")

    def _train_binary_probability_model(
            self,
            training_feature_matrix: numpy.ndarray,
            training_labels: numpy.ndarray,
            validation_feature_matrix: numpy.ndarray,
            validation_labels: numpy.ndarray,
            preferred_training_device: str,
            evaluation_metric_name: str,
    ) -> tuple[xgboost.Booster, str]:
        scale_pos_weight = self._compute_scale_pos_weight(training_labels)
        return self._train_with_fallback(
            training_feature_matrix=training_feature_matrix,
            training_targets=training_labels,
            validation_feature_matrix=validation_feature_matrix,
            validation_targets=validation_labels,
            preferred_training_device=preferred_training_device,
            objective_name="binary:logistic",
            evaluation_metric_name=evaluation_metric_name,
            extra_parameters={"scale_pos_weight": scale_pos_weight},
        )

    def _train_regression_model(
            self,
            training_feature_matrix: numpy.ndarray,
            training_targets: numpy.ndarray,
            validation_feature_matrix: numpy.ndarray,
            validation_targets: numpy.ndarray,
            preferred_training_device: str,
    ) -> tuple[xgboost.Booster, str]:
        return self._train_with_fallback(
            training_feature_matrix=training_feature_matrix,
            training_targets=training_targets,
            validation_feature_matrix=validation_feature_matrix,
            validation_targets=validation_targets,
            preferred_training_device=preferred_training_device,
            objective_name="reg:pseudohubererror",
            evaluation_metric_name="rmse",
        )

    def _train_with_fallback(
            self,
            training_feature_matrix: numpy.ndarray,
            training_targets: numpy.ndarray,
            validation_feature_matrix: numpy.ndarray,
            validation_targets: numpy.ndarray,
            preferred_training_device: str,
            objective_name: str,
            evaluation_metric_name: str,
            extra_parameters: dict[str, float] | None = None,
    ) -> tuple[xgboost.Booster, str]:
        for training_device in self._resolve_training_devices(preferred_training_device):
            try:
                return self._train_booster(
                    training_feature_matrix=training_feature_matrix,
                    training_targets=training_targets,
                    validation_feature_matrix=validation_feature_matrix,
                    validation_targets=validation_targets,
                    objective_name=objective_name,
                    evaluation_metric_name=evaluation_metric_name,
                    training_device=training_device,
                    extra_parameters=extra_parameters,
                ), training_device
            except Exception:
                logger.exception(
                    "[TRADING][CORTEX][TRAINING] Failed training objective=%s on device=%s",
                    objective_name,
                    training_device,
                )
        raise RuntimeError(f"Unable to train objective {objective_name} on any configured device")

    def _train_booster(
            self,
            training_feature_matrix: numpy.ndarray,
            training_targets: numpy.ndarray,
            validation_feature_matrix: numpy.ndarray,
            validation_targets: numpy.ndarray,
            objective_name: str,
            evaluation_metric_name: str,
            training_device: str,
            extra_parameters: dict[str, float] | None = None,
    ) -> xgboost.Booster:
        logger.info(
            "[TRADING][CORTEX][TRAINING][BOOSTER] Training targets objective=%s: min=%.2f, max=%.2f, mean=%.2f",
            objective_name,
            float(numpy.min(training_targets)),
            float(numpy.max(training_targets)),
            float(numpy.mean(training_targets)),
        )
        training_matrix = xgboost.QuantileDMatrix(training_feature_matrix, training_targets)
        validation_matrix = xgboost.QuantileDMatrix(
            validation_feature_matrix,
            validation_targets,
            ref=training_matrix,
        )
        parameter_map: dict[str, object] = dict(TRADING_CORTEX_XGBOOST_TRAINING_PARAMETERS)
        parameter_map["objective"] = objective_name
        parameter_map["eval_metric"] = evaluation_metric_name
        parameter_map["tree_method"] = "hist"
        parameter_map["device"] = training_device
        parameter_map["seed"] = 42

        num_boost_round = int(parameter_map.pop("num_boost_round", 700))
        early_stopping_rounds = int(parameter_map.pop("early_stopping_rounds", 50))

        if extra_parameters is not None:
            parameter_map.update(extra_parameters)
        logger.info(
            "[TRADING][CORTEX][TRAINING] Training objective=%s eval=%s on device=%s",
            objective_name,
            evaluation_metric_name,
            training_device,
        )
        booster = xgboost.train(
            params=parameter_map,
            dtrain=training_matrix,
            num_boost_round=num_boost_round,
            evals=[(validation_matrix, "validation")],
            early_stopping_rounds=early_stopping_rounds,
            verbose_eval=False,
        )
        return booster

    def _resolve_training_devices(self, preferred_training_device: str) -> list[str]:
        if preferred_training_device == "cuda":
            return ["cuda", "cpu"]
        return [preferred_training_device]

    def _compute_scale_pos_weight(self, training_labels: numpy.ndarray) -> float:
        positive_count = float(numpy.sum(training_labels == 1.0))
        negative_count = float(numpy.sum(training_labels == 0.0))
        if positive_count <= 0:
            return 1.0
        return negative_count / positive_count

    def _compute_binary_log_loss(
            self,
            expected_labels: numpy.ndarray,
            predicted_probabilities: numpy.ndarray,
    ) -> float:
        clipped_probabilities = numpy.clip(predicted_probabilities, 1e-6, 1.0 - 1e-6)
        losses = -(
                expected_labels * numpy.log(clipped_probabilities)
                + (1.0 - expected_labels) * numpy.log(1.0 - clipped_probabilities)
        )
        return float(numpy.mean(losses))

    def _compute_binary_accuracy(
            self,
            expected_labels: numpy.ndarray,
            predicted_probabilities: numpy.ndarray,
    ) -> float:
        predicted_labels = (predicted_probabilities >= 0.5).astype(numpy.float32)
        return float(numpy.mean(predicted_labels == expected_labels))

    def _compute_root_mean_squared_error(
            self,
            expected_targets: numpy.ndarray,
            predicted_targets: numpy.ndarray,
    ) -> float:
        squared_errors = numpy.square(expected_targets - predicted_targets)
        return float(numpy.sqrt(numpy.mean(squared_errors)))

    def _build_training_summary(
            self,
            success_probability_booster: xgboost.Booster,
            toxicity_probability_booster: xgboost.Booster,
            expected_profit_and_loss_percentage_booster: xgboost.Booster,
            training_success_labels: numpy.ndarray,
            training_toxicity_labels: numpy.ndarray,
            training_expected_profit_and_loss_percentages: numpy.ndarray,
            exit_reasons: list[str],
            ordered_feature_names: list[str],
            training_device: str,
            excluded_staled_verdict_count: int,
    ) -> TradingCortexTrainingSummary:
        feature_importance_entries = self._extract_feature_importance(
            success_probability_booster,
            ordered_feature_names,
        )

        success_label_distribution = self._build_label_distribution(training_success_labels)
        toxicity_label_distribution = self._build_label_distribution(training_toxicity_labels)
        target_distribution = self._build_target_distribution(training_expected_profit_and_loss_percentages)
        exit_reason_distribution = self._build_exit_reason_distribution(exit_reasons)

        return TradingCortexTrainingSummary(
            training_device=training_device,
            xgboost_parameters=TRADING_CORTEX_XGBOOST_TRAINING_PARAMETERS,
            best_iteration_success_probability=self._extract_best_iteration(success_probability_booster),
            best_iteration_toxicity_probability=self._extract_best_iteration(toxicity_probability_booster),
            best_iteration_expected_profit_and_loss=self._extract_best_iteration(expected_profit_and_loss_percentage_booster),
            success_label_distribution=success_label_distribution,
            toxicity_label_distribution=toxicity_label_distribution,
            expected_profit_and_loss_target_distribution=target_distribution,
            exit_reason_distribution=exit_reason_distribution,
            feature_importance_by_gain=feature_importance_entries,
            excluded_staled_verdict_count=excluded_staled_verdict_count,
        )

    def _extract_feature_importance(
            self,
            booster: xgboost.Booster,
            ordered_feature_names: list[str],
    ) -> list[TradingCortexTrainingFeatureImportanceEntry]:
        gain_scores: dict[str, float] = booster.get_score(importance_type="gain")
        weight_scores: dict[str, float] = booster.get_score(importance_type="weight")
        cover_scores: dict[str, float] = booster.get_score(importance_type="cover")

        feature_name_by_index: dict[str, str] = {
            f"f{index}": feature_name
            for index, feature_name in enumerate(ordered_feature_names)
        }

        entries: list[TradingCortexTrainingFeatureImportanceEntry] = []
        for raw_key in gain_scores:
            feature_name = feature_name_by_index.get(raw_key, raw_key)
            entries.append(TradingCortexTrainingFeatureImportanceEntry(
                feature_name=feature_name,
                gain=gain_scores.get(raw_key, 0.0),
                weight=weight_scores.get(raw_key, 0.0),
                cover=cover_scores.get(raw_key, 0.0),
            ))

        entries.sort(key=lambda entry: entry.gain, reverse=True)
        return entries

    def _extract_best_iteration(self, booster: xgboost.Booster) -> Optional[int]:
        best_iteration: int = booster.best_iteration
        return best_iteration if best_iteration >= 0 else None

    def _build_label_distribution(
            self,
            labels: numpy.ndarray,
    ) -> TradingCortexTrainingLabelDistribution:
        total_count: int = len(labels)
        positive_count: int = int(numpy.sum(labels == 1.0))
        negative_count: int = total_count - positive_count
        positive_ratio: float = positive_count / total_count if total_count > 0 else 0.0
        scale_pos_weight: float = negative_count / positive_count if positive_count > 0 else 1.0
        return TradingCortexTrainingLabelDistribution(
            total_count=total_count,
            positive_count=positive_count,
            negative_count=negative_count,
            positive_ratio=positive_ratio,
            scale_pos_weight=scale_pos_weight,
        )

    def _build_target_distribution(
            self,
            targets: numpy.ndarray,
    ) -> TradingCortexTrainingTargetDistribution:
        total_count: int = len(targets)
        return TradingCortexTrainingTargetDistribution(
            total_count=total_count,
            minimum=float(numpy.min(targets)),
            maximum=float(numpy.max(targets)),
            mean=float(numpy.mean(targets)),
            median=float(numpy.median(targets)),
            standard_deviation=float(numpy.std(targets)),
            percentile_5=float(numpy.percentile(targets, 5)),
            percentile_25=float(numpy.percentile(targets, 25)),
            percentile_75=float(numpy.percentile(targets, 75)),
            percentile_95=float(numpy.percentile(targets, 95)),
        )

    def _build_exit_reason_distribution(
            self,
            exit_reasons: list[str],
    ) -> TradingCortexTrainingExitReasonDistribution:
        total_count: int = len(exit_reasons)
        take_profit_2_count: int = sum(1 for reason in exit_reasons if reason == "TAKE_PROFIT_2")
        stop_loss_count: int = sum(1 for reason in exit_reasons if reason == "STOP_LOSS")
        lethargic_count: int = sum(1 for reason in exit_reasons if reason == "LETHARGIC")
        safe_total: float = max(1.0, float(total_count))
        return TradingCortexTrainingExitReasonDistribution(
            take_profit_2_count=take_profit_2_count,
            stop_loss_count=stop_loss_count,
            lethargic_count=lethargic_count,
            take_profit_2_ratio=take_profit_2_count / safe_total,
            stop_loss_ratio=stop_loss_count / safe_total,
            lethargic_ratio=lethargic_count / safe_total,
        )
