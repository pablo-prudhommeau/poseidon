from __future__ import annotations

from typing import Final

trading_cortex_supported_network_identifiers: Final[tuple[str, ...]] = (
    "solana",
    "bsc",
    "base",
    "ethereum",
    "avalanche",
)

trading_cortex_supported_dex_identifiers: Final[tuple[str, ...]] = (
    "pumpfun",
    "pumpswap",
    "raydium",
    "meteora",
    "orca",
    "uniswap",
    "pancakeswap",
)

trading_cortex_supported_metric_keys: Final[tuple[str, ...]] = (
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
    "promotion_score",
    "liquidity_churn_h24",
    "momentum_acceleration_5m_1h",
)


class TradingCortexCandidateFeatures:
    QUALITY_SCORE: Final[str] = "candidate_quality_score"
    TOKEN_AGE_HOURS: Final[str] = "candidate_token_age_hours"
    LIQUIDITY_USD: Final[str] = "candidate_liquidity_usd"
    MARKET_CAP_USD: Final[str] = "candidate_market_cap_usd"
    FULLY_DILUTED_VALUATION_USD: Final[str] = "candidate_fully_diluted_valuation_usd"
    PROMOTION_SCORE: Final[str] = "candidate_promotion_score"
    VOLUME_5M_USD: Final[str] = "candidate_volume_5m_usd"
    VOLUME_1H_USD: Final[str] = "candidate_volume_1h_usd"
    VOLUME_6H_USD: Final[str] = "candidate_volume_6h_usd"
    VOLUME_24H_USD: Final[str] = "candidate_volume_24h_usd"
    PRICE_CHANGE_PERCENTAGE_5M: Final[str] = "candidate_price_change_percentage_5m"
    PRICE_CHANGE_PERCENTAGE_1H: Final[str] = "candidate_price_change_percentage_1h"
    PRICE_CHANGE_PERCENTAGE_6H: Final[str] = "candidate_price_change_percentage_6h"
    PRICE_CHANGE_PERCENTAGE_24H: Final[str] = "candidate_price_change_percentage_24h"
    TRANSACTION_COUNT_5M: Final[str] = "candidate_transaction_count_5m"
    TRANSACTION_COUNT_1H: Final[str] = "candidate_transaction_count_1h"
    TRANSACTION_COUNT_6H: Final[str] = "candidate_transaction_count_6h"
    TRANSACTION_COUNT_24H: Final[str] = "candidate_transaction_count_24h"
    BUY_TO_SELL_RATIO: Final[str] = "candidate_buy_to_sell_ratio"
    ORDER_NOTIONAL_VALUE_USD: Final[str] = "candidate_order_notional_value_usd"
    LIQUIDITY_USD_LOGARITHMIC: Final[str] = "candidate_liquidity_usd_logarithmic"
    MARKET_CAP_USD_LOGARITHMIC: Final[str] = "candidate_market_cap_usd_logarithmic"
    FULLY_DILUTED_VALUATION_USD_LOGARITHMIC: Final[str] = "candidate_fully_diluted_valuation_usd_logarithmic"
    VOLUME_5M_USD_LOGARITHMIC: Final[str] = "candidate_volume_5m_usd_logarithmic"
    VOLUME_1H_USD_LOGARITHMIC: Final[str] = "candidate_volume_1h_usd_logarithmic"
    VOLUME_6H_USD_LOGARITHMIC: Final[str] = "candidate_volume_6h_usd_logarithmic"
    VOLUME_24H_USD_LOGARITHMIC: Final[str] = "candidate_volume_24h_usd_logarithmic"
    TRANSACTION_COUNT_5M_LOGARITHMIC: Final[str] = "candidate_transaction_count_5m_logarithmic"
    TRANSACTION_COUNT_1H_LOGARITHMIC: Final[str] = "candidate_transaction_count_1h_logarithmic"
    TRANSACTION_COUNT_6H_LOGARITHMIC: Final[str] = "candidate_transaction_count_6h_logarithmic"
    TRANSACTION_COUNT_24H_LOGARITHMIC: Final[str] = "candidate_transaction_count_24h_logarithmic"
    LIQUIDITY_CHURN_24H: Final[str] = "candidate_liquidity_churn_24h"
    VOLUME_ACCELERATION_5M_TO_1H: Final[str] = "candidate_volume_acceleration_5m_to_1h"
    VOLUME_ACCELERATION_1H_TO_6H: Final[str] = "candidate_volume_acceleration_1h_to_6h"
    TRANSACTION_ACCELERATION_5M_TO_1H: Final[str] = "candidate_transaction_acceleration_5m_to_1h"
    PRICE_CHANGE_RATIO_5M_TO_1H: Final[str] = "candidate_price_change_ratio_5m_to_1h"
    PRICE_CHANGE_RATIO_1H_TO_6H: Final[str] = "candidate_price_change_ratio_1h_to_6h"
    PRICE_CHANGE_SPREAD_5M_TO_1H: Final[str] = "candidate_price_change_spread_5m_to_1h"
    PRICE_CHANGE_SPREAD_1H_TO_6H: Final[str] = "candidate_price_change_spread_1h_to_6h"
    BUY_PRESSURE_5M: Final[str] = "candidate_buy_pressure_5m"
    MARKET_CAP_TO_LIQUIDITY_RATIO: Final[str] = "candidate_market_cap_to_liquidity_ratio"
    FULLY_DILUTED_VALUATION_TO_LIQUIDITY_RATIO: Final[str] = "candidate_fully_diluted_valuation_to_liquidity_ratio"
    ORDER_NOTIONAL_TO_LIQUIDITY_RATIO: Final[str] = "candidate_order_notional_to_liquidity_ratio"
    IS_RECENT_TOKEN: Final[str] = "candidate_is_recent_token"
    IS_MICRO_CAP_TOKEN: Final[str] = "candidate_is_micro_cap_token"
    IS_HIGH_PROMOTION_TOKEN: Final[str] = "candidate_is_high_promotion_token"
    NETWORK_PREFIX: Final[str] = "candidate_network"
    DEX_PREFIX: Final[str] = "candidate_dex"


class TradingCortexRegimeFeatures:
    META_WIN_RATE: Final[str] = "regime_meta_win_rate"
    META_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE: Final[str] = "regime_meta_average_profit_and_loss_percentage"
    META_AVERAGE_HOLDING_TIME_HOURS: Final[str] = "regime_meta_average_holding_time_hours"
    META_EXPECTED_PNL_VELOCITY: Final[str] = "regime_meta_expected_pnl_velocity"
    META_PROFIT_FACTOR: Final[str] = "regime_meta_profit_factor"
    META_EXPECTED_VALUE_USD: Final[str] = "regime_meta_expected_value_usd"
    EDGE_CHRONICLE_PROFIT_FACTOR: Final[str] = "regime_edge_chronicle_profit_factor"
    EDGE_SPARSE_EXPECTED_VALUE_USD: Final[str] = "regime_edge_sparse_expected_value_usd"
    SIGNAL: Final[str] = "regime_signal"


class TradingCortexMetricAggregateFeatures:
    COUNT: Final[str] = "metric_count"
    GOLDEN_COUNT: Final[str] = "metric_golden_count"
    TOXIC_COUNT: Final[str] = "metric_toxic_count"
    GOLDEN_RATIO: Final[str] = "metric_golden_ratio"
    TOXIC_RATIO: Final[str] = "metric_toxic_ratio"
    AVERAGE_BUCKET_WIN_RATE: Final[str] = "metric_average_bucket_win_rate"
    AVERAGE_BUCKET_PROFIT_AND_LOSS_PERCENTAGE: Final[str] = "metric_average_bucket_profit_and_loss_percentage"
    AVERAGE_BUCKET_EXPECTED_PNL_VELOCITY: Final[str] = "metric_average_bucket_expected_pnl_velocity"
    AVERAGE_BUCKET_OUTLIER_HIT_RATE: Final[str] = "metric_average_bucket_outlier_hit_rate"
    AVERAGE_NORMALIZED_INFLUENCE: Final[str] = "metric_average_normalized_influence"
    CUMULATIVE_GOLDEN_INFLUENCE: Final[str] = "metric_cumulative_golden_influence"
    CUMULATIVE_TOXIC_INFLUENCE: Final[str] = "metric_cumulative_toxic_influence"


class TradingCortexMetricFeatureSuffix:
    CANDIDATE_VALUE: Final[str] = "candidate_value"
    BUCKET_INDEX: Final[str] = "bucket_index"
    BUCKET_WIN_RATE: Final[str] = "bucket_win_rate"
    BUCKET_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE: Final[str] = "bucket_average_profit_and_loss_percentage"
    BUCKET_AVERAGE_HOLDING_TIME_HOURS: Final[str] = "bucket_average_holding_time_hours"
    BUCKET_EXPECTED_PNL_VELOCITY: Final[str] = "bucket_expected_pnl_velocity"
    BUCKET_OUTLIER_HIT_RATE: Final[str] = "bucket_outlier_hit_rate"
    BUCKET_SAMPLE_COUNT: Final[str] = "bucket_sample_count"
    IS_TOXIC: Final[str] = "is_toxic"
    IS_GOLDEN: Final[str] = "is_golden"
    NORMALIZED_INFLUENCE: Final[str] = "normalized_influence"


trading_cortex_per_metric_feature_suffixes: Final[tuple[str, ...]] = (
    TradingCortexMetricFeatureSuffix.CANDIDATE_VALUE,
    TradingCortexMetricFeatureSuffix.BUCKET_INDEX,
    TradingCortexMetricFeatureSuffix.BUCKET_WIN_RATE,
    TradingCortexMetricFeatureSuffix.BUCKET_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE,
    TradingCortexMetricFeatureSuffix.BUCKET_AVERAGE_HOLDING_TIME_HOURS,
    TradingCortexMetricFeatureSuffix.BUCKET_EXPECTED_PNL_VELOCITY,
    TradingCortexMetricFeatureSuffix.BUCKET_OUTLIER_HIT_RATE,
    TradingCortexMetricFeatureSuffix.BUCKET_SAMPLE_COUNT,
    TradingCortexMetricFeatureSuffix.IS_TOXIC,
    TradingCortexMetricFeatureSuffix.IS_GOLDEN,
    TradingCortexMetricFeatureSuffix.NORMALIZED_INFLUENCE,
)


def candidate_categorical_feature_name(feature_prefix: str, supported_identifier: str) -> str:
    return f"{feature_prefix}_is_{supported_identifier}"


def metric_feature_name(metric_key: str, feature_suffix: str) -> str:
    return f"metric_{metric_key}_{feature_suffix}"


def _build_candidate_xgboost_ordered_feature_names() -> tuple[str, ...]:
    ordered_feature_names: list[str] = [
        TradingCortexCandidateFeatures.QUALITY_SCORE,
        TradingCortexCandidateFeatures.TOKEN_AGE_HOURS,
        TradingCortexCandidateFeatures.LIQUIDITY_USD,
        TradingCortexCandidateFeatures.MARKET_CAP_USD,
        TradingCortexCandidateFeatures.FULLY_DILUTED_VALUATION_USD,
        TradingCortexCandidateFeatures.PROMOTION_SCORE,
        TradingCortexCandidateFeatures.VOLUME_5M_USD,
        TradingCortexCandidateFeatures.VOLUME_1H_USD,
        TradingCortexCandidateFeatures.VOLUME_6H_USD,
        TradingCortexCandidateFeatures.VOLUME_24H_USD,
        TradingCortexCandidateFeatures.PRICE_CHANGE_PERCENTAGE_5M,
        TradingCortexCandidateFeatures.PRICE_CHANGE_PERCENTAGE_1H,
        TradingCortexCandidateFeatures.PRICE_CHANGE_PERCENTAGE_6H,
        TradingCortexCandidateFeatures.PRICE_CHANGE_PERCENTAGE_24H,
        TradingCortexCandidateFeatures.TRANSACTION_COUNT_5M,
        TradingCortexCandidateFeatures.TRANSACTION_COUNT_1H,
        TradingCortexCandidateFeatures.TRANSACTION_COUNT_6H,
        TradingCortexCandidateFeatures.TRANSACTION_COUNT_24H,
        TradingCortexCandidateFeatures.BUY_TO_SELL_RATIO,
        TradingCortexCandidateFeatures.ORDER_NOTIONAL_VALUE_USD,
        TradingCortexCandidateFeatures.LIQUIDITY_USD_LOGARITHMIC,
        TradingCortexCandidateFeatures.MARKET_CAP_USD_LOGARITHMIC,
        TradingCortexCandidateFeatures.FULLY_DILUTED_VALUATION_USD_LOGARITHMIC,
        TradingCortexCandidateFeatures.VOLUME_5M_USD_LOGARITHMIC,
        TradingCortexCandidateFeatures.VOLUME_1H_USD_LOGARITHMIC,
        TradingCortexCandidateFeatures.VOLUME_6H_USD_LOGARITHMIC,
        TradingCortexCandidateFeatures.VOLUME_24H_USD_LOGARITHMIC,
        TradingCortexCandidateFeatures.TRANSACTION_COUNT_5M_LOGARITHMIC,
        TradingCortexCandidateFeatures.TRANSACTION_COUNT_1H_LOGARITHMIC,
        TradingCortexCandidateFeatures.TRANSACTION_COUNT_6H_LOGARITHMIC,
        TradingCortexCandidateFeatures.TRANSACTION_COUNT_24H_LOGARITHMIC,
        TradingCortexCandidateFeatures.LIQUIDITY_CHURN_24H,
        TradingCortexCandidateFeatures.VOLUME_ACCELERATION_5M_TO_1H,
        TradingCortexCandidateFeatures.VOLUME_ACCELERATION_1H_TO_6H,
        TradingCortexCandidateFeatures.TRANSACTION_ACCELERATION_5M_TO_1H,
        TradingCortexCandidateFeatures.PRICE_CHANGE_RATIO_5M_TO_1H,
        TradingCortexCandidateFeatures.PRICE_CHANGE_RATIO_1H_TO_6H,
        TradingCortexCandidateFeatures.PRICE_CHANGE_SPREAD_5M_TO_1H,
        TradingCortexCandidateFeatures.PRICE_CHANGE_SPREAD_1H_TO_6H,
        TradingCortexCandidateFeatures.BUY_PRESSURE_5M,
        TradingCortexCandidateFeatures.MARKET_CAP_TO_LIQUIDITY_RATIO,
        TradingCortexCandidateFeatures.FULLY_DILUTED_VALUATION_TO_LIQUIDITY_RATIO,
        TradingCortexCandidateFeatures.ORDER_NOTIONAL_TO_LIQUIDITY_RATIO,
        TradingCortexCandidateFeatures.IS_RECENT_TOKEN,
        TradingCortexCandidateFeatures.IS_MICRO_CAP_TOKEN,
        TradingCortexCandidateFeatures.IS_HIGH_PROMOTION_TOKEN,
    ]
    for supported_identifier in trading_cortex_supported_network_identifiers:
        ordered_feature_names.append(
            candidate_categorical_feature_name(
                TradingCortexCandidateFeatures.NETWORK_PREFIX,
                supported_identifier,
            )
        )
    for supported_identifier in trading_cortex_supported_dex_identifiers:
        ordered_feature_names.append(
            candidate_categorical_feature_name(
                TradingCortexCandidateFeatures.DEX_PREFIX,
                supported_identifier,
            )
        )
    return tuple(ordered_feature_names)


_CANDIDATE_XGBOOST_ORDERED: Final[tuple[str, ...]] = _build_candidate_xgboost_ordered_feature_names()

_REGIME_SCORING_CONTEXT_ORDERED: Final[tuple[str, ...]] = (
    TradingCortexRegimeFeatures.META_WIN_RATE,
    TradingCortexRegimeFeatures.META_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE,
    TradingCortexRegimeFeatures.META_AVERAGE_HOLDING_TIME_HOURS,
    TradingCortexRegimeFeatures.META_EXPECTED_PNL_VELOCITY,
    TradingCortexRegimeFeatures.META_PROFIT_FACTOR,
    TradingCortexRegimeFeatures.META_EXPECTED_VALUE_USD,
    TradingCortexRegimeFeatures.EDGE_CHRONICLE_PROFIT_FACTOR,
    TradingCortexRegimeFeatures.EDGE_SPARSE_EXPECTED_VALUE_USD,
    TradingCortexRegimeFeatures.SIGNAL,
)

_METRIC_AGGREGATE_SCORING_CONTEXT_ORDERED: Final[tuple[str, ...]] = (
    TradingCortexMetricAggregateFeatures.COUNT,
    TradingCortexMetricAggregateFeatures.GOLDEN_COUNT,
    TradingCortexMetricAggregateFeatures.TOXIC_COUNT,
    TradingCortexMetricAggregateFeatures.GOLDEN_RATIO,
    TradingCortexMetricAggregateFeatures.TOXIC_RATIO,
    TradingCortexMetricAggregateFeatures.AVERAGE_BUCKET_WIN_RATE,
    TradingCortexMetricAggregateFeatures.AVERAGE_BUCKET_PROFIT_AND_LOSS_PERCENTAGE,
    TradingCortexMetricAggregateFeatures.AVERAGE_BUCKET_EXPECTED_PNL_VELOCITY,
    TradingCortexMetricAggregateFeatures.AVERAGE_BUCKET_OUTLIER_HIT_RATE,
    TradingCortexMetricAggregateFeatures.AVERAGE_NORMALIZED_INFLUENCE,
    TradingCortexMetricAggregateFeatures.CUMULATIVE_GOLDEN_INFLUENCE,
    TradingCortexMetricAggregateFeatures.CUMULATIVE_TOXIC_INFLUENCE,
)


def build_trading_cortex_xgboost_ordered_feature_names() -> list[str]:
    return list(_CANDIDATE_XGBOOST_ORDERED)


def build_trading_cortex_scoring_context_feature_names() -> list[str]:
    ordered_feature_names: list[str] = list(_REGIME_SCORING_CONTEXT_ORDERED)
    ordered_feature_names.extend(_METRIC_AGGREGATE_SCORING_CONTEXT_ORDERED)
    for metric_key in trading_cortex_supported_metric_keys:
        for feature_suffix in trading_cortex_per_metric_feature_suffixes:
            ordered_feature_names.append(metric_feature_name(metric_key, feature_suffix))
    return ordered_feature_names


def build_trading_cortex_full_feature_vector_names() -> list[str]:
    return build_trading_cortex_xgboost_ordered_feature_names() + build_trading_cortex_scoring_context_feature_names()


trading_cortex_xgboost_ordered_feature_names: list[str] = build_trading_cortex_xgboost_ordered_feature_names()
trading_cortex_scoring_context_feature_names: list[str] = build_trading_cortex_scoring_context_feature_names()
trading_cortex_poseidon_shadow_ordered_feature_names: list[str] = trading_cortex_xgboost_ordered_feature_names
