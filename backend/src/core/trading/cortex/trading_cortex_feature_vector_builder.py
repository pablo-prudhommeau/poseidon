from __future__ import annotations

import math
from typing import Optional

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_feature_catalog import (
    TradingCortexCandidateFeatures,
    TradingCortexMetricAggregateFeatures,
    TradingCortexMetricFeatureSuffix,
    TradingCortexRegimeFeatures,
    candidate_categorical_feature_name,
    metric_feature_name,
    trading_cortex_per_metric_feature_suffixes,
    trading_cortex_supported_metric_keys,
)
from src.core.trading.trading_chain_capability_service import (
    resolve_trading_allowed_blockchain_network_identifiers,
)
from src.core.trading.trading_dex_capability_service import resolve_supported_trading_dex_identifiers
from src.core.trading.cortex.trading_cortex_numerical_utils import (
    bounded_hyperbolic_signal,
    clamp,
    optional_float_to_feature_value,
    safe_logarithm_one_plus,
    safe_ratio,
)
from src.core.trading.cortex.trading_cortex_structures import (
    TradingCortexFeatureVectorSnapshot,
    TradingCortexNamedFeatureValue,
    TradingCortexShadowingMetricFeatureSnapshot,
    TradingCortexShadowingRegimeFeatureSnapshot,
    TradingCortexScoringRequest,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

binary_metric_indicator_suffixes = frozenset({
    TradingCortexMetricFeatureSuffix.IS_TOXIC,
    TradingCortexMetricFeatureSuffix.IS_GOLDEN,
})


class TradingCortexFeatureVectorBuilder:
    def build_feature_vector(self, scoring_request: TradingCortexScoringRequest) -> TradingCortexFeatureVectorSnapshot:
        named_feature_values: list[TradingCortexNamedFeatureValue] = []
        candidate_features = scoring_request.candidate_features

        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.QUALITY_SCORE, candidate_features.quality_score)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TOKEN_AGE_HOURS, candidate_features.token_age_hours)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.LIQUIDITY_USD, candidate_features.liquidity_usd)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.MARKET_CAP_USD, optional_float_to_feature_value(candidate_features.market_cap_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.FULLY_DILUTED_VALUATION_USD, optional_float_to_feature_value(candidate_features.fully_diluted_valuation_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PROMOTION_SCORE, optional_float_to_feature_value(candidate_features.promotion_score))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_5M_USD, candidate_features.volume_5m_usd)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_1H_USD, candidate_features.volume_1h_usd)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_6H_USD, candidate_features.volume_6h_usd)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_24H_USD, candidate_features.volume_24h_usd)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PRICE_CHANGE_PERCENTAGE_5M, candidate_features.price_change_percentage_5m)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PRICE_CHANGE_PERCENTAGE_1H, candidate_features.price_change_percentage_1h)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PRICE_CHANGE_PERCENTAGE_6H, candidate_features.price_change_percentage_6h)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PRICE_CHANGE_PERCENTAGE_24H, candidate_features.price_change_percentage_24h)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_COUNT_5M, candidate_features.transaction_count_5m)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_COUNT_1H, candidate_features.transaction_count_1h)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_COUNT_6H, candidate_features.transaction_count_6h)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_COUNT_24H, candidate_features.transaction_count_24h)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.BUY_TO_SELL_RATIO, candidate_features.buy_to_sell_ratio)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.ORDER_NOTIONAL_VALUE_USD, optional_float_to_feature_value(candidate_features.order_notional_value_usd))

        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.LIQUIDITY_USD_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.liquidity_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.MARKET_CAP_USD_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.market_cap_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.FULLY_DILUTED_VALUATION_USD_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.fully_diluted_valuation_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_5M_USD_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.volume_5m_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_1H_USD_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.volume_1h_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_6H_USD_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.volume_6h_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_24H_USD_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.volume_24h_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_COUNT_5M_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.transaction_count_5m))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_COUNT_1H_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.transaction_count_1h))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_COUNT_6H_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.transaction_count_6h))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_COUNT_24H_LOGARITHMIC, safe_logarithm_one_plus(candidate_features.transaction_count_24h))

        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.LIQUIDITY_CHURN_24H, safe_ratio(candidate_features.volume_24h_usd, candidate_features.liquidity_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_ACCELERATION_5M_TO_1H, safe_ratio(candidate_features.volume_5m_usd, candidate_features.volume_1h_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.VOLUME_ACCELERATION_1H_TO_6H, safe_ratio(candidate_features.volume_1h_usd, candidate_features.volume_6h_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.TRANSACTION_ACCELERATION_5M_TO_1H, safe_ratio(candidate_features.transaction_count_5m, candidate_features.transaction_count_1h))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PRICE_CHANGE_RATIO_5M_TO_1H, safe_ratio(candidate_features.price_change_percentage_5m, candidate_features.price_change_percentage_1h))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PRICE_CHANGE_RATIO_1H_TO_6H, safe_ratio(candidate_features.price_change_percentage_1h, candidate_features.price_change_percentage_6h))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PRICE_CHANGE_SPREAD_5M_TO_1H, candidate_features.price_change_percentage_5m - candidate_features.price_change_percentage_1h)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.PRICE_CHANGE_SPREAD_1H_TO_6H, candidate_features.price_change_percentage_1h - candidate_features.price_change_percentage_6h)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.BUY_PRESSURE_5M, candidate_features.buy_to_sell_ratio * candidate_features.volume_5m_usd)
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.MARKET_CAP_TO_LIQUIDITY_RATIO, safe_ratio(candidate_features.market_cap_usd, candidate_features.liquidity_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.FULLY_DILUTED_VALUATION_TO_LIQUIDITY_RATIO, safe_ratio(candidate_features.fully_diluted_valuation_usd, candidate_features.liquidity_usd))
        self._append_feature(named_feature_values, TradingCortexCandidateFeatures.ORDER_NOTIONAL_TO_LIQUIDITY_RATIO, safe_ratio(candidate_features.order_notional_value_usd, candidate_features.liquidity_usd))
        self._append_feature(
            named_feature_values,
            TradingCortexCandidateFeatures.IS_RECENT_TOKEN,
            1.0 if candidate_features.token_age_hours <= 24.0 else 0.0,
        )
        self._append_feature(
            named_feature_values,
            TradingCortexCandidateFeatures.IS_MICRO_CAP_TOKEN,
            1.0 if candidate_features.market_cap_usd is not None and candidate_features.market_cap_usd <= 2000000.0 else 0.0,
        )
        self._append_feature(
            named_feature_values,
            TradingCortexCandidateFeatures.IS_HIGH_PROMOTION_TOKEN,
            1.0 if candidate_features.promotion_score is not None and candidate_features.promotion_score >= 1.0 else 0.0,
        )
        self._append_categorical_indicator_features(
            named_feature_values,
            TradingCortexCandidateFeatures.NETWORK_PREFIX,
            candidate_features.blockchain_network,
            resolve_trading_allowed_blockchain_network_identifiers(),
        )
        self._append_categorical_indicator_features(
            named_feature_values,
            TradingCortexCandidateFeatures.DEX_PREFIX,
            candidate_features.dex_identifier,
            resolve_supported_trading_dex_identifiers(),
        )

        regime_features = scoring_request.regime_features
        regime_signal = self._compute_regime_signal(regime_features)
        self._append_regime_features(named_feature_values, regime_features, regime_signal)

        metric_count = len(scoring_request.metric_features)
        golden_metric_count = sum(1 for metric_feature in scoring_request.metric_features if metric_feature.is_golden)
        toxic_metric_count = sum(1 for metric_feature in scoring_request.metric_features if metric_feature.is_toxic)

        golden_metric_ratio = 0.0
        toxic_metric_ratio = 0.0
        average_bucket_win_rate = math.nan
        average_bucket_profit_and_loss_percentage = math.nan
        average_bucket_expected_profit_and_loss_velocity = math.nan
        average_bucket_outlier_hit_rate = math.nan
        average_normalized_influence = math.nan
        cumulative_golden_influence = 0.0
        cumulative_toxic_influence = 0.0

        if metric_count > 0:
            golden_metric_ratio = golden_metric_count / metric_count
            toxic_metric_ratio = toxic_metric_count / metric_count
            bucket_win_rates = [metric_feature.bucket_win_rate for metric_feature in scoring_request.metric_features if metric_feature.bucket_win_rate is not None]
            bucket_profit_and_loss_percentages = [
                metric_feature.bucket_average_profit_and_loss_percentage
                for metric_feature in scoring_request.metric_features
                if metric_feature.bucket_average_profit_and_loss_percentage is not None
            ]
            bucket_expected_profit_and_loss_velocities = [
                metric_feature.bucket_expected_pnl_velocity
                for metric_feature in scoring_request.metric_features
                if metric_feature.bucket_expected_pnl_velocity is not None
            ]
            bucket_outlier_hit_rates = [
                metric_feature.bucket_outlier_hit_rate
                for metric_feature in scoring_request.metric_features
                if metric_feature.bucket_outlier_hit_rate is not None
            ]
            normalized_influences = [
                metric_feature.normalized_influence
                for metric_feature in scoring_request.metric_features
                if metric_feature.normalized_influence is not None
            ]
            if bucket_win_rates:
                average_bucket_win_rate = sum(bucket_win_rates) / len(bucket_win_rates)
            if bucket_profit_and_loss_percentages:
                average_bucket_profit_and_loss_percentage = sum(bucket_profit_and_loss_percentages) / len(bucket_profit_and_loss_percentages)
            if bucket_expected_profit_and_loss_velocities:
                average_bucket_expected_profit_and_loss_velocity = (
                        sum(bucket_expected_profit_and_loss_velocities) / len(bucket_expected_profit_and_loss_velocities)
                )
            if bucket_outlier_hit_rates:
                average_bucket_outlier_hit_rate = sum(bucket_outlier_hit_rates) / len(bucket_outlier_hit_rates)
            if normalized_influences:
                average_normalized_influence = sum(normalized_influences) / len(normalized_influences)
            cumulative_golden_influence = sum(
                metric_feature.normalized_influence or 0.0
                for metric_feature in scoring_request.metric_features
                if metric_feature.is_golden
            )
            cumulative_toxic_influence = sum(
                metric_feature.normalized_influence or 0.0
                for metric_feature in scoring_request.metric_features
                if metric_feature.is_toxic
            )

        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.COUNT, float(metric_count))
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.GOLDEN_COUNT, float(golden_metric_count))
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.TOXIC_COUNT, float(toxic_metric_count))
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.GOLDEN_RATIO, golden_metric_ratio)
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.TOXIC_RATIO, toxic_metric_ratio)
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.AVERAGE_BUCKET_WIN_RATE, average_bucket_win_rate)
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.AVERAGE_BUCKET_PROFIT_AND_LOSS_PERCENTAGE, average_bucket_profit_and_loss_percentage)
        self._append_feature(
            named_feature_values,
            TradingCortexMetricAggregateFeatures.AVERAGE_BUCKET_EXPECTED_PNL_VELOCITY,
            average_bucket_expected_profit_and_loss_velocity,
        )
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.AVERAGE_BUCKET_OUTLIER_HIT_RATE, average_bucket_outlier_hit_rate)
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.AVERAGE_NORMALIZED_INFLUENCE, average_normalized_influence)
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.CUMULATIVE_GOLDEN_INFLUENCE, cumulative_golden_influence)
        self._append_feature(named_feature_values, TradingCortexMetricAggregateFeatures.CUMULATIVE_TOXIC_INFLUENCE, cumulative_toxic_influence)

        for supported_metric_key in trading_cortex_supported_metric_keys:
            metric_feature = self._find_metric_feature(
                scoring_request.metric_features,
                supported_metric_key,
            )
            self._append_metric_features(
                named_feature_values,
                supported_metric_key,
                metric_feature,
            )

        return TradingCortexFeatureVectorSnapshot(
            feature_set_version=scoring_request.feature_set_version,
            named_feature_values=named_feature_values,
            metric_count=metric_count,
            golden_metric_count=golden_metric_count,
            toxic_metric_count=toxic_metric_count,
            golden_metric_ratio=golden_metric_ratio,
            toxic_metric_ratio=toxic_metric_ratio,
            regime_signal=regime_signal,
        )

    def _append_regime_features(
            self,
            named_feature_values: list[TradingCortexNamedFeatureValue],
            regime_features: TradingCortexShadowingRegimeFeatureSnapshot,
            regime_signal: float,
    ) -> None:
        self._append_feature(named_feature_values, TradingCortexRegimeFeatures.META_WIN_RATE, optional_float_to_feature_value(regime_features.metrics_meta_win_rate))
        self._append_feature(
            named_feature_values,
            TradingCortexRegimeFeatures.META_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE,
            optional_float_to_feature_value(regime_features.metrics_meta_average_pnl),
        )
        self._append_feature(
            named_feature_values,
            TradingCortexRegimeFeatures.META_AVERAGE_HOLDING_TIME_HOURS,
            optional_float_to_feature_value(regime_features.metrics_meta_average_holding_time_hours),
        )
        self._append_feature(
            named_feature_values,
            TradingCortexRegimeFeatures.META_EXPECTED_PNL_VELOCITY,
            optional_float_to_feature_value(regime_features.metrics_meta_expected_pnl_velocity),
        )
        self._append_feature(
            named_feature_values,
            TradingCortexRegimeFeatures.META_PROFIT_FACTOR,
            optional_float_to_feature_value(regime_features.metrics_meta_profit_factor),
        )
        self._append_feature(
            named_feature_values,
            TradingCortexRegimeFeatures.META_EXPECTED_VALUE_USD,
            optional_float_to_feature_value(regime_features.metrics_meta_expected_value_usd),
        )
        self._append_feature(
            named_feature_values,
            TradingCortexRegimeFeatures.EDGE_CHRONICLE_PROFIT_FACTOR,
            optional_float_to_feature_value(regime_features.edge_chronicle_profit_factor),
        )
        self._append_feature(
            named_feature_values,
            TradingCortexRegimeFeatures.EDGE_SPARSE_EXPECTED_VALUE_USD,
            optional_float_to_feature_value(regime_features.edge_sparse_expected_value_usd),
        )
        self._append_feature(named_feature_values, TradingCortexRegimeFeatures.SIGNAL, regime_signal)

    def _compute_regime_signal(self, regime_features: TradingCortexShadowingRegimeFeatureSnapshot) -> float:
        chronicle_profit_factor_signal = bounded_hyperbolic_signal(
            None if regime_features.edge_chronicle_profit_factor is None else regime_features.edge_chronicle_profit_factor - settings.TRADING_CORTEX_REGIME_PROFIT_FACTOR_CENTER,
            settings.TRADING_CORTEX_REGIME_PROFIT_FACTOR_TEMPERATURE,
        )
        sparse_expected_value_signal = bounded_hyperbolic_signal(
            regime_features.edge_sparse_expected_value_usd,
            settings.TRADING_CORTEX_REGIME_EXPECTED_VALUE_TEMPERATURE,
        )
        meta_expected_value_signal = bounded_hyperbolic_signal(
            regime_features.metrics_meta_expected_value_usd,
            settings.TRADING_CORTEX_REGIME_EXPECTED_VALUE_TEMPERATURE,
        )
        meta_expected_profit_and_loss_velocity_signal = bounded_hyperbolic_signal(
            regime_features.metrics_meta_expected_pnl_velocity,
            2.0,
        )
        composite_signal = (
                0.35 * chronicle_profit_factor_signal
                + 0.25 * sparse_expected_value_signal
                + 0.20 * meta_expected_value_signal
                + 0.20 * meta_expected_profit_and_loss_velocity_signal
        )
        return clamp(composite_signal, -1.0, 1.0)

    def _append_metric_features(
            self,
            named_feature_values: list[TradingCortexNamedFeatureValue],
            metric_key: str,
            metric_feature: Optional[TradingCortexShadowingMetricFeatureSnapshot],
    ) -> None:
        if metric_feature is None:
            for feature_suffix in trading_cortex_per_metric_feature_suffixes:
                feature_name = metric_feature_name(metric_key, feature_suffix)
                if feature_suffix in binary_metric_indicator_suffixes:
                    self._append_feature(named_feature_values, feature_name, 0.0)
                else:
                    self._append_feature(named_feature_values, feature_name, math.nan)
            return

        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.CANDIDATE_VALUE),
            metric_feature.candidate_value,
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.BUCKET_INDEX),
            float(metric_feature.bucket_index) if metric_feature.bucket_index is not None else math.nan,
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.BUCKET_WIN_RATE),
            optional_float_to_feature_value(metric_feature.bucket_win_rate),
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.BUCKET_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE),
            optional_float_to_feature_value(metric_feature.bucket_average_profit_and_loss_percentage),
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.BUCKET_AVERAGE_HOLDING_TIME_HOURS),
            optional_float_to_feature_value(metric_feature.bucket_average_holding_time_hours),
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.BUCKET_EXPECTED_PNL_VELOCITY),
            optional_float_to_feature_value(metric_feature.bucket_expected_pnl_velocity),
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.BUCKET_OUTLIER_HIT_RATE),
            optional_float_to_feature_value(metric_feature.bucket_outlier_hit_rate),
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.BUCKET_SAMPLE_COUNT),
            float(metric_feature.bucket_sample_count) if metric_feature.bucket_sample_count is not None else math.nan,
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.IS_TOXIC),
            1.0 if metric_feature.is_toxic else 0.0,
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.IS_GOLDEN),
            1.0 if metric_feature.is_golden else 0.0,
        )
        self._append_feature(
            named_feature_values,
            metric_feature_name(metric_key, TradingCortexMetricFeatureSuffix.NORMALIZED_INFLUENCE),
            optional_float_to_feature_value(metric_feature.normalized_influence),
        )

    def _find_metric_feature(
            self,
            metric_features: list[TradingCortexShadowingMetricFeatureSnapshot],
            metric_key: str,
    ) -> Optional[TradingCortexShadowingMetricFeatureSnapshot]:
        for metric_feature in metric_features:
            if metric_feature.metric_key == metric_key:
                return metric_feature
        return None

    def _append_feature(
            self,
            named_feature_values: list[TradingCortexNamedFeatureValue],
            feature_name: str,
            feature_value: float,
    ) -> None:
        named_feature_values.append(
            TradingCortexNamedFeatureValue(
                feature_name=feature_name,
                feature_value=feature_value,
            )
        )

    def _append_categorical_indicator_features(
            self,
            named_feature_values: list[TradingCortexNamedFeatureValue],
            feature_prefix: str,
            raw_identifier: Optional[str],
            supported_identifiers: tuple[str, ...] | list[str],
    ) -> None:
        normalized_identifier = self._normalize_identifier(raw_identifier)
        for supported_identifier in supported_identifiers:
            feature_name = candidate_categorical_feature_name(feature_prefix, supported_identifier)
            feature_value = 1.0 if normalized_identifier == supported_identifier else 0.0
            self._append_feature(named_feature_values, feature_name, feature_value)

    def _normalize_identifier(self, raw_identifier: Optional[str]) -> str:
        if raw_identifier is None:
            return ""
        return raw_identifier.strip().lower()
