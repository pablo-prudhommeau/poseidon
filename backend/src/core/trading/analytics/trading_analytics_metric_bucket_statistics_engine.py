from __future__ import annotations

import statistics

from src.configuration.config import settings
from src.core.trading.analytics.trading_analytics_helpers import compute_bucket_edges, assign_bucket_index, quantile, MINIMUM_POINTS_PER_BUCKET
from src.core.trading.analytics.trading_analytics_structures import AnalyticsOutcomeRecord, MetricBucketStatistics, MetricBucketProfile, MetricDefinition, MetaStatistics
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

METRIC_DEFINITIONS: list[MetricDefinition] = [
    MetricDefinition(key="quality_score", label="Quality score", accessor=lambda record: record.quality_score, unit="score"),
    MetricDefinition(key="liquidity_usd", label="Liquidity ($)", accessor=lambda record: record.liquidity_usd, unit="usd"),
    MetricDefinition(key="market_cap_usd", label="Market cap ($)", accessor=lambda record: record.market_cap_usd, unit="usd"),
    MetricDefinition(key="volume_m5_usd", label="Volume 5m ($)", accessor=lambda record: record.volume_m5_usd, unit="usd"),
    MetricDefinition(key="volume_h1_usd", label="Volume 1h ($)", accessor=lambda record: record.volume_h1_usd, unit="usd"),
    MetricDefinition(key="volume_h6_usd", label="Volume 6h ($)", accessor=lambda record: record.volume_h6_usd, unit="usd"),
    MetricDefinition(key="volume_h24_usd", label="Volume 24h ($)", accessor=lambda record: record.volume_h24_usd, unit="usd"),
    MetricDefinition(key="price_change_m5", label="Δ5m (%)", accessor=lambda record: record.price_change_percentage_m5, unit="percent"),
    MetricDefinition(key="price_change_h1", label="Δ1h (%)", accessor=lambda record: record.price_change_percentage_h1, unit="percent"),
    MetricDefinition(key="price_change_h6", label="Δ6h (%)", accessor=lambda record: record.price_change_percentage_h6, unit="percent"),
    MetricDefinition(key="price_change_h24", label="Δ24h (%)", accessor=lambda record: record.price_change_percentage_h24, unit="percent"),
    MetricDefinition(key="token_age_hours", label="Token age (h)", accessor=lambda record: record.token_age_hours, unit="hours"),
    MetricDefinition(key="transaction_count_m5", label="Transactions 5m", accessor=lambda record: record.transaction_count_m5, unit="count"),
    MetricDefinition(key="transaction_count_h1", label="Transactions 1h", accessor=lambda record: record.transaction_count_h1, unit="count"),
    MetricDefinition(key="transaction_count_h6", label="Transactions 6h", accessor=lambda record: record.transaction_count_h6, unit="count"),
    MetricDefinition(key="transaction_count_h24", label="Transactions 24h", accessor=lambda record: record.transaction_count_h24, unit="count"),
    MetricDefinition(key="buy_to_sell_ratio", label="Buy/Sell ratio", accessor=lambda record: record.buy_to_sell_ratio, unit="ratio"),
    MetricDefinition(key="fully_diluted_valuation_usd", label="FDV ($)", accessor=lambda record: record.fully_diluted_valuation_usd, unit="usd"),
    MetricDefinition(key="dexscreener_boost", label="Dexscreener Boost", accessor=lambda record: record.dexscreener_boost, unit="count"),
    MetricDefinition(key="liquidity_churn_h24", label="Liquidity Churn 24h", accessor=lambda record: (record.volume_h24_usd / record.liquidity_usd) if record.liquidity_usd and record.liquidity_usd > 0 else 0.0, unit="ratio"),
    MetricDefinition(key="momentum_acceleration_5m_1h", label="Momentum Accel. 5m/1h", accessor=lambda record: (record.price_change_percentage_m5 / record.price_change_percentage_h1) if record.price_change_percentage_h1 and record.price_change_percentage_h1 != 0 else 0.0, unit="ratio"),
]


def evaluate_golden_condition(bucket_statistics: MetricBucketStatistics) -> bool:
    return (
            bucket_statistics.sample_count >= MINIMUM_POINTS_PER_BUCKET
            and bucket_statistics.win_rate > settings.TRADING_SHADOWING_GOLDEN_WIN_RATE_THRESHOLD * 100.0
            and bucket_statistics.average_pnl > settings.TRADING_SHADOWING_GOLDEN_AVERAGE_PNL_THRESHOLD * 100.0
            and bucket_statistics.outlier_hit_rate > settings.TRADING_SHADOWING_GOLDEN_OUTLIER_HIT_RATE_THRESHOLD * 100.0
            and (bucket_statistics.average_holding_time_minutes / 60.0) < settings.TRADING_SHADOWING_GOLDEN_HOLDING_TIME_THRESHOLD
            and bucket_statistics.capital_velocity > settings.TRADING_SHADOWING_GOLDEN_CAPITAL_VELOCITY_THRESHOLD
    )


def evaluate_toxic_condition(bucket_statistics: MetricBucketStatistics, meta_statistics: MetaStatistics) -> bool:
    toxic_win_rate = (meta_statistics.win_rate + settings.TRADING_SHADOWING_TOXIC_WIN_RATE_OFFSET) * 100.0
    toxic_average_pnl = meta_statistics.average_pnl + settings.TRADING_SHADOWING_TOXIC_AVERAGE_PNL_OFFSET * 100.0
    toxic_max_holding_time_hours = meta_statistics.average_holding_time_hours + settings.TRADING_SHADOWING_TOXIC_HOLDING_TIME_OFFSET
    toxic_min_capital_velocity = meta_statistics.capital_velocity + settings.TRADING_SHADOWING_TOXIC_CAPITAL_VELOCITY_OFFSET

    return (
            bucket_statistics.sample_count >= MINIMUM_POINTS_PER_BUCKET
            and (
                    bucket_statistics.win_rate < toxic_win_rate
                    or bucket_statistics.average_pnl < toxic_average_pnl
                    or bucket_statistics.capital_velocity < toxic_min_capital_velocity
                    or (bucket_statistics.average_holding_time_minutes / 60.0) > toxic_max_holding_time_hours
            )
    )


def compute_metric_bucket_profile(
        metric_definition: MetricDefinition,
        closed_records: list[AnalyticsOutcomeRecord],
        meta_statistics: MetaStatistics,
) -> MetricBucketProfile:
    metric_values: list[float] = []
    pnl_values: list[float] = []
    holding_times: list[float] = []
    is_profitable_flags: list[bool] = []

    for record in closed_records:
        metric_value = metric_definition.accessor(record)
        if metric_value is None or not isinstance(metric_value, (int, float)):
            continue
        metric_values.append(float(metric_value))
        pnl_values.append(record.realized_profit_and_loss_percentage)
        holding_times.append(record.holding_duration_minutes)
        is_profitable_flags.append(record.is_profitable)

    if len(metric_values) < MINIMUM_POINTS_PER_BUCKET:
        return MetricBucketProfile(
            metric_key=metric_definition.key,
            bucket_edges=[],
            bucket_statistics=[],
            influence_score=0.0,
            winner_deviation=0.0,
        )

    edges = compute_bucket_edges(metric_values)
    bucket_count = len(edges) - 1

    bucket_pnl_lists: list[list[float]] = [[] for _ in range(bucket_count)]
    bucket_holding_lists: list[list[float]] = [[] for _ in range(bucket_count)]
    bucket_total_counts: list[int] = [0] * bucket_count
    bucket_win_counts: list[int] = [0] * bucket_count
    bucket_outlier_counts: list[int] = [0] * bucket_count

    outlier_pnl_threshold = settings.TRADING_SHADOWING_OUTLIER_PNL_THRESHOLD

    for value_index in range(len(metric_values)):
        bucket_index = assign_bucket_index(metric_values[value_index], edges)
        if bucket_index == -1:
            continue
        bucket_pnl_lists[bucket_index].append(pnl_values[value_index])
        bucket_holding_lists[bucket_index].append(holding_times[value_index])
        bucket_total_counts[bucket_index] += 1
        if is_profitable_flags[value_index]:
            bucket_win_counts[bucket_index] += 1
        if pnl_values[value_index] >= outlier_pnl_threshold:
            bucket_outlier_counts[bucket_index] += 1

    all_bucket_statistics: list[MetricBucketStatistics] = []

    for bucket_index in range(bucket_count):
        pnl_data = bucket_pnl_lists[bucket_index]
        holding_data = bucket_holding_lists[bucket_index]
        sample_count = bucket_total_counts[bucket_index]
        win_count = bucket_win_counts[bucket_index]

        if sample_count > 0:
            sorted_pnl = sorted(pnl_data)
            average_pnl = statistics.fmean(sorted_pnl)
            average_holding = statistics.fmean(holding_data)
            quartile_1 = quantile(sorted_pnl, 0.25) if sample_count >= MINIMUM_POINTS_PER_BUCKET else 0.0
            quartile_3 = quantile(sorted_pnl, 0.75) if sample_count >= MINIMUM_POINTS_PER_BUCKET else 0.0
        else:
            average_pnl = 0.0
            average_holding = 0.0
            quartile_1 = 0.0
            quartile_3 = 0.0

        win_rate = (win_count / sample_count * 100.0) if sample_count > 0 else 0.0
        outlier_hit_rate = (bucket_outlier_counts[bucket_index] / sample_count * 100.0) if sample_count > 0 else 0.0
        capital_velocity = 0.0
        if average_holding > 0:
            capital_velocity = (average_pnl * win_rate / 100.0) / (average_holding / 60.0)

        bucket_stats = MetricBucketStatistics(
            range_min=edges[bucket_index],
            range_max=edges[bucket_index + 1],
            sample_count=sample_count,
            win_count=win_count,
            win_rate=win_rate,
            average_pnl=average_pnl,
            average_holding_time_minutes=average_holding,
            capital_velocity=capital_velocity,
            outlier_hit_rate=outlier_hit_rate,
            quartile_1_pnl=quartile_1,
            quartile_3_pnl=quartile_3,
            is_golden=False,
            is_toxic=False,
        )

        bucket_stats.is_golden = evaluate_golden_condition(bucket_stats)
        bucket_stats.is_toxic = evaluate_toxic_condition(bucket_stats, meta_statistics)

        all_bucket_statistics.append(bucket_stats)

    all_win_rates = [bucket.win_rate for bucket in all_bucket_statistics if bucket.sample_count > 0]
    max_win_rate = max(all_win_rates) if all_win_rates else 0.0
    min_win_rate = min(all_win_rates) if all_win_rates else 0.0
    influence_score = (max_win_rate - min_win_rate)

    global_average = statistics.fmean(metric_values) if metric_values else 0.0
    winner_values = [metric_values[index] for index in range(len(metric_values)) if is_profitable_flags[index]]
    winner_average = statistics.fmean(winner_values) if winner_values else global_average
    standard_deviation = statistics.stdev(metric_values) if len(metric_values) > 1 else 1.0
    winner_deviation = ((winner_average - global_average) / standard_deviation) if standard_deviation > 0.0 else 0.0

    return MetricBucketProfile(
        metric_key=metric_definition.key,
        bucket_edges=edges,
        bucket_statistics=all_bucket_statistics,
        influence_score=influence_score,
        winner_deviation=winner_deviation,
    )


def compute_all_metric_bucket_profiles(
        closed_records: list[AnalyticsOutcomeRecord],
        meta_statistics: MetaStatistics = MetaStatistics(),
) -> list[MetricBucketProfile]:
    profiles: list[MetricBucketProfile] = []
    for metric_definition in METRIC_DEFINITIONS:
        profile = compute_metric_bucket_profile(metric_definition, closed_records, meta_statistics)
        profiles.append(profile)
    logger.info(
        "[ANALYTICS][ENGINE] Computed bucket profiles for %d metrics from %d records",
        len(profiles), len(closed_records),
    )
    return profiles
