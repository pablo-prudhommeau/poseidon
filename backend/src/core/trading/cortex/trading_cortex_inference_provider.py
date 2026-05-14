from __future__ import annotations

from typing import Optional

from src.core.trading.cortex.trading_cortex_feature_vector_builder import TradingCortexFeatureVectorBuilder
from src.core.trading.cortex.trading_cortex_final_score_service import TradingCortexFinalScoreService
from src.core.trading.cortex.trading_cortex_inference_service import TradingCortexInferenceService
from src.core.trading.cortex.trading_cortex_model_registry_service import TradingCortexModelRegistryService
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_trading_cortex_model_registry_service: Optional[TradingCortexModelRegistryService] = None
_trading_cortex_inference_service: Optional[TradingCortexInferenceService] = None


def get_trading_cortex_inference_service() -> TradingCortexInferenceService:
    global _trading_cortex_model_registry_service, _trading_cortex_inference_service
    if _trading_cortex_inference_service is None:
        _trading_cortex_model_registry_service = TradingCortexModelRegistryService()
        _trading_cortex_model_registry_service.reload_models()
        _trading_cortex_inference_service = TradingCortexInferenceService(
            model_registry_service=_trading_cortex_model_registry_service,
            feature_vector_builder=TradingCortexFeatureVectorBuilder(),
            final_score_service=TradingCortexFinalScoreService(),
        )
        logger.info("[TRADING][CORTEX][PROVIDER] Inference service initialized")
    return _trading_cortex_inference_service
