from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_structures import TradingCortexGateThresholds
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.database_session_manager import get_database_session

logger = get_application_logger(__name__)


def build_absolute_gate_thresholds() -> TradingCortexGateThresholds:
    return TradingCortexGateThresholds(
        success_probability_threshold=settings.TRADING_CORTEX_SUCCESS_PROBABILITY_THRESHOLD,
        toxicity_probability_threshold=settings.TRADING_CORTEX_TOXICITY_PROBABILITY_THRESHOLD,
        fragility_probability_threshold=settings.TRADING_CORTEX_FRAGILITY_PROBABILITY_THRESHOLD,
        derived_from_quantiles=False,
        sample_count=0,
    )


def compute_quantile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        raise ValueError("Cannot compute a quantile from an empty distribution")

    clamped_quantile: float = max(0.0, min(1.0, quantile))
    highest_index: int = len(sorted_values) - 1
    if highest_index == 0:
        return sorted_values[0]

    exact_position: float = clamped_quantile * highest_index
    lower_index: int = int(exact_position)
    upper_index: int = min(lower_index + 1, highest_index)
    interpolation_weight: float = exact_position - lower_index
    return sorted_values[lower_index] + (sorted_values[upper_index] - sorted_values[lower_index]) * interpolation_weight


class TradingCortexQuantileGateService:
    def __init__(self) -> None:
        self._cached_thresholds: Optional[TradingCortexGateThresholds] = None
        self._cached_model_version: Optional[str] = None
        self._cached_at: Optional[datetime] = None

    def resolve_gate_thresholds(self, model_version: Optional[str]) -> TradingCortexGateThresholds:
        if not settings.TRADING_CORTEX_QUANTILE_GATE_ENABLED or model_version is None:
            return build_absolute_gate_thresholds()

        current_time: datetime = get_current_local_datetime()
        cached_thresholds: Optional[TradingCortexGateThresholds] = self._read_valid_cached_thresholds(
            model_version=model_version,
            current_time=current_time,
        )
        if cached_thresholds is not None:
            return cached_thresholds

        quantile_thresholds: Optional[TradingCortexGateThresholds] = self._compute_quantile_thresholds(
            model_version=model_version,
            current_time=current_time,
        )
        resolved_thresholds: TradingCortexGateThresholds = quantile_thresholds or build_absolute_gate_thresholds()

        self._cached_thresholds = resolved_thresholds
        self._cached_model_version = model_version
        self._cached_at = current_time
        return resolved_thresholds

    def invalidate(self) -> None:
        self._cached_thresholds = None
        self._cached_model_version = None
        self._cached_at = None

    def _read_valid_cached_thresholds(
            self,
            model_version: str,
            current_time: datetime,
    ) -> Optional[TradingCortexGateThresholds]:
        if self._cached_thresholds is None or self._cached_at is None:
            return None
        if self._cached_model_version != model_version:
            return None
        refresh_interval = timedelta(minutes=settings.TRADING_CORTEX_QUANTILE_GATE_REFRESH_MINUTES)
        if current_time - self._cached_at >= refresh_interval:
            return None
        return self._cached_thresholds

    def _compute_quantile_thresholds(
            self,
            model_version: str,
            current_time: datetime,
    ) -> Optional[TradingCortexGateThresholds]:
        lookback_start = current_time - timedelta(days=settings.TRADING_CORTEX_QUANTILE_GATE_LOOKBACK_DAYS)

        try:
            with get_database_session() as database_session:
                probe_dao = TradingShadowingProbeDao(database_session)
                inference_summaries = probe_dao.retrieve_cortex_inference_summaries_since(
                    since=lookback_start,
                    model_version=model_version,
                    limit_count=settings.TRADING_CORTEX_QUANTILE_GATE_MAX_SAMPLE_COUNT,
                )
        except Exception:
            logger.exception(
                "[TRADING][CORTEX][GATE][QUANTILE] Failed to read the score distribution for model_version=%s, falling back to absolute thresholds",
                model_version,
            )
            return None

        minimum_sample_count: int = settings.TRADING_CORTEX_QUANTILE_GATE_MIN_SAMPLE_COUNT
        if len(inference_summaries) < minimum_sample_count:
            logger.info(
                "[TRADING][CORTEX][GATE][QUANTILE] Only %d / %d required samples for model_version=%s over %.1f days, falling back to absolute thresholds",
                len(inference_summaries),
                minimum_sample_count,
                model_version,
                settings.TRADING_CORTEX_QUANTILE_GATE_LOOKBACK_DAYS,
            )
            return None

        success_probabilities: list[float] = sorted(
            inference_summary.success_probability for inference_summary in inference_summaries
        )
        toxicity_probabilities: list[float] = sorted(
            inference_summary.toxicity_probability for inference_summary in inference_summaries
        )
        fragility_probabilities: list[float] = sorted(
            inference_summary.fragility_probability for inference_summary in inference_summaries
        )

        success_probability_threshold: float = compute_quantile(
            success_probabilities,
            settings.TRADING_CORTEX_QUANTILE_GATE_SUCCESS_PROBABILITY_QUANTILE,
        )
        toxicity_probability_threshold: float = compute_quantile(
            toxicity_probabilities,
            settings.TRADING_CORTEX_QUANTILE_GATE_TOXICITY_PROBABILITY_QUANTILE,
        )
        fragility_probability_threshold: float = compute_quantile(
            fragility_probabilities,
            settings.TRADING_CORTEX_QUANTILE_GATE_FRAGILITY_PROBABILITY_QUANTILE,
        )

        logger.info(
            "[TRADING][CORTEX][GATE][QUANTILE] Derived thresholds from %d samples over %.1f days for model_version=%s "
            "— win>=%.3f (q%.2f), tox<=%.3f (q%.2f), frag<=%.3f (q%.2f)",
            len(inference_summaries),
            settings.TRADING_CORTEX_QUANTILE_GATE_LOOKBACK_DAYS,
            model_version,
            success_probability_threshold,
            settings.TRADING_CORTEX_QUANTILE_GATE_SUCCESS_PROBABILITY_QUANTILE,
            toxicity_probability_threshold,
            settings.TRADING_CORTEX_QUANTILE_GATE_TOXICITY_PROBABILITY_QUANTILE,
            fragility_probability_threshold,
            settings.TRADING_CORTEX_QUANTILE_GATE_FRAGILITY_PROBABILITY_QUANTILE,
        )

        return TradingCortexGateThresholds(
            success_probability_threshold=success_probability_threshold,
            toxicity_probability_threshold=toxicity_probability_threshold,
            fragility_probability_threshold=fragility_probability_threshold,
            derived_from_quantiles=True,
            sample_count=len(inference_summaries),
        )


trading_cortex_quantile_gate_service = TradingCortexQuantileGateService()
