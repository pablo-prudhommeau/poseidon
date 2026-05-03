from __future__ import annotations

from collections import defaultdict

from src.api.http.api_schemas import (
    AnalyticsResponse,
    AnalyticsHeatmapCellPayload,
    AnalyticsHeatmapSeriesPayload,
    AnalyticsKpiPayload,
    AnalyticsScatterPointPayload,
    AnalyticsScatterSeriesPayload,
    AnalyticsTimelinePointPayload,
)
from src.core.trading.analytics.trading_analytics_helpers import MINIMUM_POINTS_PER_BUCKET
from src.core.trading.analytics.trading_analytics_helpers import format_metric_value, ROLLING_WINDOW_SIZE
from src.core.trading.analytics.trading_analytics_metric_bucket_statistics_engine import (
    METRIC_DEFINITIONS,
    compute_all_metric_bucket_profiles,
)
from src.core.trading.analytics.trading_analytics_structures import (
    AnalyticsOutcomeRecord,
    AnalyticsTimelineOutcome,
    AnalyticsDailyAggregation,
    MetricBucketProfile,
    MetricDefinition,
)
from src.core.utils.date_utils import format_datetime_to_local_iso
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def compute_kpis(
        records: list[AnalyticsOutcomeRecord],
        total_evaluations: int,
) -> AnalyticsKpiPayload:
    all_pnl_percentages: list[float] = []
    all_pnl_usd: list[float] = []
    all_holding_durations: list[float] = []
    win_count = 0
    loss_count = 0
    gross_profit = 0.0
    gross_loss = 0.0

    for record in records:
        if not record.has_outcome:
            continue

        trade_pnl_usd = record.realized_profit_and_loss_usd
        all_pnl_percentages.append(record.realized_profit_and_loss_percentage)
        all_pnl_usd.append(trade_pnl_usd)
        all_holding_durations.append(record.holding_duration_minutes)
        if record.is_profitable:
            win_count += 1
            gross_profit += trade_pnl_usd
        else:
            loss_count += 1
            gross_loss += abs(trade_pnl_usd)

    total_outcomes = len(all_pnl_percentages)
    win_rate = (win_count / total_outcomes * 100.0) if total_outcomes > 0 else 0.0
    total_pnl_usd = sum(all_pnl_usd) if all_pnl_usd else 0.0
    average_pnl_percentage = (sum(all_pnl_percentages) / total_outcomes) if total_outcomes > 0 else 0.0
    average_holding_duration = (sum(all_holding_durations) / total_outcomes) if total_outcomes > 0 else 0.0
    best_trade_pnl = max(all_pnl_percentages) if all_pnl_percentages else 0.0
    worst_trade_pnl = min(all_pnl_percentages) if all_pnl_percentages else 0.0

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    expected_value_usd = (total_pnl_usd / total_outcomes) if total_outcomes > 0 else 0.0

    logger.info("[ANALYTICS][AGGREGATION][KPIS] Computed KPIs — %d outcomes from %d evaluations, win_rate=%.1f%%, PF=%.2f", total_outcomes, total_evaluations, win_rate, profit_factor)

    return AnalyticsKpiPayload(
        total_evaluations=total_evaluations,
        total_outcomes=total_outcomes,
        win_count=win_count,
        loss_count=loss_count,
        win_rate_percentage=win_rate,
        total_pnl_usd=total_pnl_usd,
        average_pnl_percentage=average_pnl_percentage,
        average_holding_duration_minutes=average_holding_duration,
        best_trade_pnl_percentage=best_trade_pnl,
        worst_trade_pnl_percentage=worst_trade_pnl,
        profit_factor=profit_factor,
        expected_value_usd=expected_value_usd,
    )


def _find_metric_definition(metric_key: str) -> MetricDefinition | None:
    for definition in METRIC_DEFINITIONS:
        if definition.key == metric_key:
            return definition
    return None


def _convert_bucket_profile_to_heatmap_series(profile: MetricBucketProfile) -> AnalyticsHeatmapSeriesPayload:
    metric_definition = _find_metric_definition(profile.metric_key)
    metric_label = metric_definition.label if metric_definition else profile.metric_key
    metric_unit = metric_definition.unit if metric_definition else "score"

    if not profile.bucket_statistics:
        return AnalyticsHeatmapSeriesPayload(metric_key=profile.metric_key, metric_label=metric_label, cells=[])

    valid_averages = [bucket.average_pnl for bucket in profile.bucket_statistics if bucket.sample_count >= MINIMUM_POINTS_PER_BUCKET]
    maximum_average = max(valid_averages) if valid_averages else 0.0
    optimal_threshold = maximum_average - abs(maximum_average) * 0.10

    cells: list[AnalyticsHeatmapCellPayload] = []

    for bucket in profile.bucket_statistics:
        range_label = f"{format_metric_value(bucket.range_min, metric_unit)} to {format_metric_value(bucket.range_max, metric_unit)}"

        if bucket.sample_count >= MINIMUM_POINTS_PER_BUCKET:
            logger.debug(
                "[ANALYTICS][HEATMAP][GOLDEN_CHECK] %s [%s] — samples=%d, WR=%.1f%%, PnL=%.1f%%, OHR=%.1f%%, Hold=%.1fh, Vel=%.2f → golden=%s",
                profile.metric_key, range_label, bucket.sample_count,
                bucket.win_rate, bucket.average_pnl,
                bucket.outlier_hit_rate,
                bucket.average_holding_time_minutes / 60.0,
                bucket.capital_velocity, bucket.is_golden,
            )

        cells.append(AnalyticsHeatmapCellPayload(
            range_label=range_label,
            range_min=bucket.range_min,
            range_max=bucket.range_max,
            average_pnl=bucket.average_pnl,
            average_holding_time_minutes=bucket.average_holding_time_minutes,
            capital_velocity=bucket.capital_velocity,
            quartile_1_pnl=bucket.quartile_1_pnl,
            quartile_3_pnl=bucket.quartile_3_pnl,
            sample_count=bucket.sample_count,
            win_count=bucket.win_count,
            win_rate_percentage=bucket.win_rate,
            outlier_hit_rate_percentage=bucket.outlier_hit_rate,
            is_optimal=(bucket.average_pnl > optimal_threshold and bucket.sample_count >= MINIMUM_POINTS_PER_BUCKET),
            is_golden=bucket.is_golden,
            is_toxic=bucket.is_toxic,
        ))

    golden_count = sum(1 for cell in cells if cell.is_golden)
    toxic_count = sum(1 for cell in cells if cell.is_toxic)
    if golden_count > 0 or toxic_count > 0:
        logger.info(
            "[ANALYTICS][HEATMAP][ZONES] %s — %d golden, %d toxic out of %d buckets",
            profile.metric_key, golden_count, toxic_count, len(cells),
        )

    return AnalyticsHeatmapSeriesPayload(metric_key=profile.metric_key, metric_label=metric_label, cells=cells)


def compute_pnl_drivers_heatmap(records: list[AnalyticsOutcomeRecord]) -> list[AnalyticsHeatmapSeriesPayload]:
    closed_records = [record for record in records if record.has_outcome]
    profiles = compute_all_metric_bucket_profiles(closed_records)

    series_list: list[AnalyticsHeatmapSeriesPayload] = []
    for profile in profiles:
        series = _convert_bucket_profile_to_heatmap_series(profile)
        series_list.append(series)

    logger.info("[ANALYTICS][AGGREGATION][HEATMAP][PNL_DRIVERS] Computed %d metric series for PnL drivers", len(series_list))
    return series_list


def compute_timeline(records: list[AnalyticsOutcomeRecord]) -> list[AnalyticsTimelinePointPayload]:
    outcomes: list[AnalyticsTimelineOutcome] = []

    for record in records:
        if not record.has_outcome or not record.occurred_at:
            continue
        date_iso = format_datetime_to_local_iso(record.occurred_at)[:10]
        outcomes.append(AnalyticsTimelineOutcome(
            date_iso=date_iso,
            pnl_usd=record.realized_profit_and_loss_usd,
            pnl_percentage=record.realized_profit_and_loss_percentage,
            is_profitable=record.is_profitable,
        ))

    outcomes.sort(key=lambda outcome: outcome.date_iso)

    daily_aggregations: dict[str, AnalyticsDailyAggregation] = defaultdict(AnalyticsDailyAggregation)

    for outcome in outcomes:
        aggregation = daily_aggregations[outcome.date_iso]
        aggregation.pnl_usd += outcome.pnl_usd
        aggregation.pnl_percentage += outcome.pnl_percentage
        aggregation.trade_count += 1
        if outcome.is_profitable:
            aggregation.win_count += 1

    timeline_points: list[AnalyticsTimelinePointPayload] = []
    cumulative_pnl_usd = 0.0
    cumulative_pnl_percentage = 0.0
    recent_outcomes: list[bool] = []

    for date_iso in sorted(daily_aggregations.keys()):
        aggregation = daily_aggregations[date_iso]
        cumulative_pnl_usd += aggregation.pnl_usd
        cumulative_pnl_percentage += aggregation.pnl_percentage

        wins_today = aggregation.win_count
        total_today = aggregation.trade_count
        for trade_index in range(total_today):
            recent_outcomes.append(trade_index < wins_today)

        if len(recent_outcomes) > ROLLING_WINDOW_SIZE:
            recent_outcomes = recent_outcomes[-ROLLING_WINDOW_SIZE:]

        rolling_win_rate = (sum(1 for outcome in recent_outcomes if outcome) / len(recent_outcomes) * 100.0) if recent_outcomes else 0.0

        timeline_points.append(AnalyticsTimelinePointPayload(
            date_iso=date_iso,
            cumulative_pnl_usd=cumulative_pnl_usd,
            cumulative_pnl_percentage=cumulative_pnl_percentage,
            rolling_win_rate=rolling_win_rate,
            trade_count=total_today,
        ))

    logger.info("[ANALYTICS][AGGREGATION][TIMELINE] Computed %d timeline points", len(timeline_points))
    return timeline_points


def compute_scatter_series(records: list[AnalyticsOutcomeRecord]) -> list[AnalyticsScatterSeriesPayload]:
    closed_records = [record for record in records if record.has_outcome]

    max_scatter_points = 500
    if len(closed_records) > max_scatter_points:
        step = len(closed_records) / max_scatter_points
        sampled_records = [closed_records[int(i * step)] for i in range(max_scatter_points)]
    else:
        sampled_records = closed_records

    scatter_series_list: list[AnalyticsScatterSeriesPayload] = []

    for metric_definition in METRIC_DEFINITIONS:
        points: list[AnalyticsScatterPointPayload] = []

        for record in sampled_records:
            metric_value = metric_definition.accessor(record)
            if metric_value is None:
                continue

            points.append(AnalyticsScatterPointPayload(
                metric_value=metric_value,
                pnl_percentage=record.realized_profit_and_loss_percentage,
                pnl_usd=record.realized_profit_and_loss_usd,
                token_symbol=record.token_symbol,
                exit_reason=record.exit_reason,
            ))

        scatter_series_list.append(AnalyticsScatterSeriesPayload(
            metric_key=metric_definition.key,
            metric_label=metric_definition.label,
            points=points,
        ))

    logger.info("[ANALYTICS][AGGREGATION][SCATTER] Computed scatter series for %d metrics with %d closed evaluations", len(scatter_series_list), len(closed_records))
    return scatter_series_list


def build_analytics_response(
        records: list[AnalyticsOutcomeRecord],
        total_evaluations: int,
        staled_token_addresses: set[str],
) -> AnalyticsResponse:
    logger.info("[ANALYTICS][AGGREGATION] Starting aggregation for %d records out of %d total evaluations", len(records), total_evaluations)

    kpis = compute_kpis(records, total_evaluations)
    pnl_drivers_series = compute_pnl_drivers_heatmap(records)
    timeline = compute_timeline(records)
    scatter_series = compute_scatter_series(records)

    logger.info("[ANALYTICS][AGGREGATION] Aggregation complete")
    return AnalyticsResponse(
        kpis=kpis,
        pnl_drivers_series=pnl_drivers_series,
        timeline=timeline,
        scatter_series=scatter_series,
    )
