from __future__ import annotations

import statistics
from typing import Optional

from src.api.http.analytics_aggregation_service import METRIC_DEFINITIONS, MetricDefinition
from src.configuration.config import settings
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceMetricSnapshot, ShadowIntelligenceSnapshot
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.dao.trading.shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.db import get_database_session
from src.persistence.models import TradingShadowingVerdict

logger = get_application_logger(__name__)

DECILE_COUNT = 10


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

        metric_snapshots: list[ShadowIntelligenceMetricSnapshot] = []

        for metric_definition in METRIC_DEFINITIONS:
            metric_snapshot = _compute_metric_snapshot(metric_definition, resolved_verdicts)
            if metric_snapshot is not None:
                metric_snapshots.append(metric_snapshot)

        logger.info(
            "[TRADING][SHADOW][INTELLIGENCE] Shadow intelligence snapshot computed — %d outcomes analyzed, %d metrics profiled",
            total_outcomes, len(metric_snapshots),
        )

        return ShadowIntelligenceSnapshot(
            metric_snapshots=metric_snapshots,
            total_outcomes_analyzed=total_outcomes,
            is_activated=True,
            resolved_outcome_count=resolved_count,
            elapsed_hours=elapsed_hours,
        )


def _compute_metric_snapshot(
        metric_definition: MetricDefinition,
        resolved_verdicts: list[TradingShadowingVerdict],
) -> Optional[ShadowIntelligenceMetricSnapshot]:
    metric_values: list[float] = []
    pnl_values: list[float] = []
    is_winner_flags: list[bool] = []

    for verdict in resolved_verdicts:
        try:
            metric_value = metric_definition.accessor(verdict.probe)
        except Exception:
            continue

        if metric_value is None or not isinstance(metric_value, (int, float)):
            continue

        metric_values.append(float(metric_value))
        pnl_values.append(verdict.realized_pnl_percentage or 0.0)
        is_winner_flags.append(verdict.is_profitable or False)

    if len(metric_values) < DECILE_COUNT * 2:
        return None

    sorted_values = sorted(metric_values)
    sample_count = len(sorted_values)

    decile_edges: list[float] = []
    for decile_index in range(1, DECILE_COUNT):
        boundary_position = int(sample_count * decile_index / DECILE_COUNT)
        decile_edges.append(sorted_values[min(boundary_position, sample_count - 1)])

    decile_win_rates: list[float] = []
    decile_median_pnl: list[float] = []

    for bucket_index in range(DECILE_COUNT):
        lower_bound = decile_edges[bucket_index - 1] if bucket_index > 0 else float("-inf")
        upper_bound = decile_edges[bucket_index] if bucket_index < len(decile_edges) else float("inf")

        bucket_pnl: list[float] = []
        bucket_wins = 0
        bucket_total = 0

        for value_index in range(len(metric_values)):
            metric_value = metric_values[value_index]
            is_in_bucket = (metric_value > lower_bound) if bucket_index > 0 else (metric_value >= lower_bound)
            is_in_bucket = is_in_bucket and (metric_value <= upper_bound)

            if is_in_bucket:
                bucket_pnl.append(pnl_values[value_index])
                bucket_total += 1
                if is_winner_flags[value_index]:
                    bucket_wins += 1

        win_rate = (bucket_wins / bucket_total) if bucket_total > 0 else 0.0
        median_pnl = statistics.median(bucket_pnl) if bucket_pnl else 0.0

        decile_win_rates.append(win_rate)
        decile_median_pnl.append(median_pnl)

    max_win_rate = max(decile_win_rates) if decile_win_rates else 0.0
    min_win_rate = min(decile_win_rates) if decile_win_rates else 0.0
    influence_score = (max_win_rate - min_win_rate) * 100.0

    global_mean = statistics.fmean(metric_values) if metric_values else 0.0
    winner_values = [metric_values[index] for index in range(len(metric_values)) if is_winner_flags[index]]
    winner_mean = statistics.fmean(winner_values) if winner_values else global_mean

    standard_deviation = statistics.stdev(metric_values) if len(metric_values) > 1 else 1.0
    winner_deviation = ((winner_mean - global_mean) / standard_deviation) if standard_deviation > 0.0 else 0.0

    logger.debug(
        "[TRADING][SHADOW][INTELLIGENCE] Metric %s — influence=%.1f, win_rate_range=[%.2f, %.2f], winner_deviation=%.2f",
        metric_definition.key, influence_score, min_win_rate, max_win_rate, winner_deviation,
    )

    return ShadowIntelligenceMetricSnapshot(
        metric_key=metric_definition.key,
        decile_edges=decile_edges,
        decile_win_rates=decile_win_rates,
        decile_median_pnl=decile_median_pnl,
        influence_score=influence_score,
        winner_deviation=winner_deviation,
    )


def find_decile_index_for_value(value: float, decile_edges: list[float]) -> int:
    for edge_index, edge_value in enumerate(decile_edges):
        if value <= edge_value:
            return edge_index
    return len(decile_edges)
