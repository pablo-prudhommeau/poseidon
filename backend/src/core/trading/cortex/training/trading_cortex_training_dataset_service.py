from __future__ import annotations

from datetime import datetime

import numpy

from src.core.trading.cortex.trading_cortex_feature_vector_builder import TradingCortexFeatureVectorBuilder
from src.core.trading.cortex.trading_cortex_structures import TradingCortexCandidateFeatureSnapshot, TradingCortexScoringRequest
from src.core.trading.cortex.training.trading_cortex_training_structures import (
    TradingCortexInsufficientTrainingDataError,
    TradingCortexPreparedTrainingDataset,
    TradingCortexShadowTrainingRecord,
    TradingCortexTrainingRunRequest,
)
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session

logger = get_application_logger(__name__)


class TradingCortexTrainingDatasetService:
    def __init__(self, feature_vector_builder: TradingCortexFeatureVectorBuilder) -> None:
        self._feature_vector_builder = feature_vector_builder

    def build_training_dataset(
            self,
            training_run_request: TradingCortexTrainingRunRequest,
            ordered_feature_names: list[str],
    ) -> tuple[TradingCortexPreparedTrainingDataset, datetime]:
        shadow_training_records = self._load_shadow_training_records()
        labeled_record_count = len(shadow_training_records)
        if labeled_record_count < training_run_request.minimum_labeled_record_count:
            raise TradingCortexInsufficientTrainingDataError(
                required_count=training_run_request.minimum_labeled_record_count,
                found_count=labeled_record_count,
            )

        feature_matrix_rows: list[list[float]] = []
        success_labels: list[float] = []
        toxicity_labels: list[float] = []
        expected_profit_and_loss_percentages: list[float] = []

        dataset_window_start_at = shadow_training_records[0].resolved_at
        dataset_window_end_at = shadow_training_records[-1].resolved_at
        latest_resolved_at = dataset_window_end_at

        for shadow_training_record in shadow_training_records:
            scoring_request = TradingCortexScoringRequest(
                request_identifier=str(shadow_training_record.probe_identifier),
                feature_set_version=training_run_request.feature_set_version,
                candidate_features=shadow_training_record.candidate_features,
            )
            feature_vector_snapshot = self._feature_vector_builder.build_feature_vector(scoring_request)
            feature_matrix_rows.append(feature_vector_snapshot.extract_ordered_feature_values(ordered_feature_names))
            success_labels.append(1.0 if shadow_training_record.is_profitable else 0.0)
            toxicity_labels.append(1.0 if shadow_training_record.exit_reason == "STOP_LOSS" else 0.0)
            expected_profit_and_loss_percentages.append(shadow_training_record.realized_profit_and_loss_percentage)

        feature_matrix = numpy.asarray(feature_matrix_rows, dtype=numpy.float32)
        success_label_array = numpy.asarray(success_labels, dtype=numpy.float32)
        toxicity_label_array = numpy.asarray(toxicity_labels, dtype=numpy.float32)
        expected_profit_and_loss_percentage_array = numpy.asarray(expected_profit_and_loss_percentages, dtype=numpy.float32)

        validation_record_count = max(1, int(labeled_record_count * training_run_request.validation_fraction))
        training_record_count = labeled_record_count - validation_record_count
        if training_record_count <= 0:
            raise ValueError("Validation fraction leaves no records for training")

        logger.info(
            "[TRADING][CORTEX][TRAINING][DATASET] Prepared %d labeled records with %d selected features",
            labeled_record_count,
            len(ordered_feature_names),
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
            training_record_count=training_record_count,
            validation_record_count=validation_record_count,
            dataset_window_start_at=dataset_window_start_at,
            dataset_window_end_at=dataset_window_end_at,
        )
        return prepared_training_dataset, latest_resolved_at

    def _load_shadow_training_records(self) -> list[TradingCortexShadowTrainingRecord]:
        shadow_training_records: list[TradingCortexShadowTrainingRecord] = []

        with get_database_session() as database_session:
            verdict_dao = TradingShadowingVerdictDao(database_session)
            resolved_verdicts = verdict_dao.retrieve_resolved_for_cortex_training()

            for verdict in resolved_verdicts:
                probe = verdict.probe
                resolved_at = verdict.resolved_at
                if resolved_at is None:
                    continue

                shadow_training_records.append(
                    TradingCortexShadowTrainingRecord(
                        probe_identifier=probe.id,
                        resolved_at=resolved_at,
                        candidate_features=TradingCortexCandidateFeatureSnapshot(
                            token_symbol=probe.token_symbol,
                            blockchain_network=probe.blockchain_network,
                            dex_identifier=probe.dex_id,
                            pair_address=probe.pair_address,
                            candidate_rank=probe.candidate_rank,
                            quality_score=probe.quality_score,
                            token_age_hours=probe.token_age_hours,
                            liquidity_usd=probe.liquidity_usd,
                            market_cap_usd=probe.market_cap_usd,
                            fully_diluted_valuation_usd=probe.fully_diluted_valuation_usd,
                            dexscreener_boost=probe.dexscreener_boost,
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
                        realized_profit_and_loss_percentage=float(verdict.realized_pnl_percentage),
                        realized_profit_and_loss_usd=float(verdict.realized_pnl_usd),
                        holding_duration_minutes=float(verdict.holding_duration_minutes),
                        is_profitable=bool(verdict.is_profitable),
                        exit_reason=str(verdict.exit_reason),
                    )
                )

        logger.info(
            "[TRADING][CORTEX][TRAINING][DATASET] Loaded %d shadowing rows from database",
            len(shadow_training_records),
        )
        return shadow_training_records
