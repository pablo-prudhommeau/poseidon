from __future__ import annotations

import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_feature_vector_builder import TradingCortexFeatureVectorBuilder
from src.core.trading.cortex.trading_cortex_inference_provider import get_trading_cortex_inference_service
from src.core.trading.cortex.training.trading_cortex_training_dataset_service import TradingCortexTrainingDatasetService
from src.core.trading.cortex.training.trading_cortex_training_service import TradingCortexTrainingService
from src.core.trading.cortex.training.trading_cortex_training_structures import (
    TradingCortexInsufficientTrainingDataError,
    TradingCortexTrainingRunRequest,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingCortexTrainingJob:
    def __init__(self) -> None:
        self._thread_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trading_cortex_training")
        self._training_interval_seconds = 86400

    async def run_loop(self) -> None:
        while True:
            try:
                await self._run_training_async()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[TRADING][CORTEX][TRAINING_JOB] Unexpected failure in training loop: %s", exc)

            logger.info("[TRADING][CORTEX][TRAINING_JOB] Sleeping for %d seconds before next training iteration", self._training_interval_seconds)
            await asyncio.sleep(self._training_interval_seconds)

    async def _run_training_async(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            logger.info("[TRADING][CORTEX][TRAINING_JOB] Dispatching training task to background thread pool")
            await loop.run_in_executor(self._thread_pool, self._execute_training_sync)
        except TradingCortexInsufficientTrainingDataError as exc:
            logger.warning(
                "[TRADING][CORTEX][TRAINING_JOB] Training skipped: %s. Background data collection is continuing.",
                exc,
            )
        except Exception as exc:
            logger.error("[TRADING][CORTEX][TRAINING_JOB] Training task failed in thread pool: %s\n%s", exc, traceback.format_exc())

    def _execute_training_sync(self) -> None:
        logger.info("[TRADING][CORTEX][TRAINING_JOB] Starting training execution...")
        training_run_request = TradingCortexTrainingRunRequest(
            feature_set_version=settings.TRADING_CORTEX_FEATURE_SET_VERSION,
            model_output_directory=settings.TRADING_CORTEX_MODEL_OUTPUT_DIRECTORY,
            validation_fraction=settings.TRADING_CORTEX_TRAINING_VALIDATION_FRACTION,
            minimum_labeled_record_count=settings.TRADING_CORTEX_TRAINING_MINIMUM_LABELED_RECORD_COUNT,
            preferred_training_device=settings.TRADING_CORTEX_XGBOOST_TRAINING_DEVICE,
        )
        feature_vector_builder = TradingCortexFeatureVectorBuilder()
        training_dataset_service = TradingCortexTrainingDatasetService(feature_vector_builder=feature_vector_builder)
        training_service = TradingCortexTrainingService(training_dataset_service=training_dataset_service)

        trained_model_artifacts = training_service.run_training(training_run_request)

        logger.info(
            "[TRADING][CORTEX][TRAINING_JOB] Artifacts ready success_model=%s toxicity_model=%s expected_pnl_model=%s",
            trained_model_artifacts.success_probability_model_path,
            trained_model_artifacts.toxicity_probability_model_path,
            trained_model_artifacts.expected_profit_and_loss_percentage_model_path,
        )

        try:
            inference_service = get_trading_cortex_inference_service()
            inference_service._model_registry_service.reload_models()
            logger.info("\033[92m[TRADING][CORTEX][TRAINING_JOB] Model registry reloaded successfully with new trained model\033[0m")
        except Exception as exc:
            logger.error("[TRADING][CORTEX][TRAINING_JOB] Failed to reload model registry after training: %s", exc)
