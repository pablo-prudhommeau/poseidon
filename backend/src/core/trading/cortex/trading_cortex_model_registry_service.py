from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.trading.cortex.trading_cortex_numerical_utils import clamp
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexBatchPrediction,
    TradingCortexFeatureVectorSnapshot,
    TradingCortexHealthResponse,
    TradingCortexPrediction,
)
from src.logging.logger import get_application_logger
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingCortexModelManifest, TradingCortexModelRole

logger = get_application_logger(__name__)

_REQUIRED_MODEL_NAMES = [
    "success_probability",
    "toxicity_probability",
    "expected_profit_and_loss_percentage",
    "predicted_holding_time_minutes",
    "fragility_probability",
]


def load_booster_from_path(model_path_string: str) -> Optional[object]:
    if not model_path_string.strip():
        return None
    model_path = Path(model_path_string)
    if not model_path.exists():
        logger.warning("[TRADING][CORTEX][MODEL] Model artifact %s is missing", model_path)
        return None

    import xgboost

    booster = xgboost.Booster()
    booster.load_model(str(model_path))
    logger.info("[TRADING][CORTEX][MODEL] Loaded artifact from %s", model_path)
    return booster


class TradingCortexModelBundle:
    def __init__(
            self,
            model_version: str,
            feature_set_version: str,
            ordered_feature_names: list[str],
            success_probability_booster: Optional[object],
            toxicity_probability_booster: Optional[object],
            expected_profit_and_loss_percentage_booster: Optional[object],
            predicted_holding_time_minutes_booster: Optional[object],
            fragility_probability_booster: Optional[object],
    ) -> None:
        self.model_version = model_version
        self.feature_set_version = feature_set_version
        self.ordered_feature_names = ordered_feature_names
        self._success_probability_booster = success_probability_booster
        self._toxicity_probability_booster = toxicity_probability_booster
        self._expected_profit_and_loss_percentage_booster = expected_profit_and_loss_percentage_booster
        self._predicted_holding_time_minutes_booster = predicted_holding_time_minutes_booster
        self._fragility_probability_booster = fragility_probability_booster

    @property
    def loaded_model_names(self) -> list[str]:
        loaded_model_names: list[str] = []
        if self._success_probability_booster is not None:
            loaded_model_names.append("success_probability")
        if self._toxicity_probability_booster is not None:
            loaded_model_names.append("toxicity_probability")
        if self._expected_profit_and_loss_percentage_booster is not None:
            loaded_model_names.append("expected_profit_and_loss_percentage")
        if self._predicted_holding_time_minutes_booster is not None:
            loaded_model_names.append("predicted_holding_time_minutes")
        if self._fragility_probability_booster is not None:
            loaded_model_names.append("fragility_probability")
        return loaded_model_names

    @property
    def is_complete(self) -> bool:
        loaded_model_names = self.loaded_model_names
        return all(required_model_name in loaded_model_names for required_model_name in _REQUIRED_MODEL_NAMES)

    def predict(self, feature_vector_snapshot: TradingCortexFeatureVectorSnapshot) -> TradingCortexPrediction:
        if not self.is_complete:
            raise RuntimeError("[TRADING][CORTEX][MODEL] Complete model bundle is not loaded")

        ordered_feature_values = feature_vector_snapshot.extract_ordered_feature_values(self.ordered_feature_names)
        feature_matrix = numpy.asarray([ordered_feature_values], dtype=numpy.float32)

        success_probability_prediction = self._predict_optional_probability(self._success_probability_booster, feature_matrix)
        toxicity_probability_prediction = self._predict_optional_probability(self._toxicity_probability_booster, feature_matrix)
        expected_profit_and_loss_prediction = self._predict_optional_regression(
            self._expected_profit_and_loss_percentage_booster,
            feature_matrix,
        )
        predicted_holding_time_minutes_prediction = self._predict_optional_regression(
            self._predicted_holding_time_minutes_booster,
            feature_matrix,
        )
        fragility_probability_prediction = self._predict_optional_probability(
            self._fragility_probability_booster,
            feature_matrix,
        )

        if (
                success_probability_prediction is None
                or toxicity_probability_prediction is None
                or expected_profit_and_loss_prediction is None
                or predicted_holding_time_minutes_prediction is None
                or fragility_probability_prediction is None
        ):
            raise RuntimeError("[TRADING][CORTEX][MODEL] Complete model bundle failed to produce all predictions")

        return TradingCortexPrediction(
            success_probability=success_probability_prediction,
            toxicity_probability=toxicity_probability_prediction,
            expected_profit_and_loss_percentage=expected_profit_and_loss_prediction,
            predicted_holding_time_minutes=predicted_holding_time_minutes_prediction,
            fragility_probability=fragility_probability_prediction,
            used_model_names=self.loaded_model_names,
        )

    def predict_batch(self, feature_matrix: numpy.ndarray) -> TradingCortexBatchPrediction:
        if not self.is_complete:
            raise RuntimeError("[TRADING][CORTEX][MODEL] Complete model bundle is not loaded")

        return TradingCortexBatchPrediction(
            success_probabilities=numpy.clip(self._success_probability_booster.inplace_predict(feature_matrix), 0.0, 1.0),
            toxicity_probabilities=numpy.clip(self._toxicity_probability_booster.inplace_predict(feature_matrix), 0.0, 1.0),
            expected_profit_and_loss_percentages=self._expected_profit_and_loss_percentage_booster.inplace_predict(feature_matrix),
            predicted_holding_time_minutes=self._predicted_holding_time_minutes_booster.inplace_predict(feature_matrix),
            fragility_probabilities=numpy.clip(self._fragility_probability_booster.inplace_predict(feature_matrix), 0.0, 1.0),
        )

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


def build_model_bundle_from_manifest(manifest: TradingCortexModelManifest) -> TradingCortexModelBundle:
    return TradingCortexModelBundle(
        model_version=manifest.model_version,
        feature_set_version=manifest.feature_set_version,
        ordered_feature_names=list(manifest.ordered_feature_names),
        success_probability_booster=load_booster_from_path(manifest.success_probability_model_path),
        toxicity_probability_booster=load_booster_from_path(manifest.toxicity_probability_model_path),
        expected_profit_and_loss_percentage_booster=load_booster_from_path(manifest.expected_profit_and_loss_model_path),
        predicted_holding_time_minutes_booster=load_booster_from_path(manifest.predicted_holding_time_minutes_model_path),
        fragility_probability_booster=load_booster_from_path(manifest.fragility_probability_model_path),
    )


class TradingCortexModelRegistryService:
    def __init__(self) -> None:
        self._champion_bundle: Optional[TradingCortexModelBundle] = None
        self._challenger_bundle: Optional[TradingCortexModelBundle] = None

    def reload_models(self) -> None:
        try:
            with get_database_session() as session:
                champion_manifest: Optional[TradingCortexModelManifest] = self._retrieve_manifest_for_role(
                    session,
                    TradingCortexModelRole.CHAMPION,
                )
                challenger_manifest: Optional[TradingCortexModelManifest] = self._retrieve_manifest_for_role(
                    session,
                    TradingCortexModelRole.CHALLENGER,
                )

                if champion_manifest is None:
                    logger.info(
                        "[TRADING][CORTEX][MODEL] No champion model manifest found in database, bootstrap scoring remains active"
                    )
                    self._clear_loaded_models()
                    return

                champion_bundle: TradingCortexModelBundle = build_model_bundle_from_manifest(champion_manifest)
                challenger_bundle: Optional[TradingCortexModelBundle] = (
                    build_model_bundle_from_manifest(challenger_manifest) if challenger_manifest is not None else None
                )

            self._champion_bundle = champion_bundle
            self._challenger_bundle = challenger_bundle

            if not champion_bundle.is_complete:
                logger.warning(
                    "[TRADING][CORTEX][MODEL] Champion bundle version=%s is incomplete (loaded=%s), bootstrap scoring remains active",
                    champion_bundle.model_version,
                    ", ".join(champion_bundle.loaded_model_names),
                )
                self._clear_loaded_models()
                return

            logger.info(
                "[TRADING][CORTEX][MODEL] Loaded champion bundle version=%s feature_set=%s models=%s (challenger=%s)",
                champion_bundle.model_version,
                champion_bundle.feature_set_version,
                ", ".join(champion_bundle.loaded_model_names),
                challenger_bundle.model_version if challenger_bundle is not None else "none",
            )
        except Exception:
            logger.exception("[TRADING][CORTEX][MODEL] Failed to load model manifest from database")
            self._clear_loaded_models()

    def predict(self, feature_vector_snapshot: TradingCortexFeatureVectorSnapshot) -> TradingCortexPrediction:
        if self._champion_bundle is None:
            raise RuntimeError("[TRADING][CORTEX][MODEL] Complete model bundle is not loaded")
        return self._champion_bundle.predict(feature_vector_snapshot)

    @property
    def champion_bundle(self) -> Optional[TradingCortexModelBundle]:
        return self._champion_bundle

    @property
    def challenger_bundle(self) -> Optional[TradingCortexModelBundle]:
        return self._challenger_bundle

    @property
    def model_ready(self) -> bool:
        return self._champion_bundle is not None and self._champion_bundle.is_complete

    @property
    def model_version(self) -> Optional[str]:
        if self._champion_bundle is None:
            return None
        return self._champion_bundle.model_version

    @property
    def feature_set_version(self) -> Optional[str]:
        if self._champion_bundle is None:
            return None
        return self._champion_bundle.feature_set_version

    @property
    def loaded_model_names(self) -> list[str]:
        if self._champion_bundle is None:
            return []
        return self._champion_bundle.loaded_model_names

    def build_health_response(self) -> TradingCortexHealthResponse:
        return TradingCortexHealthResponse(
            ok=True,
            model_ready=self.model_ready,
            model_version=self.model_version,
            feature_set_version=self.feature_set_version,
            loaded_model_names=self.loaded_model_names,
        )

    def _retrieve_manifest_for_role(
            self,
            session: Session,
            model_role: TradingCortexModelRole,
    ) -> Optional[TradingCortexModelManifest]:
        statement = (
            select(TradingCortexModelManifest)
            .where(TradingCortexModelManifest.model_role == model_role)
            .order_by(TradingCortexModelManifest.created_at.desc())
            .limit(1)
        )
        return session.execute(statement).scalar_one_or_none()

    def _clear_loaded_models(self) -> None:
        self._champion_bundle = None
        self._challenger_bundle = None
