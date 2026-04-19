from __future__ import annotations

from collections import defaultdict
from typing import Callable

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
from src.logging.logger import get_application_logger
from src.persistence.models import TradingEvaluation, TradingOutcome

logger = get_application_logger(__name__)

MINIMUM_POINTS_PER_BUCKET = 3
DECILE_COUNT = 10
ROLLING_WINDOW_SIZE = 50


class MetricDefinition:
    def __init__(self, key: str, label: str, accessor: Callable[[TradingEvaluation], float], unit: str) -> None:
        self.key = key
        self.label = label
        self.accessor = accessor
        self.unit = unit


METRIC_DEFINITIONS: list[MetricDefinition] = [
    MetricDefinition("final_score", "Final score", lambda evaluation: evaluation.final_score, "score"),
    MetricDefinition("quality_score", "Quality score", lambda evaluation: evaluation.quality_score, "score"),
    MetricDefinition("statistics_score", "Statistics score", lambda evaluation: evaluation.statistics_score, "score"),
    MetricDefinition("entry_score", "Entry score", lambda evaluation: evaluation.entry_score, "score"),
    MetricDefinition("liquidity_usd", "Liquidity ($)", lambda evaluation: evaluation.liquidity_usd, "usd"),
    MetricDefinition("market_cap_usd", "Market cap ($)", lambda evaluation: evaluation.market_cap_usd, "usd"),
    MetricDefinition("volume_m5_usd", "Volume 5m ($)", lambda evaluation: evaluation.volume_m5_usd, "usd"),
    MetricDefinition("volume_h1_usd", "Volume 1h ($)", lambda evaluation: evaluation.volume_h1_usd, "usd"),
    MetricDefinition("volume_h6_usd", "Volume 6h ($)", lambda evaluation: evaluation.volume_h6_usd, "usd"),
    MetricDefinition("volume_h24_usd", "Volume 24h ($)", lambda evaluation: evaluation.volume_h24_usd, "usd"),
    MetricDefinition("price_change_m5", "Δ5m (%)", lambda evaluation: evaluation.price_change_percentage_m5, "percent"),
    MetricDefinition("price_change_h1", "Δ1h (%)", lambda evaluation: evaluation.price_change_percentage_h1, "percent"),
    MetricDefinition("price_change_h6", "Δ6h (%)", lambda evaluation: evaluation.price_change_percentage_h6, "percent"),
    MetricDefinition("price_change_h24", "Δ24h (%)", lambda evaluation: evaluation.price_change_percentage_h24, "percent"),
    MetricDefinition("token_age_hours", "Token age (h)", lambda evaluation: evaluation.token_age_hours, "hours"),
    MetricDefinition("transaction_count_m5", "Transactions 5m", lambda evaluation: evaluation.transaction_count_m5, "count"),
    MetricDefinition("transaction_count_h1", "Transactions 1h", lambda evaluation: evaluation.transaction_count_h1, "count"),
    MetricDefinition("transaction_count_h6", "Transactions 6h", lambda evaluation: evaluation.transaction_count_h6, "count"),
    MetricDefinition("transaction_count_h24", "Transactions 24h", lambda evaluation: evaluation.transaction_count_h24, "count"),
    MetricDefinition("buy_to_sell_ratio", "Buy/Sell ratio", lambda evaluation: evaluation.buy_to_sell_ratio, "ratio"),
    MetricDefinition("fully_diluted_valuation_usd", "FDV ($)", lambda evaluation: evaluation.fully_diluted_valuation_usd, "usd"),
]


def _quantile(sorted_values: list[float], quantile_fraction: float) -> float:
    length = len(sorted_values)
    if length == 0:
        return 0.0
    position = (length - 1) * quantile_fraction
    base_index = int(position)
    remainder = position - base_index
    lower_value = sorted_values[base_index]
    upper_value = sorted_values[min(base_index + 1, length - 1)]
    return lower_value + (upper_value - lower_value) * remainder


def _compute_decile_edges(values: list[float]) -> list[float]:
    sorted_values = sorted(values)
    edges: list[float] = []
    for decile_index in range(DECILE_COUNT + 1):
        edges.append(_quantile(sorted_values, decile_index / DECILE_COUNT))
    return edges


def _assign_bucket_index(value: float, edges: list[float]) -> int:
    last_valid_bucket = len(edges) - 2
    for edge_index in range(len(edges) - 1):
        if edges[edge_index] <= value <= edges[edge_index + 1]:
            return min(edge_index, last_valid_bucket)
    return last_valid_bucket


def _format_metric_value(value: float, unit: str) -> str:
    if unit == "percent":
        return f"{value:.1f}%"
    if unit in ("usd", "count"):
        absolute_value = abs(value)
        if absolute_value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if absolute_value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:.0f}"
    if unit == "hours":
        return f"{value:.0f}h"
    if unit == "ratio":
        return f"{value:.2f}"
    if unit == "score":
        return f"{value:.0f}"
    return f"{value:.1f}"


def _aggregate_evaluation_outcomes(evaluation: TradingEvaluation) -> TradingOutcome | None:
    if not evaluation.outcomes:
        return None

    if len(evaluation.outcomes) == 1:
        return evaluation.outcomes[0]

    total_profit_and_loss_usd = sum(outcome.realized_profit_and_loss_usd for outcome in evaluation.outcomes)
    average_holding_duration_minutes = sum(outcome.holding_duration_minutes for outcome in evaluation.outcomes) / len(evaluation.outcomes)
    is_profitable = total_profit_and_loss_usd > 0

    cost_basis = evaluation.order_notional_value_usd
    if cost_basis and cost_basis > 0:
        total_profit_and_loss_percentage = (total_profit_and_loss_usd / cost_basis) * 100.0
    else:
        total_profit_and_loss_percentage = sum(outcome.realized_profit_and_loss_percentage for outcome in evaluation.outcomes) / len(evaluation.outcomes)

    last_outcome = evaluation.outcomes[-1]

    return TradingOutcome(
        realized_profit_and_loss_usd=total_profit_and_loss_usd,
        realized_profit_and_loss_percentage=total_profit_and_loss_percentage,
        holding_duration_minutes=average_holding_duration_minutes,
        is_profitable=is_profitable,
        exit_reason=last_outcome.exit_reason,
        occurred_at=last_outcome.occurred_at
    )


def compute_kpis(evaluations: list[TradingEvaluation]) -> AnalyticsKpiPayload:
    total_evaluations = len(evaluations)

    all_pnl_percentages: list[float] = []
    all_pnl_usd: list[float] = []
    all_holding_durations: list[float] = []
    win_count = 0
    loss_count = 0
    gross_profit = 0.0
    gross_loss = 0.0

    for evaluation in evaluations:
        outcome = _aggregate_evaluation_outcomes(evaluation)
        if outcome is None:
            continue

        trade_pnl_usd = outcome.realized_profit_and_loss_usd
        all_pnl_percentages.append(outcome.realized_profit_and_loss_percentage)
        all_pnl_usd.append(trade_pnl_usd)
        all_holding_durations.append(outcome.holding_duration_minutes)
        if outcome.is_profitable:
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


def compute_pnl_drivers_heatmap(evaluations: list[TradingEvaluation]) -> list[AnalyticsHeatmapSeriesPayload]:
    closed_evaluations = [evaluation for evaluation in evaluations if _aggregate_evaluation_outcomes(evaluation) is not None]
    series_list: list[AnalyticsHeatmapSeriesPayload] = []

    for metric_definition in METRIC_DEFINITIONS:
        metric_values: list[float] = []
        pnl_values: list[float] = []
        is_profitable_flags: list[bool] = []

        for evaluation in closed_evaluations:
            metric_value = metric_definition.accessor(evaluation)
            outcome = _aggregate_evaluation_outcomes(evaluation)
            if outcome is not None:
                metric_values.append(metric_value)
                pnl_values.append(outcome.realized_profit_and_loss_percentage)
                is_profitable_flags.append(outcome.is_profitable)

        if len(metric_values) < MINIMUM_POINTS_PER_BUCKET:
            series_list.append(AnalyticsHeatmapSeriesPayload(metric_key=metric_definition.key, metric_label=metric_definition.label, cells=[]))
            continue

        edges = _compute_decile_edges(metric_values)
        buckets: list[list[float]] = [[] for _ in range(len(edges) - 1)]
        counts: list[int] = [0 for _ in range(len(edges) - 1)]
        win_counts: list[int] = [0 for _ in range(len(edges) - 1)]

        for index in range(len(metric_values)):
            bucket_index = _assign_bucket_index(metric_values[index], edges)
            buckets[bucket_index].append(pnl_values[index])
            counts[bucket_index] += 1
            if is_profitable_flags[index]:
                win_counts[bucket_index] += 1

        cells: list[AnalyticsHeatmapCellPayload] = []
        medians: list[float] = []

        for bucket_index in range(len(buckets)):
            left_edge = edges[bucket_index]
            right_edge = edges[bucket_index + 1]
            range_label = f"{_format_metric_value(left_edge, metric_definition.unit)}–{_format_metric_value(right_edge, metric_definition.unit)}"

            bucket_data = buckets[bucket_index]
            if len(bucket_data) >= MINIMUM_POINTS_PER_BUCKET:
                sorted_data = sorted(bucket_data)
                median_value = _quantile(sorted_data, 0.5)
                mean_value = sum(sorted_data) / len(sorted_data)
                quartile_1_value = _quantile(sorted_data, 0.25)
                quartile_3_value = _quantile(sorted_data, 0.75)
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


def compute_staled_risk_heatmap(
        evaluations: list[TradingEvaluation],
        staled_token_addresses: set[str],
) -> list[AnalyticsHeatmapSeriesPayload]:
    series_list: list[AnalyticsHeatmapSeriesPayload] = []

    for metric_definition in METRIC_DEFINITIONS:
        metric_values: list[float] = []
        is_staled_flags: list[bool] = []

        for evaluation in evaluations:
            metric_value = metric_definition.accessor(evaluation)
            metric_values.append(metric_value)
            is_staled_flags.append(evaluation.token_address in staled_token_addresses)

        if len(metric_values) < MINIMUM_POINTS_PER_BUCKET:
            series_list.append(AnalyticsHeatmapSeriesPayload(metric_key=metric_definition.key, metric_label=metric_definition.label, cells=[]))
            continue

        edges = _compute_decile_edges(metric_values)
        counts: list[int] = [0 for _ in range(len(edges) - 1)]
        staled_counts: list[int] = [0 for _ in range(len(edges) - 1)]

        for index in range(len(metric_values)):
            bucket_index = _assign_bucket_index(metric_values[index], edges)
            counts[bucket_index] += 1
            if is_staled_flags[index]:
                staled_counts[bucket_index] += 1

        cells: list[AnalyticsHeatmapCellPayload] = []
        staled_rates: list[float] = []

        for bucket_index in range(len(counts)):
            left_edge = edges[bucket_index]
            right_edge = edges[bucket_index + 1]
            range_label = f"{_format_metric_value(left_edge, metric_definition.unit)}–{_format_metric_value(right_edge, metric_definition.unit)}"
            staled_rate = (staled_counts[bucket_index] / counts[bucket_index] * 100.0) if counts[bucket_index] > 0 else 0.0
            staled_rates.append(staled_rate)

            cells.append(AnalyticsHeatmapCellPayload(
                range_label=range_label,
                range_min=left_edge,
                range_max=right_edge,
                median_pnl=staled_rate,
                mean_pnl=staled_rate,
                quartile_1_pnl=0.0,
                quartile_3_pnl=0.0,
                sample_count=counts[bucket_index],
                win_count=0,
                win_rate_percentage=0.0,
                is_optimal=False,
            ))

        if staled_rates:
            maximum_rate = max(staled_rates)
            worst_threshold = maximum_rate * 0.9
            for cell_index, cell in enumerate(cells):
                if staled_rates[cell_index] >= worst_threshold and counts[cell_index] >= MINIMUM_POINTS_PER_BUCKET:
                    cell.is_optimal = True

        series_list.append(AnalyticsHeatmapSeriesPayload(metric_key=metric_definition.key, metric_label=metric_definition.label, cells=cells))

    logger.info("[ANALYTICS][AGGREGATION][HEATMAP][STALED_RISK] Computed %d metric series for staled risk", len(series_list))
    return series_list


def compute_timeline(evaluations: list[TradingEvaluation]) -> list[AnalyticsTimelinePointPayload]:
    outcome_events: list[tuple[str, float, float, bool]] = []

    for evaluation in evaluations:
        outcome = _aggregate_evaluation_outcomes(evaluation)
        if outcome is None:
            continue
        date_key = format_datetime_to_local_iso(outcome.occurred_at)[:10]
        outcome_events.append((date_key, outcome.realized_profit_and_loss_usd, outcome.realized_profit_and_loss_percentage, outcome.is_profitable))

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


def compute_scatter_series(evaluations: list[TradingEvaluation]) -> list[AnalyticsScatterSeriesPayload]:
    closed_evaluations = [evaluation for evaluation in evaluations if _aggregate_evaluation_outcomes(evaluation) is not None]

    max_scatter_points = 500
    if len(closed_evaluations) > max_scatter_points:
        step = len(closed_evaluations) / max_scatter_points
        sampled_evaluations = [closed_evaluations[int(i * step)] for i in range(max_scatter_points)]
    else:
        sampled_evaluations = closed_evaluations

    scatter_series_list: list[AnalyticsScatterSeriesPayload] = []

    for metric_definition in METRIC_DEFINITIONS:
        points: list[AnalyticsScatterPointPayload] = []

        for evaluation in sampled_evaluations:
            outcome = _aggregate_evaluation_outcomes(evaluation)
            if outcome is None:
                continue

            metric_value = metric_definition.accessor(evaluation)
            points.append(AnalyticsScatterPointPayload(
                metric_value=metric_value,
                pnl_percentage=outcome.realized_profit_and_loss_percentage,
                pnl_usd=outcome.realized_profit_and_loss_usd,
                token_symbol=evaluation.token_symbol,
                exit_reason=outcome.exit_reason,
            ))

        scatter_series_list.append(AnalyticsScatterSeriesPayload(
            metric_key=metric_definition.key,
            metric_label=metric_definition.label,
            points=points,
        ))

    logger.info("[ANALYTICS][AGGREGATION][SCATTER] Computed scatter series for %d metrics with %d closed evaluations", len(scatter_series_list), len(closed_evaluations))
    return scatter_series_list


def build_analytics_response(
        evaluations: list[TradingEvaluation],
        staled_token_addresses: set[str],
) -> AnalyticsResponse:
    logger.info("[ANALYTICS][AGGREGATION] Starting aggregation for %d evaluations", len(evaluations))

    kpis = compute_kpis(evaluations)
    pnl_drivers_series = compute_pnl_drivers_heatmap(evaluations)
    staled_risk_series = compute_staled_risk_heatmap(evaluations, staled_token_addresses)
    timeline = compute_timeline(evaluations)
    scatter_series = compute_scatter_series(evaluations)

    logger.info("[ANALYTICS][AGGREGATION] Aggregation complete")
    return AnalyticsResponse(
        kpis=kpis,
        pnl_drivers_series=pnl_drivers_series,
        staled_risk_series=staled_risk_series,
        timeline=timeline,
        scatter_series=scatter_series,
    )
