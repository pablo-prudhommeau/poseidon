from __future__ import annotations

from datetime import datetime

import numpy

from src.core.trading.cortex.trading_cortex_feature_vector_builder import TradingCortexFeatureVectorBuilder
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexCandidateFeatureSnapshot,
    TradingCortexScoringRequest,
    TradingCortexShadowingMetricFeatureSnapshot,
    TradingCortexShadowingRegimeFeatureSnapshot,
)
from src.core.trading.cortex.training.trading_cortex_training_structures import (
    TradingCortexInsufficientTrainingDataError,
    TradingCortexPreparedTrainingDataset,
    TradingCortexTrainingRunRequest,
)
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingShadowingVerdict

logger = get_application_logger(__name__)

_TRAINING_STREAM_BATCH_SIZE = 2000
_TRAINING_STREAM_PROGRESS_LOG_INTERVAL = 20000


class TradingCortexTrainingDatasetService:
    def __init__(self, feature_vector_builder: TradingCortexFeatureVectorBuilder) -> None:
        self._feature_vector_builder = feature_vector_builder

    def build_training_dataset(
            self,
            training_run_request: TradingCortexTrainingRunRequest,
            ordered_feature_names: list[str],
    ) -> tuple[TradingCortexPreparedTrainingDataset, datetime]:
        minimum_labeled_record_count = training_run_request.minimum_labeled_record_count
        feature_count = len(ordered_feature_names)

        with get_database_session() as database_session:
            verdict_dao = TradingShadowingVerdictDao(database_session)
            excluded_staled_count = verdict_dao.count_staled_verdicts()
            eligible_record_count = verdict_dao.count_resolved_shadowing_and_cortex_inference_aware_outcomes()
            if eligible_record_count < minimum_labeled_record_count:
                raise TradingCortexInsufficientTrainingDataError(
                    required_count=minimum_labeled_record_count,
                    found_count=eligible_record_count,
                )

            logger.info(
                "[TRADING][CORTEX][TRAINING][DATASET] Streaming %d eligible shadowing rows (batch=%d)",
                eligible_record_count,
                _TRAINING_STREAM_BATCH_SIZE,
            )

            feature_matrix = numpy.empty((eligible_record_count, feature_count), dtype=numpy.float32)
            success_label_array = numpy.empty(eligible_record_count, dtype=numpy.float32)
            toxicity_label_array = numpy.empty(eligible_record_count, dtype=numpy.float32)
            expected_profit_and_loss_percentage_array = numpy.empty(eligible_record_count, dtype=numpy.float32)
            holding_duration_minutes_array = numpy.empty(eligible_record_count, dtype=numpy.float32)
            exit_reasons: list[str] = []

            filled_record_count = 0
            streamed_record_count = 0
            dataset_window_start_at: datetime | None = None
            dataset_window_end_at: datetime | None = None

            for verdict in verdict_dao.stream_resolved_for_cortex_training(batch_size=_TRAINING_STREAM_BATCH_SIZE):
                probe = verdict.probe
                feature_values = self._build_feature_values(verdict, training_run_request, ordered_feature_names)
                if feature_values is not None:
                    feature_matrix[filled_record_count] = feature_values
                    success_label_array[filled_record_count] = 1.0 if verdict.is_profitable else 0.0
                    toxicity_label_array[filled_record_count] = 1.0 if verdict.exit_reason in ("STOP_LOSS", "HONEYPOT") else 0.0
                    expected_profit_and_loss_percentage_array[filled_record_count] = verdict.realized_pnl_percentage
                    holding_duration_minutes_array[filled_record_count] = verdict.holding_duration_minutes
                    exit_reasons.append(verdict.exit_reason)

                    if dataset_window_start_at is None:
                        dataset_window_start_at = verdict.resolved_at
                    dataset_window_end_at = verdict.resolved_at
                    filled_record_count += 1

                database_session.expunge(verdict)
                if probe is not None:
                    database_session.expunge(probe)

                streamed_record_count += 1
                if streamed_record_count % _TRAINING_STREAM_PROGRESS_LOG_INTERVAL == 0:
                    logger.info(
                        "[TRADING][CORTEX][TRAINING][DATASET] Streamed %d/%d rows (%d labeled)",
                        streamed_record_count,
                        eligible_record_count,
                        filled_record_count,
                    )

        logger.info(
            "[TRADING][CORTEX][TRAINING][DATASET] Loaded %d shadowing rows from database (%d STALED excluded)",
            filled_record_count,
            excluded_staled_count,
        )

        labeled_record_count = filled_record_count
        if labeled_record_count < minimum_labeled_record_count:
            raise TradingCortexInsufficientTrainingDataError(
                required_count=minimum_labeled_record_count,
                found_count=labeled_record_count,
            )

        feature_matrix = feature_matrix[:labeled_record_count]
        success_label_array = success_label_array[:labeled_record_count]
        toxicity_label_array = toxicity_label_array[:labeled_record_count]
        expected_profit_and_loss_percentage_array = expected_profit_and_loss_percentage_array[:labeled_record_count]
        holding_duration_minutes_array = holding_duration_minutes_array[:labeled_record_count]

        latest_resolved_at = dataset_window_end_at

        validation_record_count = max(1, int(labeled_record_count * training_run_request.validation_fraction))
        training_record_count = labeled_record_count - validation_record_count
        if training_record_count <= 0:
            raise ValueError("Validation fraction leaves no records for training")

        logger.info(
            "[TRADING][CORTEX][TRAINING][DATASET] Prepared %d labeled records with %d selected features",
            labeled_record_count,
            feature_count,
        )

        prepared_training_dataset = TradingCortexPreparedTrainingDataset(
            feature_set_version=training_run_request.feature_set_version,
            ordered_feature_names=ordered_feature_names,
            training_feature_matrix=feature_matrix[:training_record_count],
            validation_feature_matrix=feature_matrix[training_record_count:],
            training_success_labels=success_label_array[:training_record_count],
            validation_success_labels=success_label_array[training_record_count:],
            training_toxicity_labels=toxicity_label_array[:training_record_count],
            validation_toxicity_labels=toxicity_label_array[training_record_count:],
            training_expected_profit_and_loss_percentages=expected_profit_and_loss_percentage_array[:training_record_count],
            validation_expected_profit_and_loss_percentages=expected_profit_and_loss_percentage_array[training_record_count:],
            training_holding_duration_minutes=holding_duration_minutes_array[:training_record_count],
            validation_holding_duration_minutes=holding_duration_minutes_array[training_record_count:],
            training_exit_reasons=exit_reasons[:training_record_count],
            training_record_count=training_record_count,
            validation_record_count=validation_record_count,
            excluded_staled_verdict_count=excluded_staled_count,
            dataset_window_start_at=dataset_window_start_at,
            dataset_window_end_at=dataset_window_end_at,
        )
        return prepared_training_dataset, latest_resolved_at

    def _build_feature_values(
            self,
            verdict: TradingShadowingVerdict,
            training_run_request: TradingCortexTrainingRunRequest,
            ordered_feature_names: list[str],
    ) -> list[float] | None:
        probe = verdict.probe
        if verdict.resolved_at is None:
            return None
        if probe is None or probe.shadowing_regime is None or probe.shadowing_metrics is None:
            return None

        shadowing_regime = probe.shadowing_regime
        regime_features = TradingCortexShadowingRegimeFeatureSnapshot.model_construct(
            metrics_meta_win_rate=shadowing_regime.metrics_meta_win_rate,
            metrics_meta_average_pnl=shadowing_regime.metrics_meta_average_pnl,
            metrics_meta_average_holding_time_hours=shadowing_regime.metrics_meta_average_holding_time_hours,
            metrics_meta_expected_pnl_velocity=shadowing_regime.metrics_meta_expected_pnl_velocity,
            metrics_meta_profit_factor=shadowing_regime.metrics_meta_profit_factor,
            metrics_meta_expected_value_usd=shadowing_regime.metrics_meta_expected_value_usd,
            edge_chronicle_profit_factor=shadowing_regime.edge_chronicle_profit_factor,
            edge_sparse_expected_value_usd=shadowing_regime.edge_sparse_expected_value_usd,
        )

        metric_features = []
        for metric_evaluation in probe.shadowing_metrics:
            if metric_evaluation.candidate_value is None:
                continue
            metric_features.append(
                TradingCortexShadowingMetricFeatureSnapshot.model_construct(
                    metric_key=metric_evaluation.metric_key,
                    candidate_value=metric_evaluation.candidate_value,
                    bucket_index=metric_evaluation.bucket_index,
                    bucket_win_rate=metric_evaluation.bucket_win_rate,
                    bucket_average_profit_and_loss_percentage=metric_evaluation.bucket_average_pnl,
                    bucket_average_holding_time_hours=metric_evaluation.bucket_average_holding_time,
                    bucket_expected_pnl_velocity=metric_evaluation.bucket_expected_pnl_velocity,
                    bucket_outlier_hit_rate=metric_evaluation.bucket_outlier_hit_rate,
                    bucket_sample_count=metric_evaluation.bucket_sample_count,
                    is_toxic=metric_evaluation.is_toxic,
                    is_golden=metric_evaluation.is_golden,
                    normalized_influence=metric_evaluation.normalized_influence,
                )
            )
        if not metric_features:
            return None

        scoring_request = TradingCortexScoringRequest.model_construct(
            request_identifier=str(probe.id),
            feature_set_version=training_run_request.feature_set_version,
            candidate_features=TradingCortexCandidateFeatureSnapshot.model_construct(
                token_symbol=probe.token_symbol,
                blockchain_network=probe.blockchain_network,
                dex_identifier=probe.dex_id,
                pair_address=probe.pair_address,
                quality_score=probe.quality_score,
                token_age_hours=probe.token_age_hours,
                liquidity_usd=probe.liquidity_usd,
                market_cap_usd=probe.market_cap_usd,
                fully_diluted_valuation_usd=probe.fully_diluted_valuation_usd,
                promotion_score=probe.promotion_score,
                volume_5m_usd=probe.volume_m5_usd,
                volume_1h_usd=probe.volume_h1_usd,
                volume_6h_usd=probe.volume_h6_usd,
                volume_24h_usd=probe.volume_h24_usd,
                price_change_percentage_5m=probe.price_change_percentage_m5,
                price_change_percentage_1h=probe.price_change_percentage_h1,
                price_change_percentage_6h=probe.price_change_percentage_h6,
                price_change_percentage_24h=probe.price_change_percentage_h24,
                transaction_count_5m=float(probe.transaction_count_m5),
                transaction_count_1h=float(probe.transaction_count_h1),
                transaction_count_6h=float(probe.transaction_count_h6),
                transaction_count_24h=float(probe.transaction_count_h24),
                buy_to_sell_ratio=probe.buy_to_sell_ratio,
                order_notional_value_usd=probe.order_notional_value_usd,
            ),
            regime_features=regime_features,
            metric_features=metric_features,
        )
        feature_vector_snapshot = self._feature_vector_builder.build_feature_vector(scoring_request)
        return feature_vector_snapshot.extract_ordered_feature_values(ordered_feature_names)
