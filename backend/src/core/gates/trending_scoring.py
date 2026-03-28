from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel

from src.configuration.config import settings
from src.core.structures.structures import Candidate
from src.core.utils.format_utils import _tail
from src.core.utils.math_utils import _clamp, _squash_pct
from src.core.utils.trending_utils import _momentum_ok, _has_valid_intraday_bars, _buy_sell_score
from src.logging.logger import get_logger

logger = get_logger(__name__)


class FeatureValues(BaseModel):
    liquidity_usd: float
    volume_24h_usd: float
    age_hours: float
    momentum_score: float
    order_flow_score: float


class RobustMinMax:
    def __init__(self, lower_percentile: float = 5.0, upper_percentile: float = 95.0) -> None:
        if not (0.0 <= lower_percentile < upper_percentile <= 100.0):
            raise ValueError("Percentile bounds must satisfy strict inequality and remain within the 0 to 100 range")

        self.lower_percentile = lower_percentile
        self.upper_percentile = upper_percentile
        self.lower_bound: Optional[float] = None
        self.upper_bound: Optional[float] = None

    @staticmethod
    def calculate_percentile(sorted_values: list[float], target_percentile: float) -> float:
        if not sorted_values:
            return 0.0

        index_position = (len(sorted_values) - 1) * (target_percentile / 100.0)
        floor_index = math.floor(index_position)
        ceiling_index = math.ceil(index_position)

        if floor_index == ceiling_index:
            return sorted_values[int(index_position)]

        lower_fraction = sorted_values[int(floor_index)] * (ceiling_index - index_position)
        upper_fraction = sorted_values[int(ceiling_index)] * (index_position - floor_index)

        return lower_fraction + upper_fraction

    def fit_distribution(self, values: list[float]) -> RobustMinMax:
        cleaned_values = [value for value in values if not math.isnan(value)]
        cleaned_values.sort()

        if not cleaned_values:
            self.lower_bound = 0.0
            self.upper_bound = 1.0
            return self

        calculated_lower_bound = self.calculate_percentile(sorted_values=cleaned_values, target_percentile=self.lower_percentile)
        calculated_upper_bound = self.calculate_percentile(sorted_values=cleaned_values, target_percentile=self.upper_percentile)

        if calculated_upper_bound <= calculated_lower_bound:
            calculated_upper_bound = calculated_lower_bound + 1.0

        self.lower_bound = calculated_lower_bound
        self.upper_bound = calculated_upper_bound
        return self

    def transform_value(self, value: float) -> float:
        resolved_lower_bound = 0.0 if self.lower_bound is None else self.lower_bound
        resolved_upper_bound = 1.0 if self.upper_bound is None else self.upper_bound

        normalized_value = (value - resolved_lower_bound) / (resolved_upper_bound - resolved_lower_bound)
        return _clamp(normalized_value, 0.0, 1.0)


class FeatureScalers:
    def __init__(self) -> None:
        self.liquidity_usd = RobustMinMax()
        self.volume_24h_usd = RobustMinMax()
        self.age_hours = RobustMinMax()
        self.momentum_score = RobustMinMax()
        self.order_flow_score = RobustMinMax()

    def fit_from_feature_collection(self, features: list[FeatureValues]) -> None:
        self.liquidity_usd.fit_distribution(values=[feature.liquidity_usd for feature in features])
        self.volume_24h_usd.fit_distribution(values=[feature.volume_24h_usd for feature in features])
        self.age_hours.fit_distribution(values=[feature.age_hours for feature in features])
        self.momentum_score.fit_distribution(values=[feature.momentum_score for feature in features])
        self.order_flow_score.fit_distribution(values=[feature.order_flow_score for feature in features])


class ScoringWeights(BaseModel):
    liquidity_weight: float
    volume_weight: float
    age_weight: float
    momentum_weight: float
    order_flow_weight: float

    @classmethod
    def load_from_configuration(cls) -> ScoringWeights:
        return cls(
            liquidity_weight=float(settings.SCORE_WEIGHT_LIQUIDITY),
            volume_weight=float(settings.SCORE_WEIGHT_VOLUME),
            age_weight=float(settings.SCORE_WEIGHT_AGE),
            momentum_weight=float(settings.SCORE_WEIGHT_MOMENTUM),
            order_flow_weight=float(settings.SCORE_WEIGHT_ORDER_FLOW),
        )

    @property
    def total_weight(self) -> float:
        return (
                self.liquidity_weight
                + self.volume_weight
                + self.age_weight
                + self.momentum_weight
                + self.order_flow_weight
        )


class ScoringEngine:
    def __init__(self) -> None:
        self.feature_scalers = FeatureScalers()
        self.scoring_weights = ScoringWeights.load_from_configuration()

    def fit_scalers_to_cohort(self, candidate_cohort: list[Candidate]) -> ScoringEngine:
        extracted_feature_rows = [self.extract_raw_features_from_candidate(candidate=candidate) for candidate in candidate_cohort]
        self.feature_scalers.fit_from_feature_collection(features=extracted_feature_rows)
        logger.debug("[TRENDING][SCORING][ENGINE] Successfully fitted feature scalers across %d candidates", len(extracted_feature_rows))
        return self

    def compute_statistics_score(self, candidate: Candidate) -> float:
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
            "[TRENDING][SCORING][STATISTICS] Token %s achieved score %f with normalized features: liquidity=%f, volume=%f, age=%f, momentum=%f, order_flow=%f",
            token_symbol,
            bounded_score,
            normalized_liquidity,
            normalized_volume,
            normalized_age,
            normalized_momentum,
            normalized_order_flow
        )
        return bounded_score

    def apply_artificial_intelligence_adjustment(self, statistics_score: float, artificial_intelligence_delta: float) -> float:
        delta_multiplier = float(settings.SCORE_AI_DELTA_MULTIPLIER)
        maximum_absolute_points = float(settings.SCORE_AI_MAX_ABS_DELTA_POINTS)

        scaled_delta = artificial_intelligence_delta * delta_multiplier
        bounded_delta = _clamp(scaled_delta, -maximum_absolute_points, +maximum_absolute_points)
        adjusted_entry_score = _clamp(statistics_score + bounded_delta, 0.0, 100.0)

        logger.debug(
            "[TRENDING][SCORING][ADJUSTMENT] Adjusted base score %f with AI delta %f resulting in final entry score %f",
            statistics_score,
            bounded_delta,
            adjusted_entry_score,
        )
        return adjusted_entry_score

    def extract_raw_features_from_candidate(self, candidate: Candidate) -> FeatureValues:
        token_information = candidate.dexscreener_token_information

        liquidity_usd = token_information.liquidity.usd if token_information.liquidity and token_information.liquidity.usd is not None else 0.0
        volume_24h_usd = token_information.volume.h24 if token_information.volume and token_information.volume.h24 is not None else 0.0

        percent_m5 = token_information.price_change.m5 if token_information.price_change and token_information.price_change.m5 is not None else 0.0
        percent_h1 = token_information.price_change.h1 if token_information.price_change and token_information.price_change.h1 is not None else 0.0
        percent_h6 = token_information.price_change.h6 if token_information.price_change and token_information.price_change.h6 is not None else 0.0
        percent_h24 = token_information.price_change.h24 if token_information.price_change and token_information.price_change.h24 is not None else 0.0

        momentum_score = self.blend_momentum_percentages(percent_m5=percent_m5, percent_h1=percent_h1, percent_h6=percent_h6, percent_h24=percent_h24)
        order_flow_score = _buy_sell_score(token_information.transactions)

        return FeatureValues(
            liquidity_usd=liquidity_usd,
            volume_24h_usd=volume_24h_usd,
            age_hours=token_information.age_hours,
            momentum_score=momentum_score,
            order_flow_score=order_flow_score
        )

    @staticmethod
    def blend_momentum_percentages(percent_m5: float, percent_h1: float, percent_h6: float, percent_h24: float) -> float:
        squashed_percent_m5 = _squash_pct(percent_m5)
        squashed_percent_h1 = _squash_pct(percent_h1)
        squashed_percent_h6 = _squash_pct(percent_h6)
        squashed_percent_h24 = _squash_pct(percent_h24)

        return 0.6 * squashed_percent_m5 + 0.4 * squashed_percent_h1 + 0.25 * squashed_percent_h6 + 0.1 * squashed_percent_h24


class QualityContext(BaseModel):
    liquidity_usd: float
    volume_m5_usd: float
    volume_h1_usd: float
    volume_h6_usd: float
    volume_h24_usd: float
    age_hours: float
    percent_m5: float
    percent_h1: float
    percent_h6: float
    percent_h24: float
    momentum_score: float
    liquidity_score: float
    volume_score: float
    order_flow_score: float


class QualityGateResult(BaseModel):
    is_admissible: bool
    score: float
    rejection_reason: str
    context: QualityContext


def evaluate_quality_gate(candidate: Candidate) -> QualityGateResult:
    token_information = candidate.dexscreener_token_information
    base_token = token_information.base_token

    liquidity_usd = token_information.liquidity.usd if token_information.liquidity and token_information.liquidity.usd is not None else 0.0

    volume_m5_usd = token_information.volume.m5 if token_information.volume and token_information.volume.m5 is not None else 0.0
    volume_h1_usd = token_information.volume.h1 if token_information.volume and token_information.volume.h1 is not None else 0.0
    volume_h6_usd = token_information.volume.h6 if token_information.volume and token_information.volume.h6 is not None else 0.0
    volume_h24_usd = token_information.volume.h24 if token_information.volume and token_information.volume.h24 is not None else 0.0

    percent_m5 = token_information.price_change.m5 if token_information.price_change and token_information.price_change.m5 is not None else 0.0
    percent_h1 = token_information.price_change.h1 if token_information.price_change and token_information.price_change.h1 is not None else 0.0
    percent_h6 = token_information.price_change.h6 if token_information.price_change and token_information.price_change.h6 is not None else 0.0
    percent_h24 = token_information.price_change.h24 if token_information.price_change and token_information.price_change.h24 is not None else 0.0

    order_flow_score = _buy_sell_score(token_information.transactions)

    minimum_liquidity_usd = float(settings.TREND_MIN_LIQ_USD)

    minimum_volume_m5_usd = float(settings.TREND_MIN_VOL5M_USD)
    minimum_volume_h1_usd = float(settings.TREND_MIN_VOL1H_USD)
    minimum_volume_h6_usd = float(settings.TREND_MIN_VOL6H_USD)
    minimum_volume_h24_usd = float(settings.TREND_MIN_VOL24H_USD)

    minimum_age_hours = float(settings.DEXSCREENER_MIN_AGE_HOURS)
    maximum_age_hours = float(settings.DEXSCREENER_MAX_AGE_HOURS)

    quality_context = QualityContext(
        liquidity_usd=liquidity_usd,
        volume_m5_usd=volume_m5_usd,
        volume_h1_usd=volume_h1_usd,
        volume_h6_usd=volume_h6_usd,
        volume_h24_usd=volume_h24_usd,
        age_hours=token_information.age_hours,
        percent_m5=percent_m5,
        percent_h1=percent_h1,
        percent_h6=percent_h6,
        percent_h24=percent_h24,
        momentum_score=0.0,
        liquidity_score=0.0,
        volume_score=0.0,
        order_flow_score=order_flow_score
    )

    if liquidity_usd < minimum_liquidity_usd:
        logger.debug("[TRENDING][QUALITY][REJECTION] Token %s rejected due to insufficient liquidity %f against minimum %f", base_token.symbol, liquidity_usd, minimum_liquidity_usd)
        return QualityGateResult(is_admissible=False, score=0.0, rejection_reason="insufficient_liquidity", context=quality_context)

    if volume_h24_usd < minimum_volume_h24_usd:
        logger.debug("[TRENDING][QUALITY][REJECTION] Token %s rejected due to insufficient volume %f against minimum %f", base_token.symbol, volume_h24_usd, minimum_volume_h24_usd)
        return QualityGateResult(is_admissible=False, score=0.0, rejection_reason="insufficient_volume", context=quality_context)

    if token_information.age_hours < minimum_age_hours or token_information.age_hours > maximum_age_hours:
        logger.debug("[TRENDING][QUALITY][REJECTION] Token %s rejected due to age %f falling outside bounds %f to %f", base_token.symbol, token_information.age_hours, minimum_age_hours, maximum_age_hours)
        return QualityGateResult(is_admissible=False, score=0.0, rejection_reason="age_out_of_bounds", context=quality_context)

    if not _momentum_ok(percent_5m=percent_m5, percent_1h=percent_h1, percent_6h=percent_h6, percent_24h=percent_h24):
        logger.debug("[TRENDING][QUALITY][REJECTION] Token %s rejected due to invalid momentum characteristics", base_token.symbol)
        return QualityGateResult(is_admissible=False, score=0.0, rejection_reason="invalid_momentum", context=quality_context)

    squashed_percent_m5 = _squash_pct(percent_m5)
    squashed_percent_h1 = _squash_pct(percent_h1)
    squashed_percent_h6 = _squash_pct(percent_h6)
    squashed_percent_h24 = _squash_pct(percent_h24)

    momentum_score = 0.6 * squashed_percent_m5 + 0.4 * squashed_percent_h1 + 0.25 * squashed_percent_h6 + 0.1 * squashed_percent_h24
    liquidity_component_score = min(1.0, liquidity_usd / (minimum_liquidity_usd * 4.0))

    volume_m5_component = min(1.0, volume_m5_usd / (minimum_volume_m5_usd * 4.0))
    volume_h1_component = min(1.0, volume_h1_usd / (minimum_volume_h1_usd * 4.0))
    volume_h6_component = min(1.0, volume_h6_usd / (minimum_volume_h6_usd * 4.0))
    volume_h24_component = min(1.0, volume_h24_usd / (minimum_volume_h24_usd * 4.0))

    volume_component_score = (
            0.4 * volume_m5_component
            + 0.3 * volume_h1_component
            + 0.2 * volume_h6_component
            + 0.1 * volume_h24_component
    )

    quality_score = 100.0 * (
            0.45 * momentum_score
            + 0.25 * liquidity_component_score
            + 0.30 * volume_component_score
    )

    quality_context.momentum_score = momentum_score
    quality_context.liquidity_score = liquidity_component_score
    quality_context.volume_score = volume_component_score

    return QualityGateResult(is_admissible=True, score=quality_score, rejection_reason="admissible", context=quality_context)


def filter_candidates_by_quality(candidate_cohort: list[Candidate]) -> list[Candidate]:
    if not candidate_cohort:
        logger.info("[TRENDING][QUALITY][FILTER] Cohort is empty, skipping quality gate evaluation")
        return []

    minimum_quality_score_threshold = float(settings.SCORE_MIN_QUALITY)
    retained_candidates: list[Candidate] = []

    for candidate in candidate_cohort:
        gate_result = evaluate_quality_gate(candidate=candidate)
        candidate.quality_score = gate_result.score

        base_token = candidate.dexscreener_token_information.base_token
        short_address = _tail(base_token.address)

        if gate_result.is_admissible and gate_result.score >= minimum_quality_score_threshold:
            if not _has_valid_intraday_bars(candidate):
                logger.debug("[TRENDING][QUALITY][FILTER][REJECTION] Token %s rejected due to missing intraday bars", base_token.symbol)
                continue

            retained_candidates.append(candidate)
            logger.debug("[TRENDING][QUALITY][FILTER][RETAINED] Token %s (%s) passed quality gate with score %f", base_token.symbol, short_address, gate_result.score)
        else:
            logger.debug("[TRENDING][QUALITY][FILTER][REJECTION] Token %s (%s) failed quality gate with score %f against threshold %f. Reason: %s", base_token.symbol, short_address, gate_result.score, minimum_quality_score_threshold, gate_result.rejection_reason)

    if not retained_candidates:
        logger.info("[TRENDING][QUALITY][FILTER] Zero candidates passed the quality gate")
    else:
        logger.info("[TRENDING][QUALITY][FILTER] Successfully retained %d out of %d candidates through the quality gate", len(retained_candidates), len(candidate_cohort))

    return retained_candidates
