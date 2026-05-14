from __future__ import annotations

import math
from typing import Optional

from src.configuration.config import settings
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
    TradingCortexShadowMetricFeatureSnapshot,
    TradingCortexShadowRegimeFeatureSnapshot,
    TradingCortexScoringRequest,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

trading_cortex_supported_network_identifiers: list[str] = [
    "solana",
    "bsc",
    "base",
    "ethereum",
    "avalanche",
]

trading_cortex_supported_dex_identifiers: list[str] = [
    "pumpfun",
    "pumpswap",
    "raydium",
    "meteora",
    "orca",
    "uniswap",
    "pancakeswap",
]

trading_cortex_supported_shadow_metric_keys: list[str] = [
    "quality_score",
    "liquidity_usd",
    "market_cap_usd",
    "volume_m5_usd",
    "volume_h1_usd",
    "volume_h6_usd",
    "volume_h24_usd",
    "price_change_m5",
    "price_change_h1",
    "price_change_h6",
    "price_change_h24",
    "token_age_hours",
    "transaction_count_m5",
    "transaction_count_h1",
    "transaction_count_h6",
    "transaction_count_h24",
    "buy_to_sell_ratio",
    "fully_diluted_valuation_usd",
    "dexscreener_boost",
    "liquidity_churn_h24",
    "momentum_acceleration_5m_1h",
]


class TradingCortexFeatureVectorBuilder:
    def build_feature_vector(self, scoring_request: TradingCortexScoringRequest) -> TradingCortexFeatureVectorSnapshot:
        named_feature_values: list[TradingCortexNamedFeatureValue] = []
        candidate_features = scoring_request.candidate_features

        self._append_feature(named_feature_values, "candidate_rank", float(candidate_features.candidate_rank) if candidate_features.candidate_rank is not None else math.nan)
        self._append_feature(named_feature_values, "candidate_quality_score", candidate_features.quality_score)
        self._append_feature(named_feature_values, "candidate_token_age_hours", candidate_features.token_age_hours)
        self._append_feature(named_feature_values, "candidate_liquidity_usd", candidate_features.liquidity_usd)
        self._append_feature(named_feature_values, "candidate_market_cap_usd", optional_float_to_feature_value(candidate_features.market_cap_usd))
        self._append_feature(named_feature_values, "candidate_fully_diluted_valuation_usd", optional_float_to_feature_value(candidate_features.fully_diluted_valuation_usd))
        self._append_feature(named_feature_values, "candidate_dexscreener_boost", optional_float_to_feature_value(candidate_features.dexscreener_boost))
        self._append_feature(named_feature_values, "candidate_volume_5m_usd", candidate_features.volume_5m_usd)
        self._append_feature(named_feature_values, "candidate_volume_1h_usd", candidate_features.volume_1h_usd)
        self._append_feature(named_feature_values, "candidate_volume_6h_usd", candidate_features.volume_6h_usd)
        self._append_feature(named_feature_values, "candidate_volume_24h_usd", candidate_features.volume_24h_usd)
        self._append_feature(named_feature_values, "candidate_price_change_percentage_5m", candidate_features.price_change_percentage_5m)
        self._append_feature(named_feature_values, "candidate_price_change_percentage_1h", candidate_features.price_change_percentage_1h)
        self._append_feature(named_feature_values, "candidate_price_change_percentage_6h", candidate_features.price_change_percentage_6h)
        self._append_feature(named_feature_values, "candidate_price_change_percentage_24h", candidate_features.price_change_percentage_24h)
        self._append_feature(named_feature_values, "candidate_transaction_count_5m", candidate_features.transaction_count_5m)
        self._append_feature(named_feature_values, "candidate_transaction_count_1h", candidate_features.transaction_count_1h)
        self._append_feature(named_feature_values, "candidate_transaction_count_6h", candidate_features.transaction_count_6h)
        self._append_feature(named_feature_values, "candidate_transaction_count_24h", candidate_features.transaction_count_24h)
        self._append_feature(named_feature_values, "candidate_buy_to_sell_ratio", candidate_features.buy_to_sell_ratio)
        self._append_feature(named_feature_values, "candidate_order_notional_value_usd", optional_float_to_feature_value(candidate_features.order_notional_value_usd))

        self._append_feature(named_feature_values, "candidate_liquidity_usd_logarithmic", safe_logarithm_one_plus(candidate_features.liquidity_usd))
        self._append_feature(named_feature_values, "candidate_market_cap_usd_logarithmic", safe_logarithm_one_plus(candidate_features.market_cap_usd))
        self._append_feature(named_feature_values, "candidate_fully_diluted_valuation_usd_logarithmic", safe_logarithm_one_plus(candidate_features.fully_diluted_valuation_usd))
        self._append_feature(named_feature_values, "candidate_volume_5m_usd_logarithmic", safe_logarithm_one_plus(candidate_features.volume_5m_usd))
        self._append_feature(named_feature_values, "candidate_volume_1h_usd_logarithmic", safe_logarithm_one_plus(candidate_features.volume_1h_usd))
        self._append_feature(named_feature_values, "candidate_volume_6h_usd_logarithmic", safe_logarithm_one_plus(candidate_features.volume_6h_usd))
        self._append_feature(named_feature_values, "candidate_volume_24h_usd_logarithmic", safe_logarithm_one_plus(candidate_features.volume_24h_usd))
        self._append_feature(named_feature_values, "candidate_transaction_count_5m_logarithmic", safe_logarithm_one_plus(candidate_features.transaction_count_5m))
        self._append_feature(named_feature_values, "candidate_transaction_count_1h_logarithmic", safe_logarithm_one_plus(candidate_features.transaction_count_1h))
        self._append_feature(named_feature_values, "candidate_transaction_count_6h_logarithmic", safe_logarithm_one_plus(candidate_features.transaction_count_6h))
        self._append_feature(named_feature_values, "candidate_transaction_count_24h_logarithmic", safe_logarithm_one_plus(candidate_features.transaction_count_24h))

        self._append_feature(named_feature_values, "candidate_liquidity_churn_24h", safe_ratio(candidate_features.volume_24h_usd, candidate_features.liquidity_usd))
        self._append_feature(named_feature_values, "candidate_volume_acceleration_5m_to_1h", safe_ratio(candidate_features.volume_5m_usd, candidate_features.volume_1h_usd))
        self._append_feature(named_feature_values, "candidate_volume_acceleration_1h_to_6h", safe_ratio(candidate_features.volume_1h_usd, candidate_features.volume_6h_usd))
        self._append_feature(named_feature_values, "candidate_transaction_acceleration_5m_to_1h", safe_ratio(candidate_features.transaction_count_5m, candidate_features.transaction_count_1h))
        self._append_feature(named_feature_values, "candidate_price_change_ratio_5m_to_1h", safe_ratio(candidate_features.price_change_percentage_5m, candidate_features.price_change_percentage_1h))
        self._append_feature(named_feature_values, "candidate_price_change_ratio_1h_to_6h", safe_ratio(candidate_features.price_change_percentage_1h, candidate_features.price_change_percentage_6h))
        self._append_feature(named_feature_values, "candidate_price_change_spread_5m_to_1h", candidate_features.price_change_percentage_5m - candidate_features.price_change_percentage_1h)
        self._append_feature(named_feature_values, "candidate_price_change_spread_1h_to_6h", candidate_features.price_change_percentage_1h - candidate_features.price_change_percentage_6h)
        self._append_feature(named_feature_values, "candidate_buy_pressure_5m", candidate_features.buy_to_sell_ratio * candidate_features.volume_5m_usd)
        self._append_feature(named_feature_values, "candidate_market_cap_to_liquidity_ratio", safe_ratio(candidate_features.market_cap_usd, candidate_features.liquidity_usd))
        self._append_feature(named_feature_values, "candidate_fully_diluted_valuation_to_liquidity_ratio", safe_ratio(candidate_features.fully_diluted_valuation_usd, candidate_features.liquidity_usd))
        self._append_feature(named_feature_values, "candidate_order_notional_to_liquidity_ratio", safe_ratio(candidate_features.order_notional_value_usd, candidate_features.liquidity_usd))
        self._append_feature(
            named_feature_values,
            "candidate_is_recent_token",
            1.0 if candidate_features.token_age_hours <= 24.0 else 0.0,
        )
        self._append_feature(
            named_feature_values,
            "candidate_is_micro_cap_token",
            1.0 if candidate_features.market_cap_usd is not None and candidate_features.market_cap_usd <= 2000000.0 else 0.0,
        )
        self._append_feature(
            named_feature_values,
            "candidate_is_high_boost_token",
            1.0 if candidate_features.dexscreener_boost is not None and candidate_features.dexscreener_boost >= 1.0 else 0.0,
        )
        self._append_categorical_indicator_features(
            named_feature_values,
            "candidate_network",
            candidate_features.blockchain_network,
            trading_cortex_supported_network_identifiers,
        )
        self._append_categorical_indicator_features(
            named_feature_values,
            "candidate_dex",
            candidate_features.dex_identifier,
            trading_cortex_supported_dex_identifiers,
        )

        regime_features = scoring_request.shadow_regime_features
        regime_signal = self._compute_regime_signal(regime_features)
        self._append_regime_features(named_feature_values, regime_features, regime_signal)

        shadow_metric_count = len(scoring_request.shadow_metric_features)
        golden_metric_count = sum(1 for shadow_metric_feature in scoring_request.shadow_metric_features if shadow_metric_feature.is_golden)
        toxic_metric_count = sum(1 for shadow_metric_feature in scoring_request.shadow_metric_features if shadow_metric_feature.is_toxic)

        golden_metric_ratio = 0.0
        toxic_metric_ratio = 0.0
        average_bucket_win_rate = math.nan
        average_bucket_profit_and_loss_percentage = math.nan
        average_bucket_capital_velocity = math.nan
        average_bucket_outlier_hit_rate = math.nan
        average_normalized_influence = math.nan
        cumulative_golden_influence = 0.0
        cumulative_toxic_influence = 0.0

        if shadow_metric_count > 0:
            golden_metric_ratio = golden_metric_count / shadow_metric_count
            toxic_metric_ratio = toxic_metric_count / shadow_metric_count
            bucket_win_rates = [shadow_metric_feature.bucket_win_rate for shadow_metric_feature in scoring_request.shadow_metric_features if shadow_metric_feature.bucket_win_rate is not None]
            bucket_profit_and_loss_percentages = [
                shadow_metric_feature.bucket_average_profit_and_loss_percentage
                for shadow_metric_feature in scoring_request.shadow_metric_features
                if shadow_metric_feature.bucket_average_profit_and_loss_percentage is not None
            ]
            bucket_capital_velocities = [
                shadow_metric_feature.bucket_capital_velocity
                for shadow_metric_feature in scoring_request.shadow_metric_features
                if shadow_metric_feature.bucket_capital_velocity is not None
            ]
            bucket_outlier_hit_rates = [
                shadow_metric_feature.bucket_outlier_hit_rate
                for shadow_metric_feature in scoring_request.shadow_metric_features
                if shadow_metric_feature.bucket_outlier_hit_rate is not None
            ]
            normalized_influences = [
                shadow_metric_feature.normalized_influence
                for shadow_metric_feature in scoring_request.shadow_metric_features
                if shadow_metric_feature.normalized_influence is not None
            ]
            if bucket_win_rates:
                average_bucket_win_rate = sum(bucket_win_rates) / len(bucket_win_rates)
            if bucket_profit_and_loss_percentages:
                average_bucket_profit_and_loss_percentage = sum(bucket_profit_and_loss_percentages) / len(bucket_profit_and_loss_percentages)
            if bucket_capital_velocities:
                average_bucket_capital_velocity = sum(bucket_capital_velocities) / len(bucket_capital_velocities)
            if bucket_outlier_hit_rates:
                average_bucket_outlier_hit_rate = sum(bucket_outlier_hit_rates) / len(bucket_outlier_hit_rates)
            if normalized_influences:
                average_normalized_influence = sum(normalized_influences) / len(normalized_influences)
            cumulative_golden_influence = sum(
                shadow_metric_feature.normalized_influence or 0.0
                for shadow_metric_feature in scoring_request.shadow_metric_features
                if shadow_metric_feature.is_golden
            )
            cumulative_toxic_influence = sum(
                shadow_metric_feature.normalized_influence or 0.0
                for shadow_metric_feature in scoring_request.shadow_metric_features
                if shadow_metric_feature.is_toxic
            )

        self._append_feature(named_feature_values, "shadow_metric_count", float(shadow_metric_count))
        self._append_feature(named_feature_values, "shadow_metric_golden_count", float(golden_metric_count))
        self._append_feature(named_feature_values, "shadow_metric_toxic_count", float(toxic_metric_count))
        self._append_feature(named_feature_values, "shadow_metric_golden_ratio", golden_metric_ratio)
        self._append_feature(named_feature_values, "shadow_metric_toxic_ratio", toxic_metric_ratio)
        self._append_feature(named_feature_values, "shadow_metric_average_bucket_win_rate", average_bucket_win_rate)
        self._append_feature(named_feature_values, "shadow_metric_average_bucket_profit_and_loss_percentage", average_bucket_profit_and_loss_percentage)
        self._append_feature(named_feature_values, "shadow_metric_average_bucket_capital_velocity", average_bucket_capital_velocity)
        self._append_feature(named_feature_values, "shadow_metric_average_bucket_outlier_hit_rate", average_bucket_outlier_hit_rate)
        self._append_feature(named_feature_values, "shadow_metric_average_normalized_influence", average_normalized_influence)
        self._append_feature(named_feature_values, "shadow_metric_cumulative_golden_influence", cumulative_golden_influence)
        self._append_feature(named_feature_values, "shadow_metric_cumulative_toxic_influence", cumulative_toxic_influence)

        for supported_shadow_metric_key in trading_cortex_supported_shadow_metric_keys:
            shadow_metric_feature = self._find_shadow_metric_feature(
                scoring_request.shadow_metric_features,
                supported_shadow_metric_key,
            )
            self._append_shadow_metric_features(
                named_feature_values,
                supported_shadow_metric_key,
                shadow_metric_feature,
            )

        return TradingCortexFeatureVectorSnapshot(
            feature_set_version=scoring_request.feature_set_version or settings.TRADING_CORTEX_DEFAULT_FEATURE_SET_VERSION,
            named_feature_values=named_feature_values,
            shadow_metric_count=shadow_metric_count,
            golden_metric_count=golden_metric_count,
            toxic_metric_count=toxic_metric_count,
            golden_metric_ratio=golden_metric_ratio,
            toxic_metric_ratio=toxic_metric_ratio,
            regime_signal=regime_signal,
        )

    def _append_regime_features(
            self,
            named_feature_values: list[TradingCortexNamedFeatureValue],
            regime_features: Optional[TradingCortexShadowRegimeFeatureSnapshot],
            regime_signal: float,
    ) -> None:
        if regime_features is None:
            self._append_feature(named_feature_values, "shadow_regime_meta_win_rate", math.nan)
            self._append_feature(named_feature_values, "shadow_regime_meta_average_profit_and_loss_percentage", math.nan)
            self._append_feature(named_feature_values, "shadow_regime_meta_average_holding_time_hours", math.nan)
            self._append_feature(named_feature_values, "shadow_regime_meta_capital_velocity", math.nan)
            self._append_feature(named_feature_values, "shadow_regime_meta_profit_factor", math.nan)
            self._append_feature(named_feature_values, "shadow_regime_meta_expected_value_usd", math.nan)
            self._append_feature(named_feature_values, "shadow_regime_chronicle_profit_factor", math.nan)
            self._append_feature(named_feature_values, "shadow_regime_sparse_expected_value_usd", math.nan)
            self._append_feature(named_feature_values, "shadow_regime_signal", regime_signal)
            return

        self._append_feature(named_feature_values, "shadow_regime_meta_win_rate", optional_float_to_feature_value(regime_features.meta_win_rate))
        self._append_feature(
            named_feature_values,
            "shadow_regime_meta_average_profit_and_loss_percentage",
            optional_float_to_feature_value(regime_features.meta_average_profit_and_loss_percentage),
        )
        self._append_feature(
            named_feature_values,
            "shadow_regime_meta_average_holding_time_hours",
            optional_float_to_feature_value(regime_features.meta_average_holding_time_hours),
        )
        self._append_feature(
            named_feature_values,
            "shadow_regime_meta_capital_velocity",
            optional_float_to_feature_value(regime_features.meta_capital_velocity),
        )
        self._append_feature(
            named_feature_values,
            "shadow_regime_meta_profit_factor",
            optional_float_to_feature_value(regime_features.meta_profit_factor),
        )
        self._append_feature(
            named_feature_values,
            "shadow_regime_meta_expected_value_usd",
            optional_float_to_feature_value(regime_features.meta_expected_value_usd),
        )
        self._append_feature(
            named_feature_values,
            "shadow_regime_chronicle_profit_factor",
            optional_float_to_feature_value(regime_features.chronicle_profit_factor),
        )
        self._append_feature(
            named_feature_values,
            "shadow_regime_sparse_expected_value_usd",
            optional_float_to_feature_value(regime_features.sparse_expected_value_usd),
        )
        self._append_feature(named_feature_values, "shadow_regime_signal", regime_signal)

    def _compute_regime_signal(self, regime_features: Optional[TradingCortexShadowRegimeFeatureSnapshot]) -> float:
        if regime_features is None:
            return 0.0

        chronicle_profit_factor_signal = bounded_hyperbolic_signal(
            None if regime_features.chronicle_profit_factor is None else regime_features.chronicle_profit_factor - settings.TRADING_CORTEX_REGIME_PROFIT_FACTOR_CENTER,
            settings.TRADING_CORTEX_REGIME_PROFIT_FACTOR_TEMPERATURE,
        )
        sparse_expected_value_signal = bounded_hyperbolic_signal(
            regime_features.sparse_expected_value_usd,
            settings.TRADING_CORTEX_REGIME_EXPECTED_VALUE_TEMPERATURE,
        )
        meta_expected_value_signal = bounded_hyperbolic_signal(
            regime_features.meta_expected_value_usd,
            settings.TRADING_CORTEX_REGIME_EXPECTED_VALUE_TEMPERATURE,
        )
        meta_capital_velocity_signal = bounded_hyperbolic_signal(regime_features.meta_capital_velocity, 2.0)
        composite_signal = (
                0.35 * chronicle_profit_factor_signal
                + 0.25 * sparse_expected_value_signal
                + 0.20 * meta_expected_value_signal
                + 0.20 * meta_capital_velocity_signal
        )
        return clamp(composite_signal, -1.0, 1.0)

    def _append_shadow_metric_features(
            self,
            named_feature_values: list[TradingCortexNamedFeatureValue],
            metric_key: str,
            shadow_metric_feature: Optional[TradingCortexShadowMetricFeatureSnapshot],
    ) -> None:
        metric_feature_prefix = f"shadow_metric_{metric_key}"
        if shadow_metric_feature is None:
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_candidate_value", math.nan)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_index", math.nan)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_win_rate", math.nan)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_average_profit_and_loss_percentage", math.nan)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_average_holding_time_hours", math.nan)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_capital_velocity", math.nan)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_outlier_hit_rate", math.nan)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_sample_count", math.nan)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_is_toxic", 0.0)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_is_golden", 0.0)
            self._append_feature(named_feature_values, f"{metric_feature_prefix}_normalized_influence", math.nan)
            return

        self._append_feature(named_feature_values, f"{metric_feature_prefix}_candidate_value", shadow_metric_feature.candidate_value)
        self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_index", float(shadow_metric_feature.bucket_index) if shadow_metric_feature.bucket_index is not None else math.nan)
        self._append_feature(named_feature_values, f"{metric_feature_prefix}_bucket_win_rate", optional_float_to_feature_value(shadow_metric_feature.bucket_win_rate))
        self._append_feature(
            named_feature_values,
            f"{metric_feature_prefix}_bucket_average_profit_and_loss_percentage",
            optional_float_to_feature_value(shadow_metric_feature.bucket_average_profit_and_loss_percentage),
        )
        self._append_feature(
            named_feature_values,
            f"{metric_feature_prefix}_bucket_average_holding_time_hours",
            optional_float_to_feature_value(shadow_metric_feature.bucket_average_holding_time_hours),
        )
        self._append_feature(
            named_feature_values,
            f"{metric_feature_prefix}_bucket_capital_velocity",
            optional_float_to_feature_value(shadow_metric_feature.bucket_capital_velocity),
        )
        self._append_feature(
            named_feature_values,
            f"{metric_feature_prefix}_bucket_outlier_hit_rate",
            optional_float_to_feature_value(shadow_metric_feature.bucket_outlier_hit_rate),
        )
        self._append_feature(
            named_feature_values,
            f"{metric_feature_prefix}_bucket_sample_count",
            float(shadow_metric_feature.bucket_sample_count) if shadow_metric_feature.bucket_sample_count is not None else math.nan,
        )
        self._append_feature(named_feature_values, f"{metric_feature_prefix}_is_toxic", 1.0 if shadow_metric_feature.is_toxic else 0.0)
        self._append_feature(named_feature_values, f"{metric_feature_prefix}_is_golden", 1.0 if shadow_metric_feature.is_golden else 0.0)
        self._append_feature(
            named_feature_values,
            f"{metric_feature_prefix}_normalized_influence",
            optional_float_to_feature_value(shadow_metric_feature.normalized_influence),
        )

    def _find_shadow_metric_feature(
            self,
            shadow_metric_features: list[TradingCortexShadowMetricFeatureSnapshot],
            metric_key: str,
    ) -> Optional[TradingCortexShadowMetricFeatureSnapshot]:
        for shadow_metric_feature in shadow_metric_features:
            if shadow_metric_feature.metric_key == metric_key:
                return shadow_metric_feature
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
            supported_identifiers: list[str],
    ) -> None:
        normalized_identifier = self._normalize_identifier(raw_identifier)
        for supported_identifier in supported_identifiers:
            feature_name = f"{feature_prefix}_is_{supported_identifier}"
            feature_value = 1.0 if normalized_identifier == supported_identifier else 0.0
            self._append_feature(named_feature_values, feature_name, feature_value)

    def _normalize_identifier(self, raw_identifier: Optional[str]) -> str:
        if raw_identifier is None:
            return ""
        return raw_identifier.strip().lower()
