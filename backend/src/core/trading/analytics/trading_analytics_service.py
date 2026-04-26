from __future__ import annotations

from collections import defaultdict
from typing import Callable

from src.core.trading.analytics.trading_analytics_helpers import compute_decile_edges, assign_bucket_index, quantile, format_metric_value, MINIMUM_POINTS_PER_BUCKET, ROLLING_WINDOW_SIZE
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

from src.core.trading.analytics.trading_analytics_structures import AnalyticsOutcomeRecord
from src.api.http.api_schemas import (
    AnalyticsResponse,
    AnalyticsHeatmapCellPayload,
    AnalyticsHeatmapSeriesPayload,
    AnalyticsKpiPayload,
    AnalyticsScatterPointPayload,
    AnalyticsScatterSeriesPayload,
    AnalyticsTimelinePointPayload,
)
from src.core.utils.date_utils import format_datetime_to_local_iso


class MetricDefinition:
    def __init__(self, key: str, label: str, accessor: Callable[[AnalyticsOutcomeRecord], float], unit: str) -> None:
        self.key = key
        self.label = label
        self.accessor = accessor
        self.unit = unit


METRIC_DEFINITIONS: list[MetricDefinition] = [
    MetricDefinition("quality_score", "Quality score", lambda record: record.quality_score, "score"),
    MetricDefinition("ai_adjusted_quality_score", "AI adjusted quality score", lambda record: record.ai_adjusted_quality_score, "score"),
    MetricDefinition("liquidity_usd", "Liquidity ($)", lambda record: record.liquidity_usd, "usd"),
    MetricDefinition("market_cap_usd", "Market cap ($)", lambda record: record.market_cap_usd, "usd"),
    MetricDefinition("volume_m5_usd", "Volume 5m ($)", lambda record: record.volume_m5_usd, "usd"),
    MetricDefinition("volume_h1_usd", "Volume 1h ($)", lambda record: record.volume_h1_usd, "usd"),
    MetricDefinition("volume_h6_usd", "Volume 6h ($)", lambda record: record.volume_h6_usd, "usd"),
    MetricDefinition("volume_h24_usd", "Volume 24h ($)", lambda record: record.volume_h24_usd, "usd"),
    MetricDefinition("price_change_m5", "Δ5m (%)", lambda record: record.price_change_percentage_m5, "percent"),
    MetricDefinition("price_change_h1", "Δ1h (%)", lambda record: record.price_change_percentage_h1, "percent"),
    MetricDefinition("price_change_h6", "Δ6h (%)", lambda record: record.price_change_percentage_h6, "percent"),
    MetricDefinition("price_change_h24", "Δ24h (%)", lambda record: record.price_change_percentage_h24, "percent"),
    MetricDefinition("token_age_hours", "Token age (h)", lambda record: record.token_age_hours, "hours"),
    MetricDefinition("transaction_count_m5", "Transactions 5m", lambda record: record.transaction_count_m5, "count"),
    MetricDefinition("transaction_count_h1", "Transactions 1h", lambda record: record.transaction_count_h1, "count"),
    MetricDefinition("transaction_count_h6", "Transactions 6h", lambda record: record.transaction_count_h6, "count"),
    MetricDefinition("transaction_count_h24", "Transactions 24h", lambda record: record.transaction_count_h24, "count"),
    MetricDefinition("buy_to_sell_ratio", "Buy/Sell ratio", lambda record: record.buy_to_sell_ratio, "ratio"),
    MetricDefinition("fully_diluted_valuation_usd", "FDV ($)", lambda record: record.fully_diluted_valuation_usd, "usd"),
    MetricDefinition("dexscreener_boost", "Dexscreener Boost", lambda record: record.dexscreener_boost, "count"),
]


def compute_kpis(records: list[AnalyticsOutcomeRecord]) -> AnalyticsKpiPayload:
    total_evaluations = len(records)

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

    logger.info("[ANALYTICS][AGGREGATION][KPIS] Computed KPIs — %d outcomes, win_rate=%.1f%%, PF=%.2f", total_outcomes, win_rate, profit_factor)

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


def compute_pnl_drivers_heatmap(records: list[AnalyticsOutcomeRecord]) -> list[AnalyticsHeatmapSeriesPayload]:
    closed_records = [record for record in records if record.has_outcome]
    series_list: list[AnalyticsHeatmapSeriesPayload] = []

    for metric_definition in METRIC_DEFINITIONS:
        metric_values: list[float] = []
        pnl_values: list[float] = []
        is_profitable_flags: list[bool] = []

        for record in closed_records:
            metric_value = metric_definition.accessor(record)
            metric_values.append(metric_value)
            pnl_values.append(record.realized_profit_and_loss_percentage)
            is_profitable_flags.append(record.is_profitable)

        if len(metric_values) < MINIMUM_POINTS_PER_BUCKET:
            series_list.append(AnalyticsHeatmapSeriesPayload(metric_key=metric_definition.key, metric_label=metric_definition.label, cells=[]))
            continue

        edges = compute_decile_edges(metric_values)
        buckets: list[list[float]] = [[] for _ in range(len(edges) - 1)]
        counts: list[int] = [0 for _ in range(len(edges) - 1)]
        win_counts: list[int] = [0 for _ in range(len(edges) - 1)]

        for index in range(len(metric_values)):
            bucket_index = assign_bucket_index(metric_values[index], edges)
            if bucket_index == -1:
                continue
            buckets[bucket_index].append(pnl_values[index])
            counts[bucket_index] += 1
            if is_profitable_flags[index]:
                win_counts[bucket_index] += 1

        cells: list[AnalyticsHeatmapCellPayload] = []
        medians: list[float] = []

        for bucket_index in range(len(buckets)):
            left_edge = edges[bucket_index]
            right_edge = edges[bucket_index + 1]
            range_label = f"{format_metric_value(left_edge, metric_definition.unit)} to {format_metric_value(right_edge, metric_definition.unit)}"

            bucket_data = buckets[bucket_index]
            if len(bucket_data) >= MINIMUM_POINTS_PER_BUCKET:
                sorted_data = sorted(bucket_data)
                median_value = quantile(sorted_data, 0.5)
                mean_value = sum(sorted_data) / len(sorted_data)
                quartile_1_value = quantile(sorted_data, 0.25)
                quartile_3_value = quantile(sorted_data, 0.75)
            else:
                median_value = 0.0
                mean_value = 0.0
                quartile_1_value = 0.0
                quartile_3_value = 0.0

            medians.append(median_value if len(bucket_data) >= MINIMUM_POINTS_PER_BUCKET else float("-inf"))

            cells.append(AnalyticsHeatmapCellPayload(
                range_label=range_label,
                range_min=left_edge,
                range_max=right_edge,
                median_pnl=median_value,
                mean_pnl=mean_value,
                quartile_1_pnl=quartile_1_value,
                quartile_3_pnl=quartile_3_value,
                sample_count=counts[bucket_index],
                win_count=win_counts[bucket_index],
                win_rate_percentage=(win_counts[bucket_index] / counts[bucket_index] * 100.0) if counts[bucket_index] > 0 else 0.0,
                is_optimal=False,
            ))

        valid_medians = [median for median in medians if median != float("-inf")]
        if valid_medians:
            maximum_median = max(valid_medians)
            optimal_threshold = maximum_median - abs(maximum_median) * 0.10
            for cell_index, cell in enumerate(cells):
                if medians[cell_index] != float("-inf") and medians[cell_index] >= optimal_threshold and counts[cell_index] >= MINIMUM_POINTS_PER_BUCKET:
                    cell.is_optimal = True

        series_list.append(AnalyticsHeatmapSeriesPayload(metric_key=metric_definition.key, metric_label=metric_definition.label, cells=cells))

    logger.info("[ANALYTICS][AGGREGATION][HEATMAP][PNL_DRIVERS] Computed %d metric series for PnL drivers", len(series_list))
    return series_list


def compute_timeline(records: list[AnalyticsOutcomeRecord]) -> list[AnalyticsTimelinePointPayload]:
    outcome_events: list[tuple[str, float, float, bool]] = []

    for record in records:
        if not record.has_outcome or not record.occurred_at:
            continue
        date_key = format_datetime_to_local_iso(record.occurred_at)[:10]
        outcome_events.append((date_key, record.realized_profit_and_loss_usd, record.realized_profit_and_loss_percentage, record.is_profitable))

    outcome_events.sort(key=lambda event: event[0])

    daily_aggregation: dict[str, dict[str, float | int]] = defaultdict(lambda: {"pnl_usd": 0.0, "pnl_pct": 0.0, "count": 0, "wins": 0})

    for date_key, pnl_usd, pnl_pct, is_profitable in outcome_events:
        daily_aggregation[date_key]["pnl_usd"] += pnl_usd
        daily_aggregation[date_key]["pnl_pct"] += pnl_pct
        daily_aggregation[date_key]["count"] += 1
        if is_profitable:
            daily_aggregation[date_key]["wins"] += 1

    timeline_points: list[AnalyticsTimelinePointPayload] = []
    cumulative_pnl_usd = 0.0
    cumulative_pnl_percentage = 0.0
    recent_outcomes: list[bool] = []

    for date_key in sorted(daily_aggregation.keys()):
        day_data = daily_aggregation[date_key]
        cumulative_pnl_usd += day_data["pnl_usd"]
        cumulative_pnl_percentage += day_data["pnl_pct"]

        wins_today = int(day_data["wins"])
        total_today = int(day_data["count"])
        for trade_index in range(total_today):
            recent_outcomes.append(trade_index < wins_today)

        if len(recent_outcomes) > ROLLING_WINDOW_SIZE:
            recent_outcomes = recent_outcomes[-ROLLING_WINDOW_SIZE:]

        rolling_win_rate = (sum(1 for outcome in recent_outcomes if outcome) / len(recent_outcomes) * 100.0) if recent_outcomes else 0.0

        timeline_points.append(AnalyticsTimelinePointPayload(
            date_iso=date_key,
            cumulative_pnl_usd=cumulative_pnl_usd,
            cumulative_pnl_percentage=cumulative_pnl_percentage,
            rolling_win_rate=rolling_win_rate,
            trade_count=int(day_data["count"]),
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
        staled_token_addresses: set[str],
) -> AnalyticsResponse:
    logger.info("[ANALYTICS][AGGREGATION] Starting aggregation for %d records", len(records))

    kpis = compute_kpis(records)
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
