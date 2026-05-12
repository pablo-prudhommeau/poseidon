from __future__ import annotations

import argparse
import csv
import logging
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
SWEEP_LOG_DIR = SCRIPTS_DIR / "logs"
SWEEP_CSV_DIR = SCRIPTS_DIR / "csv"
BACKEND_PACKAGE_ROOT = ROOT / "backend"
if str(BACKEND_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_PACKAGE_ROOT))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
else:
    load_dotenv(ROOT / ".env")

from pydantic import BaseModel, ConfigDict


class ShadowVerdictMaterializedSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolved_at: datetime | None
    realized_profit_and_loss_usd: float | None
    is_profitable: bool | None


class ProfitFactorSweepMatrixRow(BaseModel):
    """Five verdict metrics per SMA regime (above / below threshold), five chart-side SMA metrics, deltas."""

    model_config = ConfigDict(frozen=True)

    lookback_days: float
    bucket_seconds: int
    sma_period: int
    pf_threshold: float
    winsorize: bool
    sparse_buckets: int
    verdicts_above: int
    verdicts_below: int
    avg_pnl_above_usd: float
    avg_pnl_below_usd: float
    win_rate_above: float
    win_rate_below: float
    empirical_pf_above: float
    empirical_pf_below: float
    velocity_above_per_day: float
    velocity_below_per_day: float
    payoff_ratio_above: float
    payoff_ratio_below: float
    sma_series_mean: float
    sma_series_std: float
    sma_time_fraction_above_threshold: float
    raw_pf_mean_when_sma_above_threshold: float
    raw_pf_mean_when_sma_at_or_below_threshold: float
    avg_pnl_delta_usd: float
    win_rate_delta: float
    empirical_pf_delta: float
    velocity_delta_per_day: float
    payoff_ratio_delta: float


from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_intelligence_service import (
    _simple_moving_average_like_shadow_verdict_chronicle_chart,
    _winsorize_series_like_shadow_verdict_chronicle_chart,
)
from src.core.trading.shadowing.trading_shadowing_service import (
    _chronicle_display_lag_timedelta,
    _compute_profit_factor,
    _floor_datetime_to_granularity,
    _series_end_datetime,
)
from src.core.utils.date_utils import ensure_timezone_aware, get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.db import get_database_session

logger = get_application_logger(__name__)

if not logging.root.handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def render_matrix_cell_for_fixed_width_table(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        return f"{value:.6f}"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def format_profit_factor_sweep_matrix_as_padded_text_lines(
        printable_rows: list[ProfitFactorSweepMatrixRow],
) -> list[str]:
    if not printable_rows:
        return []
    column_keys = list(ProfitFactorSweepMatrixRow.model_fields.keys())
    body_lines: list[list[str]] = []
    for matrix_row in printable_rows:
        body_lines.append(
            [render_matrix_cell_for_fixed_width_table(getattr(matrix_row, key)) for key in column_keys]
        )
    header_line = list(column_keys)
    table = [header_line] + body_lines
    column_count = len(column_keys)
    column_widths = [
        max(len(table[row_index][column_index]) for row_index in range(len(table)))
        for column_index in range(column_count)
    ]
    padded_lines: list[str] = []
    for table_row in table:
        padded_lines.append(
            "  ".join(
                table_row[column_index].ljust(column_widths[column_index])
                for column_index in range(column_count)
            )
        )
    return padded_lines


def materialize_shadow_verdict_rows(orm_verdicts: list) -> list[ShadowVerdictMaterializedSnapshot]:
    materialized_rows: list[ShadowVerdictMaterializedSnapshot] = []
    for verdict in orm_verdicts:
        resolved_at = ensure_timezone_aware(verdict.resolved_at)
        profit_and_loss_usd = verdict.realized_pnl_usd
        materialized_rows.append(
            ShadowVerdictMaterializedSnapshot(
                resolved_at=resolved_at,
                realized_profit_and_loss_usd=float(profit_and_loss_usd)
                if profit_and_loss_usd is not None
                else None,
                is_profitable=verdict.is_profitable,
            )
        )
    return materialized_rows


def compute_bucket_gross_profit_and_loss_usd(
        verdicts_in_bucket: list[ShadowVerdictMaterializedSnapshot],
) -> tuple[float, float]:
    profit_and_loss_values = [
        row.realized_profit_and_loss_usd
        for row in verdicts_in_bucket
        if row.realized_profit_and_loss_usd is not None
    ]
    gross_profit_usd = sum(value for value in profit_and_loss_values if value > 0.0)
    gross_loss_usd = abs(sum(value for value in profit_and_loss_values if value < 0.0))
    return gross_profit_usd, gross_loss_usd


def build_sparse_profit_factor_series_for_chronicle_window(
        verdict_rows: list[ShadowVerdictMaterializedSnapshot],
        *,
        series_end: datetime,
        lookback: timedelta,
        granularity_seconds: int,
        trailing_bucket_count: int,
        retention_days: int,
) -> tuple[list[float], list[datetime]]:
    chronicle_lag_timedelta = _chronicle_display_lag_timedelta()
    global_lower_bound_datetime = series_end - timedelta(days=retention_days)
    bucket_lower_bound_datetime = max(
        global_lower_bound_datetime,
        series_end - lookback - chronicle_lag_timedelta,
    )
    bucket_upper_bound_datetime = series_end + timedelta(
        seconds=granularity_seconds * max(0, trailing_bucket_count)
    )

    verdicts_by_bucket_start: defaultdict = defaultdict(list)
    for verdict_row in verdict_rows:
        when_resolved = verdict_row.resolved_at
        if when_resolved is None:
            continue
        if when_resolved < bucket_lower_bound_datetime or when_resolved > bucket_upper_bound_datetime:
            continue
        if verdict_row.realized_profit_and_loss_usd is None:
            continue
        bucket_start = _floor_datetime_to_granularity(when_resolved, granularity_seconds)
        verdicts_by_bucket_start[bucket_start].append(verdict_row)

    ordered_bucket_starts = sorted(verdicts_by_bucket_start.keys())
    sparse_profit_factors: list[float] = []
    for bucket_start in ordered_bucket_starts:
        gross_profit_usd, gross_loss_usd = compute_bucket_gross_profit_and_loss_usd(
            verdicts_by_bucket_start[bucket_start]
        )
        sparse_profit_factors.append(_compute_profit_factor(gross_profit_usd, gross_loss_usd))
    return sparse_profit_factors, ordered_bucket_starts


def compute_simple_moving_average_line_over_sparse_profit_factors(
        sparse_profit_factors: list[float],
        *,
        simple_moving_average_period: int,
        winsorize_enabled: bool,
) -> list[float]:
    if winsorize_enabled:
        adjusted_series = _winsorize_series_like_shadow_verdict_chronicle_chart(sparse_profit_factors)
    else:
        adjusted_series = list(sparse_profit_factors)
    return _simple_moving_average_like_shadow_verdict_chronicle_chart(
        adjusted_series,
        simple_moving_average_period,
    )


def _payoff_ratio_from_signed_pnls(win_pnls: list[float], loss_pnls: list[float]) -> float:
    if not win_pnls or not loss_pnls:
        return math.nan
    average_win = sum(win_pnls) / len(win_pnls)
    average_loss = sum(abs(x) for x in loss_pnls) / len(loss_pnls)
    if average_loss <= 0.0:
        return math.nan
    return average_win / average_loss


@dataclass(frozen=True, slots=True)
class VerdictRegimePentaptych:
    verdict_count: int
    gross_profit_usd: float
    gross_loss_usd: float
    sum_pnl_usd: float
    wins: int
    losses: int
    win_pnls: list[float]
    loss_pnls: list[float]


def _finalize_regime_pentaptych(
        regime: VerdictRegimePentaptych,
        lookback_days: float,
) -> tuple[float, float, float, float, float]:
    count = regime.verdict_count
    if count <= 0:
        nan5 = (math.nan,) * 5
        return nan5  # type: ignore[misc]
    average_pnl = regime.sum_pnl_usd / count
    win_rate = regime.wins / count
    empirical_pf = _compute_profit_factor(regime.gross_profit_usd, regime.gross_loss_usd)
    velocity_per_day = count / lookback_days if lookback_days > 0 else math.nan
    payoff_ratio = _payoff_ratio_from_signed_pnls(regime.win_pnls, regime.loss_pnls)
    return average_pnl, win_rate, empirical_pf, velocity_per_day, payoff_ratio


def aggregate_verdict_regime_pentaptychs(
        verdict_rows: list[ShadowVerdictMaterializedSnapshot],
        ordered_bucket_starts: list[datetime],
        simple_moving_average_profit_factor_per_bucket: list[float],
        granularity_seconds: int,
        profit_factor_simple_moving_average_threshold: float,
        lookback_days: float,
) -> tuple[VerdictRegimePentaptych, VerdictRegimePentaptych]:
    bucket_start_to_simple_moving_average: dict[datetime, float] = {
        ordered_bucket_starts[index]: simple_moving_average_profit_factor_per_bucket[index]
        for index in range(len(ordered_bucket_starts))
    }

    gross_profit_above = 0.0
    gross_loss_above = 0.0
    gross_profit_below = 0.0
    gross_loss_below = 0.0
    sum_pnl_above = 0.0
    sum_pnl_below = 0.0
    wins_above = 0
    losses_above = 0
    wins_below = 0
    losses_below = 0
    win_pnls_above: list[float] = []
    loss_pnls_above: list[float] = []
    win_pnls_below: list[float] = []
    loss_pnls_below: list[float] = []

    for verdict_row in verdict_rows:
        when_resolved = verdict_row.resolved_at
        if when_resolved is None or verdict_row.realized_profit_and_loss_usd is None:
            continue
        bucket_start = _floor_datetime_to_granularity(when_resolved, granularity_seconds)
        if bucket_start not in bucket_start_to_simple_moving_average:
            continue
        simple_moving_average_profit_factor = bucket_start_to_simple_moving_average[bucket_start]
        profit_and_loss_usd = verdict_row.realized_profit_and_loss_usd
        is_winning_verdict = bool(verdict_row.is_profitable)

        if simple_moving_average_profit_factor > profit_factor_simple_moving_average_threshold:
            sum_pnl_above += profit_and_loss_usd
            if profit_and_loss_usd > 0.0:
                gross_profit_above += profit_and_loss_usd
                win_pnls_above.append(profit_and_loss_usd)
            elif profit_and_loss_usd < 0.0:
                gross_loss_above += abs(profit_and_loss_usd)
                loss_pnls_above.append(profit_and_loss_usd)
            if is_winning_verdict:
                wins_above += 1
            else:
                losses_above += 1
        else:
            sum_pnl_below += profit_and_loss_usd
            if profit_and_loss_usd > 0.0:
                gross_profit_below += profit_and_loss_usd
                win_pnls_below.append(profit_and_loss_usd)
            elif profit_and_loss_usd < 0.0:
                gross_loss_below += abs(profit_and_loss_usd)
                loss_pnls_below.append(profit_and_loss_usd)
            if is_winning_verdict:
                wins_below += 1
            else:
                losses_below += 1

    count_above = wins_above + losses_above
    count_below = wins_below + losses_below

    regime_above = VerdictRegimePentaptych(
        verdict_count=count_above,
        gross_profit_usd=gross_profit_above,
        gross_loss_usd=gross_loss_above,
        sum_pnl_usd=sum_pnl_above,
        wins=wins_above,
        losses=losses_above,
        win_pnls=win_pnls_above,
        loss_pnls=loss_pnls_above,
    )
    regime_below = VerdictRegimePentaptych(
        verdict_count=count_below,
        gross_profit_usd=gross_profit_below,
        gross_loss_usd=gross_loss_below,
        sum_pnl_usd=sum_pnl_below,
        wins=wins_below,
        losses=losses_below,
        win_pnls=win_pnls_below,
        loss_pnls=loss_pnls_below,
    )
    return regime_above, regime_below


def compute_chart_side_pentaptych_metrics(
        sparse_profit_factors: list[float],
        simple_moving_average_line: list[float],
        profit_factor_simple_moving_average_threshold: float,
) -> tuple[float, float, float, float, float]:
    bucket_count = len(simple_moving_average_line)
    if bucket_count == 0 or len(sparse_profit_factors) != bucket_count:
        return (math.nan, math.nan, math.nan, math.nan, math.nan)
    sma_mean = statistics.mean(simple_moving_average_line)
    sma_std = statistics.pstdev(simple_moving_average_line) if bucket_count > 1 else 0.0
    indices_above_threshold = [
        index
        for index in range(bucket_count)
        if simple_moving_average_line[index] > profit_factor_simple_moving_average_threshold
    ]
    indices_at_or_below_threshold = [
        index
        for index in range(bucket_count)
        if simple_moving_average_line[index] <= profit_factor_simple_moving_average_threshold
    ]
    fraction_time_above_threshold = len(indices_above_threshold) / float(bucket_count)
    raw_pf_when_above_list = [sparse_profit_factors[i] for i in indices_above_threshold]
    raw_pf_when_below_list = [sparse_profit_factors[i] for i in indices_at_or_below_threshold]
    raw_pf_mean_when_sma_above = (
        statistics.mean(raw_pf_when_above_list) if raw_pf_when_above_list else math.nan
    )
    raw_pf_mean_when_sma_below = (
        statistics.mean(raw_pf_when_below_list) if raw_pf_when_below_list else math.nan
    )
    return (
        sma_mean,
        sma_std,
        fraction_time_above_threshold,
        raw_pf_mean_when_sma_above,
        raw_pf_mean_when_sma_below,
    )


def _nan_fallback(value: float, fallback: float) -> float:
    return fallback if math.isnan(value) else value


def sweep_row_sort_key(
        row: ProfitFactorSweepMatrixRow,
        rank_by: str,
) -> tuple[float, ...]:
    verdicts = row.verdicts_above
    if rank_by == "avg_pnl_delta":
        primary = _nan_fallback(row.avg_pnl_delta_usd, -999.0)
        return (primary, row.win_rate_delta if not math.isnan(row.win_rate_delta) else -1.0, verdicts)
    if rank_by == "empirical_pf_delta":
        primary = _nan_fallback(row.empirical_pf_delta, -999.0)
        return (primary, row.avg_pnl_delta_usd if not math.isnan(row.avg_pnl_delta_usd) else -999.0, verdicts)
    if rank_by == "payoff_ratio_delta":
        primary = _nan_fallback(row.payoff_ratio_delta, -999.0)
        return (primary, row.win_rate_delta if not math.isnan(row.win_rate_delta) else -1.0, verdicts)
    if rank_by == "velocity_above":
        primary = _nan_fallback(row.velocity_above_per_day, -1.0)
        return (primary, row.win_rate_delta if not math.isnan(row.win_rate_delta) else -1.0, verdicts)
    if rank_by == "composite":
        return (
            _nan_fallback(row.win_rate_delta, -999.0),
            _nan_fallback(row.avg_pnl_delta_usd, -999.0),
            _nan_fallback(row.velocity_above_per_day, -1.0),
            verdicts,
        )
    primary = _nan_fallback(row.win_rate_delta, -999.0)
    win_rate_above = row.win_rate_above if not math.isnan(row.win_rate_above) else -1.0
    return (primary, win_rate_above, verdicts)


def make_sort_key(rank_by: str) -> Callable[[ProfitFactorSweepMatrixRow], tuple[float, ...]]:
    return lambda row: sweep_row_sort_key(row, rank_by)


def run_profit_factor_parameter_sweep(
        *,
        lookbacks_days: list[float],
        granularities_seconds: list[int],
        simple_moving_average_periods: list[int],
        profit_factor_simple_moving_average_thresholds: list[float],
        winsorize_enabled: bool,
        minimum_verdict_count_in_above_threshold_regime: int,
        minimum_verdict_count_in_below_threshold_regime: int,
        rank_by: str,
        csv_output_path: Path | None,
) -> None:
    current_time = get_current_local_datetime()
    series_end = _series_end_datetime(current_time)
    chronicle_lag_timedelta = _chronicle_display_lag_timedelta()
    trailing_bucket_count = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS
    retention_days = settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS

    maximum_lookback_timedelta = timedelta(days=max(lookbacks_days))
    maximum_granularity_seconds = max(granularities_seconds)
    fetch_upper_bound = series_end + timedelta(
        seconds=maximum_granularity_seconds * max(0, trailing_bucket_count)
    )
    fetch_lower_bound = series_end - maximum_lookback_timedelta - chronicle_lag_timedelta - timedelta(
        minutes=5
    )
    retention_lower_floor = series_end - timedelta(days=retention_days)
    fetch_lower_bound = min(fetch_lower_bound, retention_lower_floor)

    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        orm_verdicts = verdict_dao.retrieve_resolved_in_window(
            start_datetime=fetch_lower_bound,
            end_datetime=fetch_upper_bound,
            limit_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
        )
        verdict_rows = materialize_shadow_verdict_rows(orm_verdicts)

    logger.info(
        "[SCRIPT][SHADOW][PF_SWEEP] Loaded verdict materialized snapshots — series_end=%s count=%d",
        series_end.isoformat(),
        len(verdict_rows),
    )

    sweep_rows: list[ProfitFactorSweepMatrixRow] = []

    for lookback_days in lookbacks_days:
        lookback_timedelta = timedelta(days=lookback_days)
        for granularity_seconds in granularities_seconds:
            sparse_profit_factors, ordered_bucket_starts = (
                build_sparse_profit_factor_series_for_chronicle_window(
                    verdict_rows,
                    series_end=series_end,
                    lookback=lookback_timedelta,
                    granularity_seconds=granularity_seconds,
                    trailing_bucket_count=trailing_bucket_count,
                    retention_days=retention_days,
                )
            )
            if len(sparse_profit_factors) < 2:
                logger.debug(
                    "[SCRIPT][SHADOW][PF_SWEEP] Skipped sparse series — lookback_days=%s granularity_seconds=%s "
                    "sparse_bucket_count=%d",
                    lookback_days,
                    granularity_seconds,
                    len(sparse_profit_factors),
                )
                continue

            for simple_moving_average_period in simple_moving_average_periods:
                simple_moving_average_line = compute_simple_moving_average_line_over_sparse_profit_factors(
                    sparse_profit_factors,
                    simple_moving_average_period=max(1, simple_moving_average_period),
                    winsorize_enabled=winsorize_enabled,
                )
                if len(simple_moving_average_line) != len(ordered_bucket_starts):
                    continue

                for threshold in profit_factor_simple_moving_average_thresholds:
                    regime_above, regime_below = aggregate_verdict_regime_pentaptychs(
                        verdict_rows,
                        ordered_bucket_starts,
                        simple_moving_average_line,
                        granularity_seconds,
                        threshold,
                        lookback_days,
                    )
                    (
                        avg_pnl_above,
                        win_rate_above,
                        empirical_pf_above,
                        velocity_above_per_day,
                        payoff_ratio_above,
                    ) = _finalize_regime_pentaptych(regime_above, lookback_days)
                    (
                        avg_pnl_below,
                        win_rate_below,
                        empirical_pf_below,
                        velocity_below_per_day,
                        payoff_ratio_below,
                    ) = _finalize_regime_pentaptych(regime_below, lookback_days)

                    (
                        sma_series_mean,
                        sma_series_std,
                        sma_time_fraction_above_threshold,
                        raw_pf_mean_when_sma_above_threshold,
                        raw_pf_mean_when_sma_at_or_below_threshold,
                    ) = compute_chart_side_pentaptych_metrics(
                        sparse_profit_factors,
                        simple_moving_average_line,
                        threshold,
                    )

                    avg_pnl_delta_usd = (
                        avg_pnl_above - avg_pnl_below
                        if not math.isnan(avg_pnl_above) and not math.isnan(avg_pnl_below)
                        else math.nan
                    )
                    win_rate_delta = (
                        win_rate_above - win_rate_below
                        if not math.isnan(win_rate_above) and not math.isnan(win_rate_below)
                        else math.nan
                    )
                    empirical_pf_delta = (
                        empirical_pf_above - empirical_pf_below
                        if not math.isnan(empirical_pf_above) and not math.isnan(empirical_pf_below)
                        else math.nan
                    )
                    velocity_delta_per_day = (
                        velocity_above_per_day - velocity_below_per_day
                        if not math.isnan(velocity_above_per_day) and not math.isnan(velocity_below_per_day)
                        else math.nan
                    )
                    payoff_ratio_delta = (
                        payoff_ratio_above - payoff_ratio_below
                        if not math.isnan(payoff_ratio_above) and not math.isnan(payoff_ratio_below)
                        else math.nan
                    )

                    sweep_rows.append(
                        ProfitFactorSweepMatrixRow(
                            lookback_days=lookback_days,
                            bucket_seconds=granularity_seconds,
                            sma_period=simple_moving_average_period,
                            pf_threshold=threshold,
                            winsorize=winsorize_enabled,
                            sparse_buckets=len(ordered_bucket_starts),
                            verdicts_above=regime_above.verdict_count,
                            verdicts_below=regime_below.verdict_count,
                            avg_pnl_above_usd=avg_pnl_above,
                            avg_pnl_below_usd=avg_pnl_below,
                            win_rate_above=win_rate_above,
                            win_rate_below=win_rate_below,
                            empirical_pf_above=empirical_pf_above,
                            empirical_pf_below=empirical_pf_below,
                            velocity_above_per_day=velocity_above_per_day,
                            velocity_below_per_day=velocity_below_per_day,
                            payoff_ratio_above=payoff_ratio_above,
                            payoff_ratio_below=payoff_ratio_below,
                            sma_series_mean=sma_series_mean,
                            sma_series_std=sma_series_std,
                            sma_time_fraction_above_threshold=sma_time_fraction_above_threshold,
                            raw_pf_mean_when_sma_above_threshold=raw_pf_mean_when_sma_above_threshold,
                            raw_pf_mean_when_sma_at_or_below_threshold=(
                                raw_pf_mean_when_sma_at_or_below_threshold
                            ),
                            avg_pnl_delta_usd=avg_pnl_delta_usd,
                            win_rate_delta=win_rate_delta,
                            empirical_pf_delta=empirical_pf_delta,
                            velocity_delta_per_day=velocity_delta_per_day,
                            payoff_ratio_delta=payoff_ratio_delta,
                        )
                    )

    sweep_rows.sort(key=make_sort_key(rank_by), reverse=True)

    column_names = list(ProfitFactorSweepMatrixRow.model_fields.keys())

    printable_rows = [
        row
        for row in sweep_rows
        if row.verdicts_above >= minimum_verdict_count_in_above_threshold_regime
        and row.verdicts_below >= minimum_verdict_count_in_below_threshold_regime
    ]

    if csv_output_path is not None:
        csv_output_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=column_names)
            writer.writeheader()
            for row in printable_rows:
                writer.writerow(row.model_dump())

    logger.info(
        "[SCRIPT][SHADOW][PF_SWEEP] Sweep finished — printable_rows=%d total_rows=%d "
        "min_verdicts_above=%d min_verdicts_below=%d rank_by=%s",
        len(printable_rows),
        len(sweep_rows),
        minimum_verdict_count_in_above_threshold_regime,
        minimum_verdict_count_in_below_threshold_regime,
        rank_by,
    )

    logger.info(
        "[SCRIPT][SHADOW][PF_SWEEP] printable_rows=%d total_rows=%d "
        "(verdicts_above >= %d and verdicts_below >= %d)",
        len(printable_rows),
        len(sweep_rows),
        minimum_verdict_count_in_above_threshold_regime,
        minimum_verdict_count_in_below_threshold_regime,
    )

    table_lines = format_profit_factor_sweep_matrix_as_padded_text_lines(printable_rows[:80])
    if table_lines:
        logger.info("[SCRIPT][SHADOW][PF_SWEEP] Result matrix:")
        for table_line in table_lines:
            logger.info(table_line)

    if len(printable_rows) > 80:
        logger.info(
            "[SCRIPT][SHADOW][PF_SWEEP] ... %d additional rows not shown",
            len(printable_rows) - 80,
        )


def parse_comma_separated_floats(raw: str) -> list[float]:
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


def parse_comma_separated_integers(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def resolve_sweep_csv_output_path(raw: Path | None) -> Path | None:
    if raw is None:
        return None
    if raw.is_absolute():
        return raw
    if raw.parent == Path("."):
        return SWEEP_CSV_DIR / raw.name
    return (Path.cwd() / raw).resolve()


def attach_timestamped_sweep_log_file() -> Path:
    SWEEP_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file_path = SWEEP_LOG_DIR / (
        f"shadow_pf_sweetspot_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.root.addHandler(file_handler)
    logging.root.setLevel(logging.INFO)
    return log_file_path


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description="Profit factor simple moving average and lookback parameter sweep for shadow verdicts",
        epilog=(
            "Example runs:\n"
            "  Focus split signal — coarse sweep:\n"
            "    python scripts/shadow_pf_sweetspot_scan.py "
            "--lookbacks 7,14 --granularities 300,900 "
            "--sma-periods 50,100 --thresholds 1.35,1.45,1.55 "
            "--min-regime-n 30 --rank-by win_rate_delta\n"
            "  Max delta expectation vs baseline regime:\n"
            "    python scripts/shadow_pf_sweetspot_scan.py "
            "--lookbacks 14,21,30 --granularities 300 "
            "--sma-periods 30,50,80 --thresholds 1.2,1.35,1.5 "
            "--min-regime-n 40 --min-regime-below-n 40 "
            "--rank-by avg_pnl_delta --csv avg_pnl_delta.csv\n"
            "  Find throughput niches (velocity):\n"
            "    python scripts/shadow_pf_sweetspot_scan.py "
            "--lookbacks 7 --granularities 300,600 "
            "--sma-periods 40,60 --thresholds 1.4,1.45,1.5 "
            "--min-regime-n 25 --rank-by velocity_above\n"
            "  Chart-side SMA pentaptych tie-break with verdict deltas:\n"
            "    python scripts/shadow_pf_sweetspot_scan.py "
            "--lookbacks 14 --granularities 300 "
            "--sma-periods 50 --thresholds 1.35,1.4,1.45,1.5 "
            "--rank-by composite --no-winsorize\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    argument_parser.add_argument(
        "--lookbacks",
        default="7,14,30",
        help="Comma-separated lookback window lengths in days",
    )
    argument_parser.add_argument(
        "--granularities",
        default="300,900,1800",
        help="Comma-separated bucket widths in seconds",
    )
    argument_parser.add_argument(
        "--sma-periods",
        default="10,30,50,100,200",
        help="Comma-separated simple moving average periods",
    )
    argument_parser.add_argument(
        "--thresholds",
        default="1.2,1.35,1.45,1.5,1.6,1.75",
        help="Comma-separated profit factor SMA thresholds for regime split",
    )
    argument_parser.add_argument(
        "--no-winsorize",
        action="store_true",
        help="Disable winsorization before the simple moving average",
    )
    argument_parser.add_argument(
        "--min-regime-n",
        type=int,
        default=50,
        help="Minimum verdict count in the above-threshold regime for a row to be listed",
    )
    argument_parser.add_argument(
        "--min-regime-below-n",
        type=int,
        default=0,
        help="Minimum verdict count in the at-or-below-threshold regime (0 disables)",
    )
    argument_parser.add_argument(
        "--rank-by",
        choices=(
            "win_rate_delta",
            "avg_pnl_delta",
            "empirical_pf_delta",
            "payoff_ratio_delta",
            "velocity_above",
            "composite",
        ),
        default="win_rate_delta",
        help="Sort printable rows by this primary objective (see sweep_row_sort_key)",
    )
    argument_parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        dest="csv_output_path",
        help=(
            "CSV destination. A bare filename is written under scripts/csv/ "
            "(repository-relative convention); otherwise relative paths use cwd."
        ),
    )
    argument_parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Do not write a timestamped duplicate log under scripts/logs/",
    )
    parsed = argument_parser.parse_args()

    log_file_path: Path | None = None
    if not parsed.no_log_file:
        log_file_path = attach_timestamped_sweep_log_file()
        logger.info("[SCRIPT][SHADOW][PF_SWEEP] Writing log file to %s", log_file_path.as_posix())

    resolved_csv_path = resolve_sweep_csv_output_path(parsed.csv_output_path)

    try:
        run_profit_factor_parameter_sweep(
            lookbacks_days=parse_comma_separated_floats(parsed.lookbacks),
            granularities_seconds=parse_comma_separated_integers(parsed.granularities),
            simple_moving_average_periods=parse_comma_separated_integers(parsed.sma_periods),
            profit_factor_simple_moving_average_thresholds=parse_comma_separated_floats(parsed.thresholds),
            winsorize_enabled=not parsed.no_winsorize,
            minimum_verdict_count_in_above_threshold_regime=parsed.min_regime_n,
            minimum_verdict_count_in_below_threshold_regime=parsed.min_regime_below_n,
            rank_by=parsed.rank_by,
            csv_output_path=resolved_csv_path,
        )
    except Exception:
        logger.exception("[SCRIPT][SHADOW][PF_SWEEP] Profit factor parameter sweep terminated with error")
        raise


if __name__ == "__main__":
    main()
