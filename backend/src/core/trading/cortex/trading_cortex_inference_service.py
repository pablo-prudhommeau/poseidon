from __future__ import annotations

from src.core.trading.cortex.trading_cortex_feature_vector_builder import TradingCortexFeatureVectorBuilder
from src.core.trading.cortex.trading_cortex_final_score_service import TradingCortexFinalScoreService
from src.core.trading.cortex.trading_cortex_model_registry_service import TradingCortexModelRegistryService
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexPrediction,
    TradingCortexScoringBatchRequest,
    TradingCortexScoringBatchResponse,
    TradingCortexScoringRequest,
    TradingCortexScoringResponse,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingCortexInferenceService:
    def __init__(
            self,
            model_registry_service: TradingCortexModelRegistryService,
            feature_vector_builder: TradingCortexFeatureVectorBuilder,
            final_score_service: TradingCortexFinalScoreService,
    ) -> None:
        self._model_registry_service = model_registry_service
        self._feature_vector_builder = feature_vector_builder
        self._final_score_service = final_score_service

    def score_trade(self, scoring_request: TradingCortexScoringRequest) -> TradingCortexScoringResponse:
        feature_vector_snapshot = self._feature_vector_builder.build_feature_vector(scoring_request)

        if not self._model_registry_service.model_ready:
            return TradingCortexScoringResponse(
                request_identifier=scoring_request.request_identifier,
                token_symbol=scoring_request.candidate_features.token_symbol,
                feature_set_version=scoring_request.feature_set_version,
                model_version=None,
                model_ready=False,
                success_probability=None,
                toxicity_probability=None,
                expected_profit_and_loss_percentage=None,
                final_trade_score=None,
                score_breakdown=None,
                feature_count=len(feature_vector_snapshot.named_feature_values),
                golden_metric_count=feature_vector_snapshot.golden_metric_count,
                toxic_metric_count=feature_vector_snapshot.toxic_metric_count,
                used_model_names=[],
            )

        model_feature_set_version = self._model_registry_service.feature_set_version
        if model_feature_set_version != scoring_request.feature_set_version:
            logger.warning(
                "[TRADING][CORTEX][INFERENCE] Feature set mismatch request=%s model=%s for %s",
                scoring_request.feature_set_version,
                model_feature_set_version,
                scoring_request.candidate_features.token_symbol,
            )
            
        model_prediction = self._model_registry_service.predict(feature_vector_snapshot)
        
        final_score_breakdown = self._final_score_service.calculate_final_score(
            model_prediction,
            feature_vector_snapshot,
        )

        logger.info(
            "[TRADING][CORTEX][INFERENCE] Scored %s final_score=%.2f success=%.3f toxicity=%.3f expected_pnl=%.2f",
            scoring_request.candidate_features.token_symbol,
            final_score_breakdown.final_trade_score,
            model_prediction.success_probability,
            model_prediction.toxicity_probability,
            model_prediction.expected_profit_and_loss_percentage,
        )

        return TradingCortexScoringResponse(
            request_identifier=scoring_request.request_identifier,
            token_symbol=scoring_request.candidate_features.token_symbol,
            feature_set_version=scoring_request.feature_set_version,
            model_version=self._model_registry_service.model_version,
            model_ready=True,
            success_probability=model_prediction.success_probability,
            toxicity_probability=model_prediction.toxicity_probability,
            expected_profit_and_loss_percentage=model_prediction.expected_profit_and_loss_percentage,
            final_trade_score=final_score_breakdown.final_trade_score,
            score_breakdown=final_score_breakdown,
            feature_count=len(feature_vector_snapshot.named_feature_values),
            golden_metric_count=feature_vector_snapshot.golden_metric_count,
            toxic_metric_count=feature_vector_snapshot.toxic_metric_count,
            used_model_names=model_prediction.used_model_names,
        )

    def score_trade_batch(self, scoring_batch_request: TradingCortexScoringBatchRequest) -> TradingCortexScoringBatchResponse:
        return TradingCortexScoringBatchResponse(
            responses=[self.score_trade(scoring_request) for scoring_request in scoring_batch_request.requests]
        )
