from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import numpy
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.trading.cortex.promotion.trading_cortex_promotion_structures import (
    TradingCortexForwardSelectionMetrics,
    TradingCortexPromotionEvaluation,
)
from src.core.trading.cortex.trading_cortex_feature_vector_builder import TradingCortexFeatureVectorBuilder
from src.core.trading.cortex.trading_cortex_model_registry_service import (
    TradingCortexModelBundle,
    build_model_bundle_from_manifest,
)
from src.core.trading.cortex.trading_cortex_quantile_gate_service import compute_quantile
from src.core.trading.cortex.trading_cortex_structures import TradingCortexBatchPrediction, TradingCortexFeatureVectorSnapshot
from src.core.trading.cortex.training.trading_cortex_training_dataset_service import TradingCortexTrainingDatasetService
from src.core.utils.date_utils import ensure_timezone_aware, get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingCortexModelManifest, TradingCortexModelRole, TradingShadowingVerdict

logger = get_application_logger(__name__)

_EVALUATION_STREAM_BATCH_SIZE = 2000
_STALED_EXIT_REASON = "STALED"


class TradingCortexPromotionService:
    def __init__(self, training_dataset_service: TradingCortexTrainingDatasetService) -> None:
        self._training_dataset_service: TradingCortexTrainingDatasetService = training_dataset_service

    def evaluate_and_promote_challenger(self) -> Optional[TradingCortexPromotionEvaluation]:
        with get_database_session() as database_session:
            champion_manifest: Optional[TradingCortexModelManifest] = self._retrieve_manifest_for_role(
                database_session,
                TradingCortexModelRole.CHAMPION,
            )
            challenger_manifest: Optional[TradingCortexModelManifest] = self._retrieve_manifest_for_role(
                database_session,
                TradingCortexModelRole.CHALLENGER,
            )

            if champion_manifest is None or challenger_manifest is None:
                logger.debug(
                    "[TRADING][CORTEX][PROMOTION] Nothing to arbitrate (champion=%s, challenger=%s)",
                    champion_manifest.model_version if champion_manifest is not None else "none",
                    challenger_manifest.model_version if challenger_manifest is not None else "none",
                )
                return None

            challenger_created_at: datetime = ensure_timezone_aware(challenger_manifest.created_at)
            minimum_challenger_age: timedelta = timedelta(hours=settings.TRADING_CORTEX_PROMOTION_MIN_CHALLENGER_AGE_HOURS)
            if get_current_local_datetime() - challenger_created_at < minimum_challenger_age:
                logger.debug(
                    "[TRADING][CORTEX][PROMOTION] Challenger %s is younger than %.1fh, forward evaluation postponed",
                    challenger_manifest.model_version,
                    settings.TRADING_CORTEX_PROMOTION_MIN_CHALLENGER_AGE_HOURS,
                )
                return None

            champion_bundle: TradingCortexModelBundle = build_model_bundle_from_manifest(champion_manifest)
            challenger_bundle: TradingCortexModelBundle = build_model_bundle_from_manifest(challenger_manifest)
            if not champion_bundle.is_complete or not challenger_bundle.is_complete:
                logger.warning(
                    "[TRADING][CORTEX][PROMOTION] Incomplete artifacts (champion_complete=%s, challenger_complete=%s), arbitration skipped",
                    champion_bundle.is_complete,
                    challenger_bundle.is_complete,
                )
                return None

            evaluation: Optional[TradingCortexPromotionEvaluation] = self._evaluate_forward_window(
                database_session=database_session,
                champion_bundle=champion_bundle,
                challenger_bundle=challenger_bundle,
                forward_window_start_at=challenger_created_at,
            )
            if evaluation is None:
                return None

            if evaluation.promoted:
                self._apply_promotion(
                    database_session=database_session,
                    champion_manifest=champion_manifest,
                    challenger_manifest=challenger_manifest,
                )
                database_session.commit()

        self._log_evaluation(evaluation)
        return evaluation

    def _evaluate_forward_window(
            self,
            database_session: Session,
            champion_bundle: TradingCortexModelBundle,
            challenger_bundle: TradingCortexModelBundle,
            forward_window_start_at: datetime,
    ) -> Optional[TradingCortexPromotionEvaluation]:
        champion_feature_rows: list[list[float]] = []
        challenger_feature_rows: list[list[float]] = []
        realized_profit_and_loss_percentages: list[float] = []
        profitable_flags: list[float] = []
        fragile_flags: list[float] = []
        staled_flags: list[float] = []

        verdict_dao: TradingShadowingVerdictDao = TradingShadowingVerdictDao(database_session)
        for verdict in verdict_dao.stream_resolved_for_cortex_evaluation(
                batch_size=_EVALUATION_STREAM_BATCH_SIZE,
                resolved_since=forward_window_start_at,
                limit_count=settings.TRADING_CORTEX_PROMOTION_MAX_SAMPLE_COUNT,
        ):
            probe = verdict.probe
            champion_feature_values, challenger_feature_values = self._build_feature_rows(
                verdict=verdict,
                champion_bundle=champion_bundle,
                challenger_bundle=challenger_bundle,
            )
            if champion_feature_values is not None and challenger_feature_values is not None:
                champion_feature_rows.append(champion_feature_values)
                challenger_feature_rows.append(challenger_feature_values)
                realized_profit_and_loss_percentages.append(verdict.realized_pnl_percentage)
                profitable_flags.append(1.0 if verdict.is_profitable else 0.0)
                fragile_flags.append(self._resolve_fragility_flag(verdict))
                staled_flags.append(1.0 if verdict.exit_reason == _STALED_EXIT_REASON else 0.0)

            database_session.expunge(verdict)
            if probe is not None:
                database_session.expunge(probe)

        evaluated_record_count: int = len(champion_feature_rows)
        minimum_forward_verdict_count: int = settings.TRADING_CORTEX_PROMOTION_MIN_FORWARD_VERDICT_COUNT
        if evaluated_record_count < minimum_forward_verdict_count:
            logger.info(
                "[TRADING][CORTEX][PROMOTION] Only %d / %d forward verdicts since %s, arbitration postponed",
                evaluated_record_count,
                minimum_forward_verdict_count,
                forward_window_start_at,
            )
            return None

        realized_profit_and_loss_array: numpy.ndarray = numpy.asarray(realized_profit_and_loss_percentages, dtype=numpy.float64)
        profitable_array: numpy.ndarray = numpy.asarray(profitable_flags, dtype=numpy.float64)
        fragile_array: numpy.ndarray = numpy.asarray(fragile_flags, dtype=numpy.float64)
        staled_array: numpy.ndarray = numpy.asarray(staled_flags, dtype=numpy.float64)

        champion_metrics: TradingCortexForwardSelectionMetrics = self._compute_forward_selection_metrics(
            bundle=champion_bundle,
            feature_matrix=numpy.asarray(champion_feature_rows, dtype=numpy.float32),
            realized_profit_and_loss_percentages=realized_profit_and_loss_array,
            profitable_flags=profitable_array,
            fragile_flags=fragile_array,
            staled_flags=staled_array,
        )
        challenger_metrics: TradingCortexForwardSelectionMetrics = self._compute_forward_selection_metrics(
            bundle=challenger_bundle,
            feature_matrix=numpy.asarray(challenger_feature_rows, dtype=numpy.float32),
            realized_profit_and_loss_percentages=realized_profit_and_loss_array,
            profitable_flags=profitable_array,
            fragile_flags=fragile_array,
            staled_flags=staled_array,
        )

        average_profit_and_loss_uplift_percentage: float = (
                challenger_metrics.selected_average_profit_and_loss_percentage
                - champion_metrics.selected_average_profit_and_loss_percentage
        )
        fragility_rate_increase: float = challenger_metrics.selected_fragility_rate - champion_metrics.selected_fragility_rate
        rejection_reason: Optional[str] = self._resolve_rejection_reason(
            champion_metrics=champion_metrics,
            challenger_metrics=challenger_metrics,
            average_profit_and_loss_uplift_percentage=average_profit_and_loss_uplift_percentage,
            fragility_rate_increase=fragility_rate_increase,
        )

        return TradingCortexPromotionEvaluation(
            champion_metrics=champion_metrics,
            challenger_metrics=challenger_metrics,
            average_profit_and_loss_uplift_percentage=average_profit_and_loss_uplift_percentage,
            fragility_rate_increase=fragility_rate_increase,
            promoted=rejection_reason is None,
            rejection_reason=rejection_reason,
        )

    def _build_feature_rows(
            self,
            verdict: TradingShadowingVerdict,
            champion_bundle: TradingCortexModelBundle,
            challenger_bundle: TradingCortexModelBundle,
    ) -> tuple[Optional[list[float]], Optional[list[float]]]:
        champion_snapshot: Optional[TradingCortexFeatureVectorSnapshot] = (
            self._training_dataset_service.build_feature_vector_snapshot(verdict, champion_bundle.feature_set_version)
        )
        if champion_snapshot is None:
            return None, None

        challenger_snapshot: Optional[TradingCortexFeatureVectorSnapshot] = champion_snapshot
        if challenger_bundle.feature_set_version != champion_bundle.feature_set_version:
            challenger_snapshot = self._training_dataset_service.build_feature_vector_snapshot(
                verdict,
                challenger_bundle.feature_set_version,
            )
            if challenger_snapshot is None:
                return None, None

        return (
            champion_snapshot.extract_ordered_feature_values(champion_bundle.ordered_feature_names),
            challenger_snapshot.extract_ordered_feature_values(challenger_bundle.ordered_feature_names),
        )

    def _compute_forward_selection_metrics(
            self,
            bundle: TradingCortexModelBundle,
            feature_matrix: numpy.ndarray,
            realized_profit_and_loss_percentages: numpy.ndarray,
            profitable_flags: numpy.ndarray,
            fragile_flags: numpy.ndarray,
            staled_flags: numpy.ndarray,
    ) -> TradingCortexForwardSelectionMetrics:
        batch_prediction: TradingCortexBatchPrediction = bundle.predict_batch(feature_matrix)

        success_probability_threshold: float = self._resolve_selection_threshold(
            batch_prediction.success_probabilities,
            settings.TRADING_CORTEX_QUANTILE_GATE_SUCCESS_PROBABILITY_QUANTILE,
        )
        toxicity_probability_threshold: float = self._resolve_selection_threshold(
            batch_prediction.toxicity_probabilities,
            settings.TRADING_CORTEX_QUANTILE_GATE_TOXICITY_PROBABILITY_QUANTILE,
        )

        fragility_probability_threshold: float = self._resolve_selection_threshold(
            batch_prediction.fragility_probabilities,
            settings.TRADING_CORTEX_QUANTILE_GATE_FRAGILITY_PROBABILITY_QUANTILE,
        )
        selection_mask: numpy.ndarray = (
                (batch_prediction.success_probabilities >= success_probability_threshold)
                & (batch_prediction.toxicity_probabilities <= toxicity_probability_threshold)
                & (batch_prediction.fragility_probabilities <= fragility_probability_threshold)
        )

        minimum_holding_time_minutes: float = settings.TRADING_CORTEX_HOLDING_TIME_MIN_HOURS * 60.0
        maximum_holding_time_minutes: float = settings.TRADING_CORTEX_HOLDING_TIME_MAX_HOURS * 60.0
        selection_mask = (
                selection_mask
                & (batch_prediction.predicted_holding_time_minutes >= minimum_holding_time_minutes)
                & (batch_prediction.predicted_holding_time_minutes <= maximum_holding_time_minutes)
        )

        selected_record_count: int = int(numpy.count_nonzero(selection_mask))
        selected_profit_and_loss_mask: numpy.ndarray = selection_mask & (staled_flags == 0.0)
        selected_profit_and_loss_count: int = int(numpy.count_nonzero(selected_profit_and_loss_mask))

        selected_average_profit_and_loss_percentage: float = (
            float(numpy.mean(realized_profit_and_loss_percentages[selected_profit_and_loss_mask]))
            if selected_profit_and_loss_count > 0
            else 0.0
        )
        selected_win_rate: float = (
            float(numpy.mean(profitable_flags[selected_profit_and_loss_mask])) if selected_profit_and_loss_count > 0 else 0.0
        )
        selected_fragility_rate: float = (
            float(numpy.mean(fragile_flags[selection_mask])) if selected_record_count > 0 else 1.0
        )

        return TradingCortexForwardSelectionMetrics(
            model_version=bundle.model_version,
            evaluated_record_count=int(feature_matrix.shape[0]),
            selected_record_count=selected_record_count,
            selected_average_profit_and_loss_percentage=selected_average_profit_and_loss_percentage,
            selected_win_rate=selected_win_rate,
            selected_fragility_rate=selected_fragility_rate,
            success_probability_threshold=success_probability_threshold,
            toxicity_probability_threshold=toxicity_probability_threshold,
        )

    def _resolve_selection_threshold(self, probabilities: numpy.ndarray, quantile: float) -> float:
        return compute_quantile(sorted(float(probability) for probability in probabilities), quantile)

    def _resolve_rejection_reason(
            self,
            champion_metrics: TradingCortexForwardSelectionMetrics,
            challenger_metrics: TradingCortexForwardSelectionMetrics,
            average_profit_and_loss_uplift_percentage: float,
            fragility_rate_increase: float,
    ) -> Optional[str]:
        minimum_selected_verdict_count: int = settings.TRADING_CORTEX_PROMOTION_MIN_SELECTED_VERDICT_COUNT
        if champion_metrics.selected_record_count < minimum_selected_verdict_count:
            return (
                f"champion selected only {champion_metrics.selected_record_count} / {minimum_selected_verdict_count} verdicts"
            )
        if challenger_metrics.selected_record_count < minimum_selected_verdict_count:
            return (
                f"challenger selected only {challenger_metrics.selected_record_count} / {minimum_selected_verdict_count} verdicts"
            )

        minimum_uplift_percentage: float = settings.TRADING_CORTEX_PROMOTION_MIN_AVERAGE_PNL_UPLIFT_PERCENTAGE
        if average_profit_and_loss_uplift_percentage < minimum_uplift_percentage:
            return (
                f"average pnl uplift {average_profit_and_loss_uplift_percentage:+.2f}% "
                f"below the required {minimum_uplift_percentage:+.2f}%"
            )

        maximum_fragility_rate_increase: float = settings.TRADING_CORTEX_PROMOTION_MAX_FRAGILITY_RATE_INCREASE
        if fragility_rate_increase > maximum_fragility_rate_increase:
            return (
                f"fragility rate increase {fragility_rate_increase:+.3f} "
                f"above the allowed {maximum_fragility_rate_increase:+.3f}"
            )
        return None

    def _apply_promotion(
            self,
            database_session: Session,
            champion_manifest: TradingCortexModelManifest,
            challenger_manifest: TradingCortexModelManifest,
    ) -> None:
        champion_manifest.model_role = TradingCortexModelRole.RETIRED
        champion_manifest.is_active = False
        challenger_manifest.model_role = TradingCortexModelRole.CHAMPION
        challenger_manifest.is_active = True
        challenger_manifest.promoted_at = get_current_local_datetime()
        database_session.add(champion_manifest)
        database_session.add(challenger_manifest)

    def _resolve_fragility_flag(self, verdict: TradingShadowingVerdict) -> float:
        if verdict.exit_reason == _STALED_EXIT_REASON:
            return 1.0
        catastrophic_threshold: float = settings.TRADING_CORTEX_FRAGILITY_CATASTROPHIC_PNL_PERCENTAGE_THRESHOLD
        return 1.0 if verdict.realized_pnl_percentage <= catastrophic_threshold else 0.0

    def _retrieve_manifest_for_role(
            self,
            database_session: Session,
            model_role: TradingCortexModelRole,
    ) -> Optional[TradingCortexModelManifest]:
        statement = (
            select(TradingCortexModelManifest)
            .where(TradingCortexModelManifest.model_role == model_role)
            .order_by(TradingCortexModelManifest.created_at.desc())
            .limit(1)
        )
        return database_session.execute(statement).scalar_one_or_none()

    def _log_evaluation(self, evaluation: TradingCortexPromotionEvaluation) -> None:
        champion_metrics: TradingCortexForwardSelectionMetrics = evaluation.champion_metrics
        challenger_metrics: TradingCortexForwardSelectionMetrics = evaluation.challenger_metrics
        if evaluation.promoted:
            logger.info(
                "[TRADING][CORTEX][PROMOTION] Promoted challenger %s over champion %s on %d forward verdicts "
                "— avg pnl %.2f%% vs %.2f%% (uplift %+.2f%%), win rate %.1f%% vs %.1f%%, fragility %.3f vs %.3f",
                challenger_metrics.model_version,
                champion_metrics.model_version,
                champion_metrics.evaluated_record_count,
                challenger_metrics.selected_average_profit_and_loss_percentage,
                champion_metrics.selected_average_profit_and_loss_percentage,
                evaluation.average_profit_and_loss_uplift_percentage,
                challenger_metrics.selected_win_rate * 100.0,
                champion_metrics.selected_win_rate * 100.0,
                challenger_metrics.selected_fragility_rate,
                champion_metrics.selected_fragility_rate,
            )
            return
        logger.info(
            "[TRADING][CORTEX][PROMOTION] Kept champion %s over challenger %s on %d forward verdicts — %s",
            champion_metrics.model_version,
            challenger_metrics.model_version,
            champion_metrics.evaluated_record_count,
            evaluation.rejection_reason,
        )


def build_trading_cortex_promotion_service() -> TradingCortexPromotionService:
    feature_vector_builder: TradingCortexFeatureVectorBuilder = TradingCortexFeatureVectorBuilder()
    training_dataset_service: TradingCortexTrainingDatasetService = TradingCortexTrainingDatasetService(
        feature_vector_builder=feature_vector_builder,
    )
    return TradingCortexPromotionService(training_dataset_service=training_dataset_service)
