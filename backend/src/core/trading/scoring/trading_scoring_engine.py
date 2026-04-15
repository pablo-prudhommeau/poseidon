from __future__ import annotations

from typing import Optional, Final

from src.configuration.config import settings
from src.core.trading.scoring.trading_scoring_scalers import TradingFeatureScalers
from src.core.trading.trading_structures import TradingCandidate, TradingFeatureValues, TradingScoringWeights
from src.core.utils.math_utils import _clamp, _squash_positive_percentage
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_MOMENTUM_WEIGHT_5M: Final[float] = 0.6
_MOMENTUM_WEIGHT_1H: Final[float] = 0.4
_MOMENTUM_WEIGHT_6H: Final[float] = 0.25
_MOMENTUM_WEIGHT_24H: Final[float] = 0.1
_MOMENTUM_TOTAL_WEIGHT: Final[float] = _MOMENTUM_WEIGHT_5M + _MOMENTUM_WEIGHT_1H + _MOMENTUM_WEIGHT_6H + _MOMENTUM_WEIGHT_24H


def compute_buy_sell_score(transaction_activity: Optional[object]) -> float:
    from src.integrations.dexscreener.dexscreener_structures import DexscreenerTransactionActivity
    typed_activity: Optional[DexscreenerTransactionActivity] = transaction_activity
    if not typed_activity:
        return 0.5

    activity_bucket = typed_activity.h1 if typed_activity.h1 else typed_activity.h24
    if not activity_bucket:
        return 0.5

    buys = activity_bucket.buys
    sells = activity_bucket.sells
    total_transactions = buys + sells

    if total_transactions <= 0:
        return 0.5
    return buys / total_transactions


def blend_momentum_percentages(percent_m5: float, percent_h1: float, percent_h6: float, percent_h24: float) -> float:
    squashed_percent_m5 = _squash_positive_percentage(percent_m5)
    squashed_percent_h1 = _squash_positive_percentage(percent_h1)
    squashed_percent_h6 = _squash_positive_percentage(percent_h6)
    squashed_percent_h24 = _squash_positive_percentage(percent_h24)

    weighted_sum = (
            _MOMENTUM_WEIGHT_5M * squashed_percent_m5
            + _MOMENTUM_WEIGHT_1H * squashed_percent_h1
            + _MOMENTUM_WEIGHT_6H * squashed_percent_h6
            + _MOMENTUM_WEIGHT_24H * squashed_percent_h24
    )
    return weighted_sum / _MOMENTUM_TOTAL_WEIGHT


class TradingScoringEngine:
    def __init__(self) -> None:
        self.feature_scalers = TradingFeatureScalers()
        self.scoring_weights = TradingScoringWeights.load_from_configuration()

    def fit_scalers_to_cohort(self, candidate_cohort: list[TradingCandidate]) -> TradingScoringEngine:
        extracted_feature_rows = [self.extract_raw_features_from_candidate(candidate=candidate) for candidate in candidate_cohort]
        self.feature_scalers.fit_from_feature_collection(features=extracted_feature_rows)
        logger.debug("[TRADING][SCORING][ENGINE] Successfully fitted feature scalers across %d candidates", len(extracted_feature_rows))
        return self

    def compute_statistics_score(self, candidate: TradingCandidate) -> float:
        raw_features = self.extract_raw_features_from_candidate(candidate=candidate)

        normalized_liquidity = self.feature_scalers.liquidity_usd.transform_value(value=raw_features.liquidity_usd)
        normalized_volume = self.feature_scalers.volume_24h_usd.transform_value(value=raw_features.volume_24h_usd)
        normalized_age = 1.0 - self.feature_scalers.age_hours.transform_value(value=raw_features.age_hours)
        normalized_momentum = self.feature_scalers.momentum_score.transform_value(value=raw_features.momentum_score)
        normalized_order_flow = self.feature_scalers.order_flow_score.transform_value(value=raw_features.order_flow_score)

        weighted_sum = (
                self.scoring_weights.liquidity_weight * normalized_liquidity
                + self.scoring_weights.volume_weight * normalized_volume
                + self.scoring_weights.age_weight * normalized_age
                + self.scoring_weights.momentum_weight * normalized_momentum
                + self.scoring_weights.order_flow_weight * normalized_order_flow
        )

        resolved_total_weight = self.scoring_weights.total_weight if self.scoring_weights.total_weight > 0.0 else 1e-9
        final_score = 100.0 * (weighted_sum / resolved_total_weight)
        bounded_score = _clamp(final_score, 0.0, 100.0)

        token_symbol = candidate.dexscreener_token_information.base_token.symbol
        logger.debug(
            "[TRADING][SCORING][STATISTICS] Token %s achieved score %f with normalized features: liquidity=%f, volume=%f, age=%f, momentum=%f, order_flow=%f",
            token_symbol, bounded_score, normalized_liquidity, normalized_volume, normalized_age, normalized_momentum, normalized_order_flow,
        )
        return bounded_score

    def apply_artificial_intelligence_adjustment(self, statistics_score: float, artificial_intelligence_delta: float) -> float:
        delta_multiplier = settings.TRADING_AI_DELTA_MULTIPLIER
        maximum_absolute_points = settings.TRADING_AI_MAX_ABSOLUTE_DELTA_POINTS

        scaled_delta = artificial_intelligence_delta * delta_multiplier
        bounded_delta = _clamp(scaled_delta, -maximum_absolute_points, +maximum_absolute_points)
        adjusted_entry_score = _clamp(statistics_score + bounded_delta, 0.0, 100.0)

        logger.debug(
            "[TRADING][SCORING][AI_ADJUSTMENT] Adjusted base score %f with AI delta %f resulting in final entry score %f",
            statistics_score, bounded_delta, adjusted_entry_score,
        )
        return adjusted_entry_score

    def extract_raw_features_from_candidate(self, candidate: TradingCandidate) -> TradingFeatureValues:
        token_information = candidate.dexscreener_token_information

        liquidity_usd = token_information.liquidity.usd if token_information.liquidity and token_information.liquidity.usd is not None else 0.0
        volume_24h_usd = token_information.volume.h24 if token_information.volume and token_information.volume.h24 is not None else 0.0

        percent_m5 = token_information.price_change.m5 if token_information.price_change and token_information.price_change.m5 is not None else 0.0
        percent_h1 = token_information.price_change.h1 if token_information.price_change and token_information.price_change.h1 is not None else 0.0
        percent_h6 = token_information.price_change.h6 if token_information.price_change and token_information.price_change.h6 is not None else 0.0
        percent_h24 = token_information.price_change.h24 if token_information.price_change and token_information.price_change.h24 is not None else 0.0

        momentum_score = blend_momentum_percentages(percent_m5=percent_m5, percent_h1=percent_h1, percent_h6=percent_h6, percent_h24=percent_h24)
        order_flow_score = compute_buy_sell_score(token_information.transactions)

        return TradingFeatureValues(
            liquidity_usd=liquidity_usd,
            volume_24h_usd=volume_24h_usd,
            age_hours=token_information.age_hours,
            momentum_score=momentum_score,
            order_flow_score=order_flow_score,
        )
