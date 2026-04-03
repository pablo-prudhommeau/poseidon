from __future__ import annotations

import math
from typing import Optional

from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingRobustMinMaxScaler:
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

    def fit_distribution(self, values: list[float]) -> TradingRobustMinMaxScaler:
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
        from src.core.utils.math_utils import _clamp

        resolved_lower_bound = 0.0 if self.lower_bound is None else self.lower_bound
        resolved_upper_bound = 1.0 if self.upper_bound is None else self.upper_bound

        normalized_value = (value - resolved_lower_bound) / (resolved_upper_bound - resolved_lower_bound)
        return _clamp(normalized_value, 0.0, 1.0)


class TradingFeatureScalers:
    def __init__(self) -> None:
        self.liquidity_usd = TradingRobustMinMaxScaler()
        self.volume_24h_usd = TradingRobustMinMaxScaler()
        self.age_hours = TradingRobustMinMaxScaler()
        self.momentum_score = TradingRobustMinMaxScaler()
        self.order_flow_score = TradingRobustMinMaxScaler()

    def fit_from_feature_collection(self, features: list) -> None:
        from src.core.trading.trading_structures import TradingFeatureValues
        typed_features: list[TradingFeatureValues] = features
        self.liquidity_usd.fit_distribution(values=[feature.liquidity_usd for feature in typed_features])
        self.volume_24h_usd.fit_distribution(values=[feature.volume_24h_usd for feature in typed_features])
        self.age_hours.fit_distribution(values=[feature.age_hours for feature in typed_features])
        self.momentum_score.fit_distribution(values=[feature.momentum_score for feature in typed_features])
        self.order_flow_score.fit_distribution(values=[feature.order_flow_score for feature in typed_features])
