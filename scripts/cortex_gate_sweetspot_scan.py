from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from typing import Callable

import numpy

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

from pydantic import BaseModel, ConfigDict, ValidationError
from src.configuration.config import settings
from src.core.trading.trading_structures import TradingCortexInferenceSnapshot
from src.core.utils.date_utils import ensure_timezone_aware, get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session

logger = get_application_logger(__name__)

if not logging.root.handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

NO_HOLD_CAP_SENTINEL_MINUTES = 100_000_000.0


class CortexGateSweepObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolved_at: datetime
    realized_profit_and_loss_usd: float
    is_profitable: bool
    success_probability: float
    toxicity_probability: float
    expected_profit_and_loss_percentage: float
    predicted_holding_time_minutes: float
    cortex_model_version: str


class CortexGateSweepMatrixRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    win_threshold: float
    toxicity_threshold: float
    max_hold_minutes: float
    expected_pnl_threshold: float
    accepted_count: int
    pass_rate_pct: float
    accepted_per_day: float
    win_rate_pct: float
    total_pnl_usd: float
    avg_pnl_usd: float
    empirical_pf: float
    payoff_ratio: float
    n_first_half: int
    pf_first_half: float
    win_rate_first_half_pct: float
    n_second_half: int
    pf_second_half: float
    win_rate_second_half_pct: float
    rejected_avg_pnl_usd: float
    rejected_win_rate_pct: float
    rejected_pf: float
    avg_pnl_delta_usd: float
    win_rate_delta_pct: float
    pf_delta: float


class CortexGateSweepObservationArrays(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    resolved_at_epoch_seconds: numpy.ndarray
    realized_profit_and_loss_usd: numpy.ndarray
    is_profitable: numpy.ndarray
    success_probability: numpy.ndarray
    toxicity_probability: numpy.ndarray
    expected_profit_and_loss_percentage: numpy.ndarray
    predicted_holding_time_minutes: numpy.ndarray
    window_start: datetime
    window_end: datetime
    halves_split_epoch_seconds: float


def load_shadowing_cortex_observations(
    lookback_days: float | None,
    max_fetch_count: int,
) -> list[CortexGateSweepObservation]:
    current_time = get_current_local_datetime()
    if lookback_days is not None:
        fetch_lower_bound = current_time - timedelta(days=lookback_days)
    else:
        fetch_lower_bound = current_time - timedelta(days=3650)

    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        orm_verdicts = verdict_dao.retrieve_resolved_in_window(
            start_datetime=fetch_lower_bound,
            end_datetime=current_time,
            limit_count=max_fetch_count,
        )

        observations: list[CortexGateSweepObservation] = []
        incomplete_inference_count = 0
        for verdict in orm_verdicts:
            resolved_at = ensure_timezone_aware(verdict.resolved_at)
            if resolved_at is None:
                continue
            if verdict.realized_pnl_usd is None or verdict.is_profitable is None:
                continue
            raw_summary = verdict.probe.cortex_inference_summary
            if raw_summary is None:
                incomplete_inference_count += 1
                continue
            try:
                inference_snapshot = TradingCortexInferenceSnapshot.model_validate(
                    raw_summary
                )
            except ValidationError:
                incomplete_inference_count += 1
                continue
            if (
                inference_snapshot.success_probability is None
                or inference_snapshot.toxicity_probability is None
                or inference_snapshot.expected_profit_and_loss_percentage is None
                or inference_snapshot.predicted_holding_time_minutes is None
            ):
                incomplete_inference_count += 1
                continue
            observations.append(
                CortexGateSweepObservation(
                    resolved_at=resolved_at,
                    realized_profit_and_loss_usd=float(verdict.realized_pnl_usd),
                    is_profitable=bool(verdict.is_profitable),
                    success_probability=float(inference_snapshot.success_probability),
                    toxicity_probability=float(inference_snapshot.toxicity_probability),
                    expected_profit_and_loss_percentage=float(
                        inference_snapshot.expected_profit_and_loss_percentage
                    ),
                    predicted_holding_time_minutes=float(
                        inference_snapshot.predicted_holding_time_minutes
                    ),
                    cortex_model_version=str(
                        inference_snapshot.model_version or "unknown"
                    ),
                )
            )

    logger.info(
        "[SCRIPT][CORTEX][GATE_SWEEP] Loaded shadowing observations — usable=%d incomplete_inference=%d fetched=%d",
        len(observations),
        incomplete_inference_count,
        len(orm_verdicts),
    )
    return observations


def load_paper_trade_cortex_observations() -> list[CortexGateSweepObservation]:
    from sqlalchemy import select
    from src.persistence.models import TradeSide, TradingEvaluation, TradingTrade

    with get_database_session() as database_session:
        sell_rows = database_session.execute(
            select(
                TradingTrade.evaluation_id,
                TradingTrade.realized_profit_and_loss,
                TradingTrade.created_at,
            )
            .where(TradingTrade.trade_side == TradeSide.SELL)
            .where(TradingTrade.realized_profit_and_loss.is_not(None))
        ).all()

        pnl_by_evaluation: dict[int, float] = {}
        closed_at_by_evaluation: dict[int, datetime] = {}
        for evaluation_id, realized_profit_and_loss, created_at in sell_rows:
            pnl_by_evaluation[evaluation_id] = pnl_by_evaluation.get(
                evaluation_id, 0.0
            ) + float(realized_profit_and_loss)
            aware_created_at = ensure_timezone_aware(created_at)
            if aware_created_at is None:
                continue
            previous_closed_at = closed_at_by_evaluation.get(evaluation_id)
            if previous_closed_at is None or aware_created_at > previous_closed_at:
                closed_at_by_evaluation[evaluation_id] = aware_created_at

        evaluation_rows = database_session.execute(
            select(
                TradingEvaluation.id, TradingEvaluation.cortex_inference_summary
            ).where(TradingEvaluation.id.in_(list(pnl_by_evaluation.keys())))
        ).all()

    observations: list[CortexGateSweepObservation] = []
    incomplete_inference_count = 0
    for evaluation_id, raw_summary in evaluation_rows:
        closed_at = closed_at_by_evaluation.get(evaluation_id)
        if closed_at is None or raw_summary is None:
            incomplete_inference_count += 1
            continue
        try:
            inference_snapshot = TradingCortexInferenceSnapshot.model_validate(
                raw_summary
            )
        except ValidationError:
            incomplete_inference_count += 1
            continue
        if (
            inference_snapshot.success_probability is None
            or inference_snapshot.toxicity_probability is None
            or inference_snapshot.expected_profit_and_loss_percentage is None
            or inference_snapshot.predicted_holding_time_minutes is None
        ):
            incomplete_inference_count += 1
            continue
        position_pnl_usd = pnl_by_evaluation[evaluation_id]
        observations.append(
            CortexGateSweepObservation(
                resolved_at=closed_at,
                realized_profit_and_loss_usd=position_pnl_usd,
                is_profitable=position_pnl_usd > 0.0,
                success_probability=float(inference_snapshot.success_probability),
                toxicity_probability=float(inference_snapshot.toxicity_probability),
                expected_profit_and_loss_percentage=float(
                    inference_snapshot.expected_profit_and_loss_percentage
                ),
                predicted_holding_time_minutes=float(
                    inference_snapshot.predicted_holding_time_minutes
                ),
                cortex_model_version=str(inference_snapshot.model_version or "unknown"),
            )
        )

    logger.info(
        "[SCRIPT][CORTEX][GATE_SWEEP] Loaded paper trade observations — usable=%d incomplete_inference=%d",
        len(observations),
        incomplete_inference_count,
    )
    return observations


def build_observation_arrays(
    observations: list[CortexGateSweepObservation],
) -> CortexGateSweepObservationArrays:
    resolved_epoch_seconds = numpy.asarray(
        [observation.resolved_at.timestamp() for observation in observations],
        dtype=numpy.float64,
    )
    window_start = min(observation.resolved_at for observation in observations)
    window_end = max(observation.resolved_at for observation in observations)
    halves_split_epoch_seconds = (
        window_start.timestamp() + window_end.timestamp()
    ) / 2.0
    return CortexGateSweepObservationArrays(
        resolved_at_epoch_seconds=resolved_epoch_seconds,
        realized_profit_and_loss_usd=numpy.asarray(
            [observation.realized_profit_and_loss_usd for observation in observations],
            dtype=numpy.float64,
        ),
        is_profitable=numpy.asarray(
            [observation.is_profitable for observation in observations],
            dtype=bool,
        ),
        success_probability=numpy.asarray(
            [observation.success_probability for observation in observations],
            dtype=numpy.float64,
        ),
        toxicity_probability=numpy.asarray(
            [observation.toxicity_probability for observation in observations],
            dtype=numpy.float64,
        ),
        expected_profit_and_loss_percentage=numpy.asarray(
            [
                observation.expected_profit_and_loss_percentage
                for observation in observations
            ],
            dtype=numpy.float64,
        ),
        predicted_holding_time_minutes=numpy.asarray(
            [
                observation.predicted_holding_time_minutes
                for observation in observations
            ],
            dtype=numpy.float64,
        ),
        window_start=window_start,
        window_end=window_end,
        halves_split_epoch_seconds=halves_split_epoch_seconds,
    )


def compute_empirical_profit_factor(pnl_values: numpy.ndarray) -> float:
    gross_profit = float(pnl_values[pnl_values > 0.0].sum())
    gross_loss = float(abs(pnl_values[pnl_values < 0.0].sum()))
    if gross_loss <= 0.0:
        return math.nan if gross_profit <= 0.0 else math.inf
    return gross_profit / gross_loss


def compute_payoff_ratio(pnl_values: numpy.ndarray) -> float:
    winning_pnls = pnl_values[pnl_values > 0.0]
    losing_pnls = pnl_values[pnl_values < 0.0]
    if winning_pnls.size == 0 or losing_pnls.size == 0:
        return math.nan
    average_win = float(winning_pnls.mean())
    average_loss = float(abs(losing_pnls.mean()))
    if average_loss <= 0.0:
        return math.nan
    return average_win / average_loss


def compute_win_rate_percentage(is_profitable_values: numpy.ndarray) -> float:
    if is_profitable_values.size == 0:
        return math.nan
    return float(is_profitable_values.mean()) * 100.0


def build_sweep_matrix_row(
    observation_arrays: CortexGateSweepObservationArrays,
    acceptance_mask: numpy.ndarray,
    win_threshold: float,
    toxicity_threshold: float,
    max_hold_minutes: float,
    expected_pnl_threshold: float,
    window_days: float,
) -> CortexGateSweepMatrixRow | None:
    accepted_count = int(acceptance_mask.sum())
    if accepted_count == 0:
        return None

    total_count = acceptance_mask.size
    accepted_pnls = observation_arrays.realized_profit_and_loss_usd[acceptance_mask]
    accepted_outcomes = observation_arrays.is_profitable[acceptance_mask]
    rejected_pnls = observation_arrays.realized_profit_and_loss_usd[~acceptance_mask]
    rejected_outcomes = observation_arrays.is_profitable[~acceptance_mask]

    first_half_mask = acceptance_mask & (
        observation_arrays.resolved_at_epoch_seconds
        < observation_arrays.halves_split_epoch_seconds
    )
    second_half_mask = acceptance_mask & (
        observation_arrays.resolved_at_epoch_seconds
        >= observation_arrays.halves_split_epoch_seconds
    )
    first_half_pnls = observation_arrays.realized_profit_and_loss_usd[first_half_mask]
    second_half_pnls = observation_arrays.realized_profit_and_loss_usd[second_half_mask]

    win_rate_pct = compute_win_rate_percentage(accepted_outcomes)
    rejected_win_rate_pct = compute_win_rate_percentage(rejected_outcomes)
    empirical_pf = compute_empirical_profit_factor(accepted_pnls)
    rejected_pf = (
        compute_empirical_profit_factor(rejected_pnls)
        if rejected_pnls.size > 0
        else math.nan
    )
    avg_pnl_usd = float(accepted_pnls.mean())
    rejected_avg_pnl_usd = (
        float(rejected_pnls.mean()) if rejected_pnls.size > 0 else math.nan
    )

    return CortexGateSweepMatrixRow(
        win_threshold=win_threshold,
        toxicity_threshold=toxicity_threshold,
        max_hold_minutes=max_hold_minutes,
        expected_pnl_threshold=expected_pnl_threshold,
        accepted_count=accepted_count,
        pass_rate_pct=accepted_count / total_count * 100.0,
        accepted_per_day=accepted_count / window_days if window_days > 0 else math.nan,
        win_rate_pct=win_rate_pct,
        total_pnl_usd=float(accepted_pnls.sum()),
        avg_pnl_usd=avg_pnl_usd,
        empirical_pf=empirical_pf,
        payoff_ratio=compute_payoff_ratio(accepted_pnls),
        n_first_half=int(first_half_mask.sum()),
        pf_first_half=compute_empirical_profit_factor(first_half_pnls)
        if first_half_pnls.size > 0
        else math.nan,
        win_rate_first_half_pct=compute_win_rate_percentage(
            observation_arrays.is_profitable[first_half_mask]
        ),
        n_second_half=int(second_half_mask.sum()),
        pf_second_half=compute_empirical_profit_factor(second_half_pnls)
        if second_half_pnls.size > 0
        else math.nan,
        win_rate_second_half_pct=compute_win_rate_percentage(
            observation_arrays.is_profitable[second_half_mask]
        ),
        rejected_avg_pnl_usd=rejected_avg_pnl_usd,
        rejected_win_rate_pct=rejected_win_rate_pct,
        rejected_pf=rejected_pf,
        avg_pnl_delta_usd=avg_pnl_usd - rejected_avg_pnl_usd
        if not math.isnan(rejected_avg_pnl_usd)
        else math.nan,
        win_rate_delta_pct=(
            win_rate_pct - rejected_win_rate_pct
            if not math.isnan(win_rate_pct) and not math.isnan(rejected_win_rate_pct)
            else math.nan
        ),
        pf_delta=(
            empirical_pf - rejected_pf
            if not math.isnan(empirical_pf)
            and not math.isnan(rejected_pf)
            and not math.isinf(empirical_pf)
            and not math.isinf(rejected_pf)
            else math.nan
        ),
    )


def run_cortex_gate_threshold_sweep(
    observation_arrays: CortexGateSweepObservationArrays,
    win_thresholds: list[float],
    toxicity_thresholds: list[float],
    max_hold_minutes_values: list[float],
    expected_pnl_thresholds: list[float],
) -> list[CortexGateSweepMatrixRow]:
    window_days = (
        observation_arrays.window_end - observation_arrays.window_start
    ).total_seconds() / 86400.0

    sweep_rows: list[CortexGateSweepMatrixRow] = []
    for (
        win_threshold,
        toxicity_threshold,
        max_hold_minutes,
        expected_pnl_threshold,
    ) in product(
        win_thresholds,
        toxicity_thresholds,
        max_hold_minutes_values,
        expected_pnl_thresholds,
    ):
        acceptance_mask = (
            (observation_arrays.success_probability >= win_threshold)
            & (observation_arrays.toxicity_probability <= toxicity_threshold)
            & (observation_arrays.predicted_holding_time_minutes <= max_hold_minutes)
            & (
                observation_arrays.expected_profit_and_loss_percentage
                >= expected_pnl_threshold
            )
        )
        matrix_row = build_sweep_matrix_row(
            observation_arrays,
            acceptance_mask,
            win_threshold,
            toxicity_threshold,
            max_hold_minutes,
            expected_pnl_threshold,
            window_days,
        )
        if matrix_row is not None:
            sweep_rows.append(matrix_row)
    return sweep_rows


def _nan_fallback(value: float, fallback: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return fallback
    return value


def sweep_row_sort_key(
    row: CortexGateSweepMatrixRow, rank_by: str
) -> tuple[float, ...]:
    if rank_by == "empirical_pf":
        return (_nan_fallback(row.empirical_pf, -999.0), row.accepted_count)
    if rank_by == "pf_stable":
        stable_pf = min(
            _nan_fallback(row.pf_first_half, -999.0),
            _nan_fallback(row.pf_second_half, -999.0),
        )
        return (stable_pf, _nan_fallback(row.empirical_pf, -999.0), row.accepted_count)
    if rank_by == "avg_pnl":
        return (_nan_fallback(row.avg_pnl_usd, -999.0), row.accepted_count)
    if rank_by == "pf_delta":
        return (
            _nan_fallback(row.pf_delta, -999.0),
            _nan_fallback(row.empirical_pf, -999.0),
            row.accepted_count,
        )
    if rank_by == "velocity":
        return (
            _nan_fallback(row.accepted_per_day, -1.0),
            _nan_fallback(row.empirical_pf, -999.0),
        )
    if rank_by == "composite":
        stable_pf = min(
            _nan_fallback(row.pf_first_half, -999.0),
            _nan_fallback(row.pf_second_half, -999.0),
        )
        return (
            stable_pf,
            _nan_fallback(row.avg_pnl_usd, -999.0),
            _nan_fallback(row.accepted_per_day, -1.0),
        )
    return (_nan_fallback(row.win_rate_pct, -1.0), row.accepted_count)


def make_sort_key(
    rank_by: str,
) -> Callable[[CortexGateSweepMatrixRow], tuple[float, ...]]:
    return lambda row: sweep_row_sort_key(row, rank_by)


def render_matrix_cell_for_fixed_width_table(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf"
        if abs(value) >= NO_HOLD_CAP_SENTINEL_MINUTES:
            return "none"
        return f"{value:.4f}"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def format_sweep_matrix_as_padded_text_lines(
    printable_rows: list[CortexGateSweepMatrixRow],
) -> list[str]:
    if not printable_rows:
        return []
    column_keys = list(CortexGateSweepMatrixRow.model_fields.keys())
    table: list[list[str]] = [list(column_keys)]
    for matrix_row in printable_rows:
        table.append(
            [
                render_matrix_cell_for_fixed_width_table(getattr(matrix_row, key))
                for key in column_keys
            ]
        )
    column_count = len(column_keys)
    column_widths = [
        max(len(table[row_index][column_index]) for row_index in range(len(table)))
        for column_index in range(column_count)
    ]
    return [
        "  ".join(
            table_row[column_index].ljust(column_widths[column_index])
            for column_index in range(column_count)
        )
        for table_row in table
    ]


def run_breakdown_report(
    observations: list[CortexGateSweepObservation],
    breakdown_mode: str,
    win_threshold: float,
    toxicity_threshold: float,
    max_hold_minutes: float,
    expected_pnl_threshold: float,
) -> None:
    def slice_key_for_observation(observation: CortexGateSweepObservation) -> str:
        if breakdown_mode == "model":
            return observation.cortex_model_version
        return observation.resolved_at.strftime("%Y-%m-%d")

    observations_by_slice: dict[str, list[CortexGateSweepObservation]] = {}
    for observation in observations:
        observations_by_slice.setdefault(
            slice_key_for_observation(observation), []
        ).append(observation)

    header = (
        f"{'slice':<22}  {'n':>7}  {'pred_wr%':>8}  {'real_wr%':>8}  {'calib_pp':>8}  "
        f"{'skill%':>7}  {'dir_acc%':>8}  {'pass%':>6}  {'gate_prec%':>10}  {'acc_avg_pnl':>11}  {'acc_pf':>7}"
    )
    logger.info(
        "[SCRIPT][CORTEX][GATE_SWEEP] Breakdown by %s (thresholds win>=%.2f tox<=%.2f hold<=%.0fmin pnl>=%.2f):",
        breakdown_mode,
        win_threshold,
        toxicity_threshold,
        max_hold_minutes,
        expected_pnl_threshold,
    )
    logger.info(header)

    for slice_key in sorted(observations_by_slice.keys()):
        slice_observations = observations_by_slice[slice_key]
        count = len(slice_observations)
        predicted_probabilities = [
            observation.success_probability for observation in slice_observations
        ]
        outcomes = [
            1.0 if observation.is_profitable else 0.0
            for observation in slice_observations
        ]
        predicted_win_rate_pct = sum(predicted_probabilities) / count * 100.0
        real_win_rate_pct = sum(outcomes) / count * 100.0
        calibration_gap_pp = predicted_win_rate_pct - real_win_rate_pct
        skill_score_pct = (
            sum(
                (2.0 * probability - 1.0) * (2.0 * outcome - 1.0)
                for probability, outcome in zip(predicted_probabilities, outcomes)
            )
            / count
            * 100.0
        )
        directional_accuracy_pct = (
            sum(
                1.0
                for probability, outcome in zip(predicted_probabilities, outcomes)
                if (probability >= 0.5 and outcome >= 0.5)
                or (probability < 0.5 and outcome < 0.5)
            )
            / count
            * 100.0
        )

        accepted_observations = [
            observation
            for observation in slice_observations
            if observation.success_probability >= win_threshold
            and observation.toxicity_probability <= toxicity_threshold
            and observation.predicted_holding_time_minutes <= max_hold_minutes
            and observation.expected_profit_and_loss_percentage
            >= expected_pnl_threshold
        ]
        pass_rate_pct = len(accepted_observations) / count * 100.0
        if accepted_observations:
            gate_precision_pct = (
                sum(
                    1.0
                    for observation in accepted_observations
                    if observation.is_profitable
                )
                / len(accepted_observations)
                * 100.0
            )
            accepted_pnls = numpy.asarray(
                [
                    observation.realized_profit_and_loss_usd
                    for observation in accepted_observations
                ],
                dtype=numpy.float64,
            )
            accepted_avg_pnl = float(accepted_pnls.mean())
            accepted_pf = compute_empirical_profit_factor(accepted_pnls)
        else:
            gate_precision_pct = math.nan
            accepted_avg_pnl = math.nan
            accepted_pf = math.nan

        logger.info(
            f"{slice_key:<22}  {count:>7}  {predicted_win_rate_pct:>8.1f}  {real_win_rate_pct:>8.1f}  "
            f"{calibration_gap_pp:>8.1f}  {skill_score_pct:>7.1f}  {directional_accuracy_pct:>8.1f}  "
            f"{pass_rate_pct:>6.1f}  {gate_precision_pct:>10.1f}  {accepted_avg_pnl:>11.2f}  {accepted_pf:>7.3f}"
        )


def parse_comma_separated_floats(raw: str) -> list[float]:
    return [float(part.strip()) for part in raw.split(",") if part.strip()]


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
        f"cortex_gate_sweetspot_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.root.addHandler(file_handler)
    logging.root.setLevel(logging.INFO)
    return log_file_path


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description="Cortex gate threshold sweep over realized shadowing (or paper trade) outcomes",
        epilog=(
            "Example runs:\n"
            "  Full-history sweep ranked by stable profit factor:\n"
            "    python scripts/cortex_gate_sweetspot_scan.py --rank-by pf_stable\n"
            "  Tighten around current thresholds with a custom grid:\n"
            "    python scripts/cortex_gate_sweetspot_scan.py "
            "--win-thresholds 0.55,0.58,0.60,0.62 --toxicity-thresholds 0.40,0.45 "
            "--max-hold-minutes 240,360,600 --min-n 100 --csv cortex_gate_sweep.csv\n"
            "  Cross-check on real paper trade positions:\n"
            "    python scripts/cortex_gate_sweetspot_scan.py --dataset trades --min-n 30 --min-n-second-half 10\n"
            "  Locate accuracy degradation per active model version:\n"
            "    python scripts/cortex_gate_sweetspot_scan.py --breakdown model\n"
            "  Daily health of the current gate:\n"
            "    python scripts/cortex_gate_sweetspot_scan.py --breakdown day\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    argument_parser.add_argument(
        "--dataset",
        choices=("shadowing", "trades"),
        default="shadowing",
        help="Data source: shadowing verdicts (default, all history) or real paper trade positions",
    )
    argument_parser.add_argument(
        "--lookback-days",
        type=float,
        default=None,
        help="Optional lookback restriction in days (default: all available history)",
    )
    argument_parser.add_argument(
        "--max-fetch",
        type=int,
        default=1_000_000,
        help="Maximum number of shadowing verdicts to fetch",
    )
    argument_parser.add_argument(
        "--win-thresholds",
        default="0.50,0.55,0.58,0.60,0.62,0.65,0.70",
        help="Comma-separated minimum success probability thresholds",
    )
    argument_parser.add_argument(
        "--toxicity-thresholds",
        default="0.30,0.35,0.40,0.45,0.50",
        help="Comma-separated maximum toxicity probability thresholds",
    )
    argument_parser.add_argument(
        "--max-hold-minutes",
        default=f"240,360,480,600,{NO_HOLD_CAP_SENTINEL_MINUTES:.0f}",
        help="Comma-separated maximum predicted holding time values in minutes (large value = no cap)",
    )
    argument_parser.add_argument(
        "--expected-pnl-thresholds",
        default="0,1,3",
        help="Comma-separated minimum expected PnL percentage thresholds",
    )
    argument_parser.add_argument(
        "--min-n",
        type=int,
        default=50,
        help="Minimum accepted count for a sweep row to be listed",
    )
    argument_parser.add_argument(
        "--min-n-second-half",
        type=int,
        default=20,
        help="Minimum accepted count in the second (most recent) half of the window",
    )
    argument_parser.add_argument(
        "--rank-by",
        choices=(
            "empirical_pf",
            "pf_stable",
            "avg_pnl",
            "pf_delta",
            "velocity",
            "composite",
            "win_rate",
        ),
        default="pf_stable",
        help="Sort printable rows by this primary objective",
    )
    argument_parser.add_argument(
        "--breakdown",
        choices=("day", "model"),
        default=None,
        help="Instead of sweeping, report per-day or per-model-version gate health for one threshold set",
    )
    argument_parser.add_argument(
        "--win-threshold",
        type=float,
        default=settings.TRADING_CORTEX_SUCCESS_PROBABILITY_THRESHOLD,
        help="Breakdown mode: success probability threshold (default: current settings)",
    )
    argument_parser.add_argument(
        "--toxicity-threshold",
        type=float,
        default=settings.TRADING_CORTEX_TOXICITY_PROBABILITY_THRESHOLD,
        help="Breakdown mode: toxicity probability threshold (default: current settings)",
    )
    argument_parser.add_argument(
        "--max-hold-minutes-single",
        type=float,
        default=settings.TRADING_CORTEX_HOLDING_TIME_MAX_HOURS * 60.0,
        help="Breakdown mode: max predicted holding time in minutes (default: current settings)",
    )
    argument_parser.add_argument(
        "--expected-pnl-threshold",
        type=float,
        default=settings.TRADING_CORTEX_PNL_THRESHOLD,
        help="Breakdown mode: expected PnL percentage threshold (default: current settings)",
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
        "--max-printed-rows",
        type=int,
        default=80,
        help="Maximum number of rows printed in the result matrix",
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
        logger.info(
            "[SCRIPT][CORTEX][GATE_SWEEP] Writing log file to %s",
            log_file_path.as_posix(),
        )

    try:
        if parsed.dataset == "trades":
            observations = load_paper_trade_cortex_observations()
        else:
            observations = load_shadowing_cortex_observations(
                lookback_days=parsed.lookback_days,
                max_fetch_count=parsed.max_fetch,
            )
        if not observations:
            logger.info(
                "[SCRIPT][CORTEX][GATE_SWEEP] No usable observations — nothing to do"
            )
            return

        window_start = min(observation.resolved_at for observation in observations)
        window_end = max(observation.resolved_at for observation in observations)
        logger.info(
            "[SCRIPT][CORTEX][GATE_SWEEP] Observation window — start=%s end=%s count=%d",
            window_start.isoformat(),
            window_end.isoformat(),
            len(observations),
        )

        if parsed.breakdown is not None:
            run_breakdown_report(
                observations,
                breakdown_mode=parsed.breakdown,
                win_threshold=parsed.win_threshold,
                toxicity_threshold=parsed.toxicity_threshold,
                max_hold_minutes=parsed.max_hold_minutes_single,
                expected_pnl_threshold=parsed.expected_pnl_threshold,
            )
            return

        observation_arrays = build_observation_arrays(observations)
        sweep_rows = run_cortex_gate_threshold_sweep(
            observation_arrays,
            win_thresholds=parse_comma_separated_floats(parsed.win_thresholds),
            toxicity_thresholds=parse_comma_separated_floats(
                parsed.toxicity_thresholds
            ),
            max_hold_minutes_values=parse_comma_separated_floats(
                parsed.max_hold_minutes
            ),
            expected_pnl_thresholds=parse_comma_separated_floats(
                parsed.expected_pnl_thresholds
            ),
        )
        sweep_rows.sort(key=make_sort_key(parsed.rank_by), reverse=True)

        printable_rows = [
            row
            for row in sweep_rows
            if row.accepted_count >= parsed.min_n
            and row.n_second_half >= parsed.min_n_second_half
        ]

        resolved_csv_path = resolve_sweep_csv_output_path(parsed.csv_output_path)
        if resolved_csv_path is not None:
            resolved_csv_path.parent.mkdir(parents=True, exist_ok=True)
            column_names = list(CortexGateSweepMatrixRow.model_fields.keys())
            with resolved_csv_path.open("w", newline="", encoding="utf-8") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=column_names)
                writer.writeheader()
                for row in printable_rows:
                    writer.writerow(row.model_dump())
            logger.info(
                "[SCRIPT][CORTEX][GATE_SWEEP] CSV written to %s",
                resolved_csv_path.as_posix(),
            )

        logger.info(
            "[SCRIPT][CORTEX][GATE_SWEEP] Sweep finished — printable_rows=%d total_rows=%d "
            "min_n=%d min_n_second_half=%d rank_by=%s",
            len(printable_rows),
            len(sweep_rows),
            parsed.min_n,
            parsed.min_n_second_half,
            parsed.rank_by,
        )

        table_lines = format_sweep_matrix_as_padded_text_lines(
            printable_rows[: parsed.max_printed_rows]
        )
        if table_lines:
            logger.info("[SCRIPT][CORTEX][GATE_SWEEP] Result matrix:")
            for table_line in table_lines:
                logger.info(table_line)

        if len(printable_rows) > parsed.max_printed_rows:
            logger.info(
                "[SCRIPT][CORTEX][GATE_SWEEP] ... %d additional rows not shown",
                len(printable_rows) - parsed.max_printed_rows,
            )
    except Exception:
        logger.exception(
            "[SCRIPT][CORTEX][GATE_SWEEP] Cortex gate threshold sweep terminated with error"
        )
        raise


if __name__ == "__main__":
    main()
