from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy

from src.core.trading.cortex.trading_cortex_numerical_utils import clamp
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexFeatureVectorSnapshot,
    TradingCortexHealthResponse,
    TradingCortexPartialPrediction,
)
from src.logging.logger import get_application_logger
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingCortexModelManifest

logger = get_application_logger(__name__)


class TradingCortexModelRegistryService:
    def __init__(self) -> None:
        self._model_version: Optional[str] = None
        self._feature_set_version: Optional[str] = None
        self._ordered_feature_names: list[str] = []
        self._success_probability_booster: Optional[object] = None
        self._toxicity_probability_booster: Optional[object] = None
        self._expected_profit_and_loss_percentage_booster: Optional[object] = None

    def reload_models(self) -> None:
        try:
            with get_database_session() as session:
                from sqlalchemy import select
                statement = (
                    select(TradingCortexModelManifest)
                    .where(TradingCortexModelManifest.is_active == True)
                    .order_by(TradingCortexModelManifest.created_at.desc())
                    .limit(1)
                )
                active_manifest = session.execute(statement).scalar_one_or_none()

                if active_manifest is None:
                    logger.info("[TRADING][CORTEX][MODEL] No active model manifest found in database, bootstrap scoring remains active")
                    self._clear_loaded_models()
                    return

                model_version = active_manifest.model_version
                feature_set_version = active_manifest.feature_set_version
                ordered_feature_names = list(active_manifest.ordered_feature_names)
                success_probability_model_path = active_manifest.success_probability_model_path
                toxicity_probability_model_path = active_manifest.toxicity_probability_model_path
                expected_profit_and_loss_model_path = active_manifest.expected_profit_and_loss_model_path

            self._model_version = model_version
            self._feature_set_version = feature_set_version
            self._ordered_feature_names = ordered_feature_names
            self._success_probability_booster = self._load_booster(success_probability_model_path)
            self._toxicity_probability_booster = self._load_booster(toxicity_probability_model_path)
            self._expected_profit_and_loss_percentage_booster = self._load_booster(
                expected_profit_and_loss_model_path
            )
            logger.info(
                "[TRADING][CORTEX][MODEL] Loaded model bundle version=%s feature_set=%s models=%s",
                model_version,
                feature_set_version,
                ", ".join(self.loaded_model_names),
            )
        except Exception:
            logger.exception("[TRADING][CORTEX][MODEL] Failed to load model manifest from database")
            self._clear_loaded_models()

    def predict(self, feature_vector_snapshot: TradingCortexFeatureVectorSnapshot) -> Optional[TradingCortexPartialPrediction]:
        if self._model_version is None:
            return None

        ordered_feature_values = feature_vector_snapshot.extract_ordered_feature_values(
            self._ordered_feature_names
        )
        feature_matrix = numpy.asarray([ordered_feature_values], dtype=numpy.float32)

        partial_prediction = TradingCortexPartialPrediction()
        success_probability_prediction = self._predict_optional_probability(self._success_probability_booster, feature_matrix)
        toxicity_probability_prediction = self._predict_optional_probability(self._toxicity_probability_booster, feature_matrix)
        expected_profit_and_loss_prediction = self._predict_optional_regression(
            self._expected_profit_and_loss_percentage_booster,
            feature_matrix,
        )

        if success_probability_prediction is not None:
            partial_prediction.success_probability = success_probability_prediction
            partial_prediction.used_model_names.append("success_probability")
        if toxicity_probability_prediction is not None:
            partial_prediction.toxicity_probability = toxicity_probability_prediction
            partial_prediction.used_model_names.append("toxicity_probability")
        if expected_profit_and_loss_prediction is not None:
            partial_prediction.expected_profit_and_loss_percentage = expected_profit_and_loss_prediction
            partial_prediction.used_model_names.append("expected_profit_and_loss_percentage")

        if not partial_prediction.used_model_names:
            return None

        return partial_prediction

    @property
    def model_ready(self) -> bool:
        return self._model_version is not None and bool(self.loaded_model_names)

    @property
    def model_version(self) -> Optional[str]:
        return self._model_version

    @property
    def feature_set_version(self) -> Optional[str]:
        return self._feature_set_version

    @property
    def loaded_model_names(self) -> list[str]:
        loaded_model_names: list[str] = []
        if self._success_probability_booster is not None:
            loaded_model_names.append("success_probability")
        if self._toxicity_probability_booster is not None:
            loaded_model_names.append("toxicity_probability")
        if self._expected_profit_and_loss_percentage_booster is not None:
            loaded_model_names.append("expected_profit_and_loss_percentage")
        return loaded_model_names

    def build_health_response(self) -> TradingCortexHealthResponse:
        return TradingCortexHealthResponse(
            ok=True,
            model_ready=self.model_ready,
            model_version=self.model_version,
            feature_set_version=self.feature_set_version,
            loaded_model_names=self.loaded_model_names,
        )

    def _load_booster(
            self,
            model_path_string: str,
    ) -> Optional[object]:
        model_path = Path(model_path_string)
        if not model_path.exists():
            logger.warning("[TRADING][CORTEX][MODEL] Model artifact %s is missing", model_path)
            return None

        import xgboost

        booster = xgboost.Booster()
        booster.load_model(str(model_path))
        logger.info("[TRADING][CORTEX][MODEL] Loaded artifact from %s", model_path)
        return booster

    def _predict_optional_probability(
            self,
            booster: Optional[object],
            feature_matrix: numpy.ndarray,
    ) -> Optional[float]:
        prediction = self._predict_optional_value(booster, feature_matrix)
        if prediction is None:
            return None
        return clamp(prediction, 0.0, 1.0)

    def _predict_optional_regression(
            self,
            booster: Optional[object],
            feature_matrix: numpy.ndarray,
    ) -> Optional[float]:
        return self._predict_optional_value(booster, feature_matrix)

    def _predict_optional_value(
            self,
            booster: Optional[object],
            feature_matrix: numpy.ndarray,
    ) -> Optional[float]:
        if booster is None:
            return None
        prediction_values = booster.inplace_predict(feature_matrix)
        if len(prediction_values) == 0:
            return None
        return float(prediction_values[0])

    def _clear_loaded_models(self) -> None:
        self._model_version = None
        self._feature_set_version = None
        self._ordered_feature_names = []
        self._success_probability_booster = None
        self._toxicity_probability_booster = None
        self._expected_profit_and_loss_percentage_booster = None
