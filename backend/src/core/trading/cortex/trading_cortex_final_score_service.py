from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_numerical_utils import (
    bounded_hyperbolic_signal,
    clamp,
    probability_to_centered_signal,
)
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexFeatureVectorSnapshot,
    TradingCortexFinalScoreBreakdown,
    TradingCortexPrediction,
)


class TradingCortexFinalScoreService:
    def calculate_final_score(
            self,
            prediction: TradingCortexPrediction,
            feature_vector_snapshot: TradingCortexFeatureVectorSnapshot,
    ) -> TradingCortexFinalScoreBreakdown:
        success_signal = probability_to_centered_signal(prediction.success_probability)
        toxicity_signal = probability_to_centered_signal(1.0 - prediction.toxicity_probability)
        expected_profit_and_loss_signal = bounded_hyperbolic_signal(
            prediction.expected_profit_and_loss_percentage,
            settings.TRADING_CORTEX_EXPECTED_PROFIT_AND_LOSS_TEMPERATURE,
        )
        shadow_exposure_signal = clamp(
            feature_vector_snapshot.golden_metric_ratio - feature_vector_snapshot.toxic_metric_ratio,
            -1.0,
            1.0,
        )
        regime_signal = clamp(feature_vector_snapshot.regime_signal, -1.0, 1.0)

        weighted_score = (
                settings.TRADING_CORTEX_SUCCESS_PROBABILITY_WEIGHT * success_signal
                + settings.TRADING_CORTEX_TOXICITY_WEIGHT * toxicity_signal
                + settings.TRADING_CORTEX_EXPECTED_PROFIT_AND_LOSS_WEIGHT * expected_profit_and_loss_signal
                + settings.TRADING_CORTEX_SHADOW_EXPOSURE_WEIGHT * shadow_exposure_signal
                + settings.TRADING_CORTEX_REGIME_WEIGHT * regime_signal
        )

        total_weight = (
                settings.TRADING_CORTEX_SUCCESS_PROBABILITY_WEIGHT
                + settings.TRADING_CORTEX_TOXICITY_WEIGHT
                + settings.TRADING_CORTEX_EXPECTED_PROFIT_AND_LOSS_WEIGHT
                + settings.TRADING_CORTEX_SHADOW_EXPOSURE_WEIGHT
                + settings.TRADING_CORTEX_REGIME_WEIGHT
        )
        normalized_weighted_score = 0.0 if total_weight == 0 else clamp(weighted_score / total_weight, -1.0, 1.0)
        final_trade_score = (normalized_weighted_score + 1.0) * 50.0

        return TradingCortexFinalScoreBreakdown(
            success_signal=success_signal,
            toxicity_signal=toxicity_signal,
            expected_profit_and_loss_signal=expected_profit_and_loss_signal,
            shadow_exposure_signal=shadow_exposure_signal,
            regime_signal=regime_signal,
            weighted_score=normalized_weighted_score,
            final_trade_score=final_trade_score,
        )
