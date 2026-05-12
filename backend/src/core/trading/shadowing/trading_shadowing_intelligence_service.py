from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from src.configuration.config import settings
from src.core.trading.analytics.trading_analytics_helpers import map_trading_shadowing_verdict
from src.core.trading.analytics.trading_analytics_metric_bucket_statistics_engine import (
    compute_all_metric_bucket_profiles,
)
from src.core.trading.analytics.trading_analytics_service import compute_kpis
from src.core.trading.analytics.trading_analytics_structures import MetricBucketProfile, MetaStatistics
from src.core.trading.shadowing.trading_shadowing_service import (
    _chronicle_display_lag_timedelta,
    _compute_profit_factor,
    _floor_datetime_to_granularity,
    _series_end_datetime,
)
from src.core.trading.shadowing.trading_shadowing_structures import ShadowIntelligenceMetricSnapshot, ShadowIntelligenceSnapshot
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.date_utils import get_current_local_datetime, ensure_timezone_aware
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session

logger = get_application_logger(__name__)


def compute_shadow_intelligence_snapshot() -> ShadowIntelligenceSnapshot:
    lookback_limit = settings.TRADING_SHADOWING_LOOKBACK_EVALUATIONS
    minimum_outcomes = settings.TRADING_SHADOWING_MIN_OUTCOMES_FOR_ACTIVATION
    minimum_hours = settings.TRADING_SHADOWING_MIN_HOURS_FOR_ACTIVATION

    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        probe_dao = TradingShadowingProbeDao(database_session)

        resolved_verdicts = verdict_dao.retrieve_recent_resolved(limit_count=lookback_limit)
        total_outcomes = len(resolved_verdicts)
        resolved_count = verdict_dao.count_resolved()
        elapsed_hours = probe_dao.retrieve_oldest_probe_timestamp()

        outcomes_insufficient = resolved_count < minimum_outcomes
        hours_insufficient = elapsed_hours < minimum_hours

        if outcomes_insufficient or hours_insufficient:
            logger.info(
                "[TRADING][SHADOW][INTELLIGENCE] Shadow intelligence not yet activated — outcomes=%d/%d, elapsed_hours=%.1f/%.1f",
                resolved_count, minimum_outcomes, elapsed_hours, minimum_hours,
            )
            return ShadowIntelligenceSnapshot(
                metric_snapshots=[],
                total_outcomes_analyzed=total_outcomes,
                is_activated=False,
                resolved_outcome_count=resolved_count,
                elapsed_hours=elapsed_hours,
            )

        analytics_records = [map_trading_shadowing_verdict(verdict) for verdict in resolved_verdicts]

        closed_records = [record for record in analytics_records if record.has_outcome]
        meta_win_rate = 0.0
        meta_average_pnl = 0.0
        meta_average_holding_time_hours = 0.0
        meta_capital_velocity = 0.0
        meta_profit_factor = 0.0
        meta_expected_value_usd = 0.0

        if closed_records:
            meta_kpis = compute_kpis(analytics_records, total_outcomes)
            meta_win_rate = meta_kpis.win_rate_percentage / 100.0
            meta_average_pnl = meta_kpis.average_pnl_percentage
            meta_average_holding_time_hours = meta_kpis.average_holding_duration_minutes / 60.0
            meta_capital_velocity = meta_kpis.capital_velocity
            meta_profit_factor = meta_kpis.profit_factor
            meta_expected_value_usd = meta_kpis.expected_value_usd

        empirical_window_verdict_count = settings.TRADING_SHADOWING_REGIME_EMPIRICAL_PROFIT_FACTOR_WINDOW_VERDICT_COUNT
        empirical_profit_factor = meta_profit_factor
        if empirical_window_verdict_count < lookback_limit and len(resolved_verdicts) > empirical_window_verdict_count:
            empirical_verdicts = resolved_verdicts[:empirical_window_verdict_count]
            empirical_analytics_records = [map_trading_shadowing_verdict(verdict) for verdict in empirical_verdicts]
            empirical_closed_records = [record for record in empirical_analytics_records if record.has_outcome]
            if empirical_closed_records:
                empirical_kpis = compute_kpis(empirical_analytics_records, len(empirical_verdicts))
                empirical_profit_factor = empirical_kpis.profit_factor
                logger.info(
                    "[TRADING][SHADOW][INTELLIGENCE] Empirical profit factor — window_verdicts=%d empirical_pf=%.2f meta_pf=%.2f",
                    empirical_window_verdict_count, empirical_profit_factor, meta_profit_factor,
                )

        meta_statistics = MetaStatistics(
            win_rate=meta_win_rate,
            average_pnl=meta_average_pnl,
            average_holding_time_hours=meta_average_holding_time_hours,
            capital_velocity=meta_capital_velocity,
        )

        bucket_profiles = compute_all_metric_bucket_profiles(analytics_records, meta_statistics)

        metric_snapshots: list[ShadowIntelligenceMetricSnapshot] = []
        for profile in bucket_profiles:
            snapshot = _convert_bucket_profile_to_metric_snapshot(profile)
            if snapshot is not None:
                metric_snapshots.append(snapshot)

        current_time = get_current_local_datetime()
        chronicle_moving_average_period = settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_PERIOD
        sparse_moving_average_period = settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_PERIOD
        chronicle_profit_factor, sparse_pf_buckets = _compute_shadow_chart_sma_profit_factor_at_series_end(
            resolved_verdicts=resolved_verdicts,
            current_time=current_time,
            sma_period=chronicle_moving_average_period,
        )
        sparse_expected_value_usd, sparse_ev_buckets = _compute_shadow_chart_sma_expected_value_usd_at_series_end(
            resolved_verdicts=resolved_verdicts,
            current_time=current_time,
            sma_period=sparse_moving_average_period,
        )

        logger.info(
            "[TRADING][SHADOW][INTELLIGENCE][CHRONICLE_PF] Chronicle profit factor SMA — period=%d sparse_buckets=%d chronicle_pf=%.2f",
            chronicle_moving_average_period,
            sparse_pf_buckets,
            chronicle_profit_factor,
        )
        logger.info(
            "[TRADING][SHADOW][INTELLIGENCE][SPARSE_EV] Sparse expected value USD — lookback_days=%.1f bucket_width_seconds=%d period=%d sparse_buckets=%d sparse_ev_usd=%.2f",
            settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_LOOKBACK_DAYS,
            settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_BUCKET_WIDTH_SECONDS,
            sparse_moving_average_period,
            sparse_ev_buckets,
            sparse_expected_value_usd,
        )

        logger.info(
            "[TRADING][SHADOW][INTELLIGENCE][SNAPSHOT] Shadow intelligence snapshot computed — outcomes=%d metrics=%d wr=%.1f%% pf=%.2f ev=%.2f velocity=%.2f empirical_pf=%.2f chronicle_pf=%.2f sparse_ev_usd=%.2f",
            total_outcomes, len(metric_snapshots), meta_win_rate * 100, meta_profit_factor, meta_expected_value_usd, meta_capital_velocity, empirical_profit_factor, chronicle_profit_factor, sparse_expected_value_usd
        )

        return ShadowIntelligenceSnapshot(
            metric_snapshots=metric_snapshots,
            total_outcomes_analyzed=total_outcomes,
            is_activated=True,
            resolved_outcome_count=resolved_count,
            elapsed_hours=elapsed_hours,
            meta_win_rate=meta_win_rate,
            meta_average_pnl=meta_average_pnl,
            meta_average_holding_time_hours=meta_average_holding_time_hours,
            meta_capital_velocity=meta_capital_velocity,
            meta_profit_factor=meta_profit_factor,
            meta_expected_value_usd=meta_expected_value_usd,
            empirical_profit_factor=empirical_profit_factor,
            chronicle_profit_factor=chronicle_profit_factor,
            sparse_expected_value_usd=sparse_expected_value_usd,
            chronicle_profit_factor_threshold=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_THRESHOLD
        )


def _build_chronicle_sparse_profit_factor_and_mean_pnl_usd_series(
        resolved_verdicts: list,
        current_time: datetime,
        lookback: timedelta,
        granularity_seconds: int,
) -> tuple[list[float], list[float], int]:
    chronicle_lag_td = _chronicle_display_lag_timedelta()
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS

    series_end = _series_end_datetime(current_time)
    global_from_datetime = series_end - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)
    bucket_from_datetime = max(global_from_datetime, series_end - lookback - chronicle_lag_td)
    bucket_to_datetime = series_end + timedelta(seconds=granularity_seconds * max(0, trailing))

    grouped_verdicts: defaultdict = defaultdict(list)
    for verdict in resolved_verdicts:
        verdict_resolved_at = ensure_timezone_aware(verdict.resolved_at)
        if verdict_resolved_at is None:
            continue
        if verdict_resolved_at < bucket_from_datetime or verdict_resolved_at > bucket_to_datetime:
            continue
        if verdict.realized_pnl_usd is None:
            continue
        bucket_start = _floor_datetime_to_granularity(verdict_resolved_at, granularity_seconds)
        grouped_verdicts[bucket_start].append(verdict)

    profit_factors_sparse: list[float] = []
    mean_pnl_usd_sparse: list[float] = []
    for bucket_timestamp in sorted(grouped_verdicts.keys()):
        items = grouped_verdicts[bucket_timestamp]
        pnl_usd_values = [item.realized_pnl_usd for item in items if item.realized_pnl_usd is not None]
        if not pnl_usd_values:
            continue
        gross_profit_usd = sum(value for value in pnl_usd_values if value > 0.0)
        gross_loss_usd = abs(sum(value for value in pnl_usd_values if value < 0.0))
        profit_factors_sparse.append(_compute_profit_factor(gross_profit_usd, gross_loss_usd))
        mean_pnl_usd_sparse.append(sum(pnl_usd_values) / float(len(pnl_usd_values)))

    return profit_factors_sparse, mean_pnl_usd_sparse, len(profit_factors_sparse)


def _shadow_chart_sma_at_series_end(
        series_values: list[float],
        sma_period: int,
        *,
        empty_fallback: float,
) -> float:
    if not series_values:
        return empty_fallback
    winsorized = _winsorize_series_like_shadow_verdict_chronicle_chart(series_values)
    sma_series = _simple_moving_average_like_shadow_verdict_chronicle_chart(winsorized, sma_period)
    return sma_series[-1]


def _compute_shadow_chart_sma_profit_factor_at_series_end(
        resolved_verdicts: list,
        current_time: datetime,
        sma_period: int,
) -> tuple[float, int]:
    chronicle_lookback = timedelta(days=settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_LOOKBACK_DAYS)
    chronicle_bucket_width_seconds = settings.TRADING_SHADOWING_REGIME_CHRONICLE_PROFIT_FACTOR_BUCKET_WIDTH_SECONDS
    profit_factors_sparse, _, sparse_bucket_count = _build_chronicle_sparse_profit_factor_and_mean_pnl_usd_series(
        resolved_verdicts,
        current_time,
        chronicle_lookback,
        chronicle_bucket_width_seconds,
    )
    chronicle_pf = _shadow_chart_sma_at_series_end(profit_factors_sparse, sma_period, empty_fallback=1.0)
    return chronicle_pf, sparse_bucket_count


def _compute_shadow_chart_sma_expected_value_usd_at_series_end(
        resolved_verdicts: list,
        current_time: datetime,
        sma_period: int,
) -> tuple[float, int]:
    lookback = timedelta(days=settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_LOOKBACK_DAYS)
    granularity_seconds = settings.TRADING_SHADOWING_REGIME_SPARSE_EXPECTED_VALUE_BUCKET_WIDTH_SECONDS
    _, mean_pnl_usd_sparse, sparse_bucket_count = _build_chronicle_sparse_profit_factor_and_mean_pnl_usd_series(
        resolved_verdicts,
        current_time,
        lookback,
        granularity_seconds,
    )
    sma_ev_usd = _shadow_chart_sma_at_series_end(mean_pnl_usd_sparse, sma_period, empty_fallback=0.0)
    return sma_ev_usd, sparse_bucket_count


def _winsorize_series_like_shadow_verdict_chronicle_chart(values: list[float]) -> list[float]:
    if len(values) < 4:
        return list(values)
    sorted_values = sorted(values)
    lower_index = max(0, math.floor((len(sorted_values) - 1) * 0.02))
    upper_index = min(len(sorted_values) - 1, math.ceil((len(sorted_values) - 1) * 0.98))
    lower_bound = sorted_values[lower_index]
    upper_bound = sorted_values[upper_index]
    return [min(upper_bound, max(lower_bound, value)) for value in values]


def _simple_moving_average_like_shadow_verdict_chronicle_chart(values: list[float], window_size: int) -> list[float]:
    if len(values) == 0 or window_size <= 1:
        return list(values)
    effective_window = min(window_size, len(values))
    result: list[float] = [0.0] * len(values)
    running_sum = 0.0
    for index in range(len(values)):
        running_sum += values[index]
        if index >= effective_window:
            running_sum -= values[index - effective_window]
        current_window = min(index + 1, effective_window)
        result[index] = running_sum / current_window
    return result


def _convert_bucket_profile_to_metric_snapshot(
        profile: MetricBucketProfile,
) -> Optional[ShadowIntelligenceMetricSnapshot]:
    if not profile.bucket_statistics:
        return None

    return ShadowIntelligenceMetricSnapshot(
        metric_key=profile.metric_key,
        bucket_edges=profile.bucket_edges,
        bucket_win_rates=[bucket.win_rate / 100.0 for bucket in profile.bucket_statistics],
        bucket_average_pnl=[bucket.average_pnl for bucket in profile.bucket_statistics],
        bucket_average_holding_time=[bucket.average_holding_time_minutes for bucket in profile.bucket_statistics],
        bucket_capital_velocity=[bucket.capital_velocity for bucket in profile.bucket_statistics],
        bucket_outlier_hit_rates=[bucket.outlier_hit_rate / 100.0 for bucket in profile.bucket_statistics],
        bucket_sample_counts=[bucket.sample_count for bucket in profile.bucket_statistics],
        bucket_is_golden=[bucket.is_golden for bucket in profile.bucket_statistics],
        bucket_is_toxic=[bucket.is_toxic for bucket in profile.bucket_statistics],
        influence_score=profile.influence_score,
        winner_deviation=profile.winner_deviation,
    )


def find_bucket_index_for_value(value: float, bucket_edges: list[float]) -> int:
    if value is None or len(bucket_edges) < 2:
        return -1
    last_valid_bucket = len(bucket_edges) - 2
    for edge_index in range(len(bucket_edges) - 1):
        if bucket_edges[edge_index] <= value <= bucket_edges[edge_index + 1]:
            return min(edge_index, last_valid_bucket)
    if value > bucket_edges[-1]:
        return last_valid_bucket
    if value < bucket_edges[0]:
        return 0
    return last_valid_bucket


def extract_metric_value_from_candidate(candidate: TradingCandidate, metric_key: str) -> float | None:
    token_information = candidate.dexscreener_token_information
    extraction_map = {
        "quality_score": lambda: candidate.quality_score,
        "ai_adjusted_quality_score": lambda: candidate.ai_adjusted_quality_score,
        "liquidity_usd": lambda: token_information.liquidity.usd if token_information.liquidity else None,
        "market_cap_usd": lambda: token_information.market_cap,
        "volume_m5_usd": lambda: token_information.volume.m5 if token_information.volume else None,
        "volume_h1_usd": lambda: token_information.volume.h1 if token_information.volume else None,
        "volume_h6_usd": lambda: token_information.volume.h6 if token_information.volume else None,
        "volume_h24_usd": lambda: token_information.volume.h24 if token_information.volume else None,
        "price_change_m5": lambda: token_information.price_change.m5 if token_information.price_change else None,
        "price_change_h1": lambda: token_information.price_change.h1 if token_information.price_change else None,
        "price_change_h6": lambda: token_information.price_change.h6 if token_information.price_change else None,
        "price_change_h24": lambda: token_information.price_change.h24 if token_information.price_change else None,
        "token_age_hours": lambda: token_information.age_hours,
        "transaction_count_m5": lambda: token_information.transactions.m5.total_transactions if token_information.transactions and token_information.transactions.m5 else None,
        "transaction_count_h1": lambda: token_information.transactions.h1.total_transactions if token_information.transactions and token_information.transactions.h1 else None,
        "transaction_count_h6": lambda: token_information.transactions.h6.total_transactions if token_information.transactions and token_information.transactions.h6 else None,
        "transaction_count_h24": lambda: token_information.transactions.h24.total_transactions if token_information.transactions and token_information.transactions.h24 else None,
        "buy_to_sell_ratio": lambda: _compute_buy_to_sell_ratio(token_information),
        "fully_diluted_valuation_usd": lambda: token_information.fully_diluted_valuation,
        "dexscreener_boost": lambda: token_information.boost,
        "liquidity_churn_h24": lambda: (token_information.volume.h24 / token_information.liquidity.usd) if token_information.volume and token_information.liquidity and token_information.liquidity.usd and token_information.liquidity.usd > 0 else 0.0,
        "momentum_acceleration_5m_1h": lambda: (token_information.price_change.m5 / token_information.price_change.h1) if token_information.price_change and token_information.price_change.h1 and token_information.price_change.h1 != 0 else 0.0,
    }

    extractor = extraction_map.get(metric_key)
    if extractor is None:
        return None

    return extractor()


def _compute_buy_to_sell_ratio(token_information) -> float | None:
    transactions = token_information.transactions
    if not transactions:
        return None
    reference_bucket = transactions.h1 if transactions.h1 else transactions.h24
    if not reference_bucket:
        return None
    total = reference_bucket.buys + reference_bucket.sells
    if total <= 0:
        return None
    return reference_bucket.buys / total
