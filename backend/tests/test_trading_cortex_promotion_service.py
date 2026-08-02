from __future__ import annotations

import numpy

from src.configuration.config import settings
from src.core.trading.cortex.promotion.trading_cortex_promotion_service import TradingCortexPromotionService
from src.core.trading.cortex.promotion.trading_cortex_promotion_structures import TradingCortexForwardSelectionMetrics
from src.core.trading.cortex.trading_cortex_model_registry_service import TradingCortexModelBundle


class _ConstantBooster:
    def __init__(self, constant_value: float) -> None:
        self._constant_value = constant_value

    def inplace_predict(self, feature_matrix: numpy.ndarray) -> numpy.ndarray:
        return numpy.full(feature_matrix.shape[0], self._constant_value, dtype=numpy.float32)


class _FirstFeatureBooster:
    def __init__(self, scale: float, offset: float) -> None:
        self._scale = scale
        self._offset = offset

    def inplace_predict(self, feature_matrix: numpy.ndarray) -> numpy.ndarray:
        return (feature_matrix[:, 0] * self._scale + self._offset).astype(numpy.float32)


def _build_bundle(
        model_version: str,
        success_probability_booster: object,
        fragility_probability_booster: object | None = None,
) -> TradingCortexModelBundle:
    return TradingCortexModelBundle(
        model_version=model_version,
        feature_set_version="cortex_v2",
        ordered_feature_names=["feature_one"],
        success_probability_booster=success_probability_booster,
        toxicity_probability_booster=_ConstantBooster(0.1),
        expected_profit_and_loss_percentage_booster=_ConstantBooster(1.0),
        predicted_holding_time_minutes_booster=_ConstantBooster(240.0),
        fragility_probability_booster=(
            fragility_probability_booster if fragility_probability_booster is not None else _ConstantBooster(0.05)
        ),
    )


def _build_metrics(
        model_version: str,
        selected_record_count: int,
        selected_average_profit_and_loss_percentage: float,
        selected_fragility_rate: float,
) -> TradingCortexForwardSelectionMetrics:
    return TradingCortexForwardSelectionMetrics(
        model_version=model_version,
        evaluated_record_count=1000,
        selected_record_count=selected_record_count,
        selected_average_profit_and_loss_percentage=selected_average_profit_and_loss_percentage,
        selected_win_rate=0.5,
        selected_fragility_rate=selected_fragility_rate,
        success_probability_threshold=0.6,
        toxicity_probability_threshold=0.3,
    )


def _build_promotion_service() -> TradingCortexPromotionService:
    return TradingCortexPromotionService(training_dataset_service=None)


def test_promotion_accepts_challenger_with_sufficient_uplift() -> None:
    promotion_service = _build_promotion_service()

    rejection_reason = promotion_service._resolve_rejection_reason(
        champion_metrics=_build_metrics("champion_v1", 200, 2.0, 0.10),
        challenger_metrics=_build_metrics("challenger_v1", 180, 6.0, 0.09),
        average_profit_and_loss_uplift_percentage=4.0,
        fragility_rate_increase=-0.01,
    )

    assert rejection_reason is None


def test_promotion_rejects_challenger_with_insufficient_uplift() -> None:
    promotion_service = _build_promotion_service()

    rejection_reason = promotion_service._resolve_rejection_reason(
        champion_metrics=_build_metrics("champion_v1", 200, 2.0, 0.10),
        challenger_metrics=_build_metrics("challenger_v1", 180, 2.4, 0.10),
        average_profit_and_loss_uplift_percentage=0.4,
        fragility_rate_increase=0.0,
    )

    assert rejection_reason is not None
    assert "uplift" in rejection_reason


def test_promotion_rejects_challenger_that_increases_fragility() -> None:
    promotion_service = _build_promotion_service()

    rejection_reason = promotion_service._resolve_rejection_reason(
        champion_metrics=_build_metrics("champion_v1", 200, 2.0, 0.10),
        challenger_metrics=_build_metrics("challenger_v1", 180, 9.0, 0.20),
        average_profit_and_loss_uplift_percentage=7.0,
        fragility_rate_increase=0.10,
    )

    assert rejection_reason is not None
    assert "fragility" in rejection_reason


def test_promotion_rejects_challenger_with_too_few_selected_verdicts() -> None:
    promotion_service = _build_promotion_service()
    too_few_selected_count: int = settings.TRADING_CORTEX_PROMOTION_MIN_SELECTED_VERDICT_COUNT - 1

    rejection_reason = promotion_service._resolve_rejection_reason(
        champion_metrics=_build_metrics("champion_v1", 200, 2.0, 0.10),
        challenger_metrics=_build_metrics("challenger_v1", too_few_selected_count, 9.0, 0.05),
        average_profit_and_loss_uplift_percentage=7.0,
        fragility_rate_increase=-0.05,
    )

    assert rejection_reason is not None
    assert "challenger selected only" in rejection_reason


def test_forward_selection_metrics_isolate_the_top_quantile_of_scores() -> None:
    promotion_service = _build_promotion_service()
    record_count: int = 100
    feature_matrix = numpy.arange(record_count, dtype=numpy.float32).reshape(record_count, 1) / float(record_count)
    bundle = _build_bundle("champion_v1", success_probability_booster=_FirstFeatureBooster(scale=1.0, offset=0.0))

    realized_profit_and_loss_percentages = numpy.where(
        numpy.arange(record_count) >= 70,
        10.0,
        -5.0,
    ).astype(numpy.float64)
    profitable_flags = (realized_profit_and_loss_percentages > 0.0).astype(numpy.float64)
    fragile_flags = numpy.zeros(record_count, dtype=numpy.float64)
    staled_flags = numpy.zeros(record_count, dtype=numpy.float64)

    metrics = promotion_service._compute_forward_selection_metrics(
        bundle=bundle,
        feature_matrix=feature_matrix,
        realized_profit_and_loss_percentages=realized_profit_and_loss_percentages,
        profitable_flags=profitable_flags,
        fragile_flags=fragile_flags,
        staled_flags=staled_flags,
    )

    assert metrics.selected_record_count == 30
    assert metrics.selected_average_profit_and_loss_percentage == 10.0
    assert metrics.selected_win_rate == 1.0


def test_forward_selection_metrics_exclude_staled_verdicts_from_the_pnl_average() -> None:
    promotion_service = _build_promotion_service()
    record_count: int = 100
    feature_matrix = numpy.arange(record_count, dtype=numpy.float32).reshape(record_count, 1) / float(record_count)
    bundle = _build_bundle("champion_v1", success_probability_booster=_FirstFeatureBooster(scale=1.0, offset=0.0))

    realized_profit_and_loss_percentages = numpy.full(record_count, 10.0, dtype=numpy.float64)
    realized_profit_and_loss_percentages[90:] = -100.0
    profitable_flags = (realized_profit_and_loss_percentages > 0.0).astype(numpy.float64)
    fragile_flags = numpy.zeros(record_count, dtype=numpy.float64)
    fragile_flags[90:] = 1.0
    staled_flags = numpy.zeros(record_count, dtype=numpy.float64)
    staled_flags[90:] = 1.0

    metrics = promotion_service._compute_forward_selection_metrics(
        bundle=bundle,
        feature_matrix=feature_matrix,
        realized_profit_and_loss_percentages=realized_profit_and_loss_percentages,
        profitable_flags=profitable_flags,
        fragile_flags=fragile_flags,
        staled_flags=staled_flags,
    )

    assert metrics.selected_record_count == 30
    assert metrics.selected_average_profit_and_loss_percentage == 10.0
    assert metrics.selected_fragility_rate == 10.0 / 30.0
