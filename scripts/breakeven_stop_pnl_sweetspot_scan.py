from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import joinedload, load_only

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

from src.configuration.config import settings
from src.core.utils.date_utils import ensure_timezone_aware, get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingShadowingProbe, TradingShadowingVerdict

logger = get_application_logger(__name__)

if not logging.root.handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

STALED_EXIT_REASON = "STALED"
DEFAULT_BREAKEVEN_STOP_PNL_FRACTIONS = (
    "-0.10,-0.07,-0.05,-0.03,-0.02,-0.015,-0.01,-0.005,0,0.005,0.01,0.02,0.03,0.05"
)
RANK_BY_AVERAGE_PROFIT_AND_LOSS_UPLIFT_PERCENTAGE = "average_profit_and_loss_uplift_percentage"
RANK_BY_COUNTERFACTUAL_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE = "counterfactual_average_profit_and_loss_percentage"
RANK_BY_COUNTERFACTUAL_EMPIRICAL_PROFIT_FACTOR = "counterfactual_empirical_profit_factor"
RANK_BY_PROFIT_FACTOR_UPLIFT = "profit_factor_uplift"


class BreakevenStopPnlObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    probed_at: datetime
    resolved_at: datetime
    entry_price_usd: float
    order_notional_value_usd: float
    exit_reason: str
    realized_profit_and_loss_percentage: float
    post_take_profit_tier_1_lowest_price: float
    post_take_profit_tier_1_breakeven_touched: bool
    market_cap_to_liquidity_ratio: float | None
    predicted_holding_time_hours: float | None


class BreakevenStopPnlCounterfactualResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    profit_and_loss_percentage: float
    stopped: bool


class BreakevenStopPnlSweepMatrixRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    breakeven_stop_pnl_fraction: float
    breakeven_stop_pnl_percentage: float
    evaluated_count: int
    stopped_count: int
    stop_rate: float
    stop_rate_among_original_winners: float
    stop_rate_among_original_losers: float
    baseline_average_profit_and_loss_percentage: float
    counterfactual_average_profit_and_loss_percentage: float
    average_profit_and_loss_uplift_percentage: float
    baseline_win_rate: float
    counterfactual_win_rate: float
    baseline_empirical_profit_factor: float
    counterfactual_empirical_profit_factor: float
    profit_factor_uplift: float
    saved_catastrophic_count: int
    cut_original_winner_count: int
    counterfactual_total_profit_and_loss_usd: float
    baseline_total_profit_and_loss_usd: float


def parse_comma_separated_floats(raw_value: str) -> list[float]:
    values: list[float] = []
    for fragment in raw_value.split(","):
        normalized_fragment = fragment.strip()
        if not normalized_fragment:
            continue
        values.append(float(normalized_fragment))
    if not values:
        raise ValueError("expected at least one float value")
    return values


def parse_optional_local_datetime(raw_value: str | None) -> datetime | None:
    if raw_value is None or not raw_value.strip():
        return None
    parsed = datetime.fromisoformat(raw_value.strip())
    return ensure_timezone_aware(parsed)


def resolve_maximum_breakeven_stop_pnl_fraction() -> float:
    return max(0.0, min(1.0, settings.TRADING_BREAKEVEN_ARM_FRACTION))


def clamp_breakeven_stop_pnl_fraction(
        breakeven_stop_pnl_fraction: float,
        maximum_breakeven_stop_pnl_fraction: float,
) -> float:
    exclusive_upper_bound = maximum_breakeven_stop_pnl_fraction
    exclusive_lower_bound = -1.0
    if not (exclusive_lower_bound < breakeven_stop_pnl_fraction < exclusive_upper_bound):
        raise ValueError(
            f"breakeven stop PnL fraction {breakeven_stop_pnl_fraction} out of open interval "
            f"({exclusive_lower_bound}, {exclusive_upper_bound}); "
            f"must stay below BE arm ({maximum_breakeven_stop_pnl_fraction:.4f})"
        )
    return breakeven_stop_pnl_fraction


def compute_empirical_profit_factor(profit_and_loss_percentages: list[float]) -> float:
    gross_profit = sum(value for value in profit_and_loss_percentages if value > 0.0)
    gross_loss = abs(sum(value for value in profit_and_loss_percentages if value < 0.0))
    if gross_loss <= 0.0:
        return math.inf if gross_profit > 0.0 else 0.0
    return gross_profit / gross_loss


def compute_average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_stop_price_usd(entry_price_usd: float, breakeven_stop_pnl_fraction: float) -> float:
    return entry_price_usd * (1.0 + breakeven_stop_pnl_fraction)


def would_breakeven_stop_trigger(
        entry_price_usd: float,
        lowest_price_after_take_profit_tier_1: float,
        breakeven_stop_pnl_fraction: float,
) -> bool:
    if entry_price_usd <= 0.0:
        return False
    stop_price = compute_stop_price_usd(
        entry_price_usd=entry_price_usd,
        breakeven_stop_pnl_fraction=breakeven_stop_pnl_fraction,
    )
    return lowest_price_after_take_profit_tier_1 <= stop_price


def resolve_counterfactual_profit_and_loss(
        observation: BreakevenStopPnlObservation,
        breakeven_stop_pnl_fraction: float,
) -> BreakevenStopPnlCounterfactualResult:
    stopped = would_breakeven_stop_trigger(
        entry_price_usd=observation.entry_price_usd,
        lowest_price_after_take_profit_tier_1=observation.post_take_profit_tier_1_lowest_price,
        breakeven_stop_pnl_fraction=breakeven_stop_pnl_fraction,
    )
    if not stopped:
        return BreakevenStopPnlCounterfactualResult(
            profit_and_loss_percentage=observation.realized_profit_and_loss_percentage,
            stopped=False,
        )
    return BreakevenStopPnlCounterfactualResult(
        profit_and_loss_percentage=breakeven_stop_pnl_fraction * 100.0,
        stopped=True,
    )


def observation_passes_liquidity_structure_filter(
        observation: BreakevenStopPnlObservation,
        minimum_ratio: float,
        maximum_ratio: float,
) -> bool:
    ratio = observation.market_cap_to_liquidity_ratio
    if ratio is None:
        return False
    return minimum_ratio <= ratio <= maximum_ratio


def observation_passes_holding_time_filter(
        observation: BreakevenStopPnlObservation,
        minimum_hours: float,
        maximum_hours: float,
) -> bool:
    predicted_holding_time_hours = observation.predicted_holding_time_hours
    if predicted_holding_time_hours is None:
        return False
    return minimum_hours <= predicted_holding_time_hours <= maximum_hours


def fetch_instrumented_breakeven_arm_observations(
        maximum_fetch_count: int,
        probed_since: datetime | None,
) -> list[BreakevenStopPnlObservation]:
    with get_database_session() as database_session:
        statement = (
            select(TradingShadowingVerdict)
            .join(TradingShadowingVerdict.probe)
            .options(
                load_only(
                    TradingShadowingVerdict.id,
                    TradingShadowingVerdict.probe_id,
                    TradingShadowingVerdict.exit_reason,
                    TradingShadowingVerdict.realized_pnl_percentage,
                    TradingShadowingVerdict.take_profit_tier_1_hit_at,
                    TradingShadowingVerdict.post_take_profit_tier_1_lowest_price,
                    TradingShadowingVerdict.post_take_profit_tier_1_breakeven_touched_at,
                    TradingShadowingVerdict.resolved_at,
                ),
                joinedload(TradingShadowingVerdict.probe).load_only(
                    TradingShadowingProbe.id,
                    TradingShadowingProbe.entry_price_usd,
                    TradingShadowingProbe.order_notional_value_usd,
                    TradingShadowingProbe.market_cap_usd,
                    TradingShadowingProbe.liquidity_usd,
                    TradingShadowingProbe.probed_at,
                    TradingShadowingProbe.cortex_inference_summary,
                ),
            )
            .where(TradingShadowingVerdict.exit_reason.is_not(None))
            .where(TradingShadowingVerdict.resolved_at.is_not(None))
            .where(TradingShadowingVerdict.take_profit_tier_1_hit_at.is_not(None))
            .where(TradingShadowingVerdict.post_take_profit_tier_1_lowest_price.is_not(None))
            .where(TradingShadowingVerdict.realized_pnl_percentage.is_not(None))
            .order_by(TradingShadowingVerdict.resolved_at.desc())
            .limit(maximum_fetch_count)
        )
        if probed_since is not None:
            statement = statement.where(TradingShadowingProbe.probed_at >= probed_since)

        verdicts = list(database_session.scalars(statement).unique().all())

        observations: list[BreakevenStopPnlObservation] = []
        for verdict in verdicts:
            probe = verdict.probe
            if probe is None or verdict.resolved_at is None or verdict.realized_pnl_percentage is None:
                continue
            if verdict.post_take_profit_tier_1_lowest_price is None:
                continue
            if probe.entry_price_usd <= 0.0:
                continue

            market_cap_to_liquidity_ratio: float | None = None
            if probe.market_cap_usd > 0.0 and probe.liquidity_usd > 0.0:
                market_cap_to_liquidity_ratio = probe.market_cap_usd / probe.liquidity_usd

            predicted_holding_time_hours: float | None = None
            cortex_inference_summary = probe.cortex_inference_summary
            if cortex_inference_summary is not None and cortex_inference_summary.predicted_holding_time_minutes is not None:
                predicted_holding_time_hours = cortex_inference_summary.predicted_holding_time_minutes / 60.0

            observations.append(
                BreakevenStopPnlObservation(
                    probed_at=ensure_timezone_aware(probe.probed_at),
                    resolved_at=ensure_timezone_aware(verdict.resolved_at),
                    entry_price_usd=probe.entry_price_usd,
                    order_notional_value_usd=probe.order_notional_value_usd,
                    exit_reason=str(verdict.exit_reason),
                    realized_profit_and_loss_percentage=verdict.realized_pnl_percentage,
                    post_take_profit_tier_1_lowest_price=verdict.post_take_profit_tier_1_lowest_price,
                    post_take_profit_tier_1_breakeven_touched=verdict.post_take_profit_tier_1_breakeven_touched_at is not None,
                    market_cap_to_liquidity_ratio=market_cap_to_liquidity_ratio,
                    predicted_holding_time_hours=predicted_holding_time_hours,
                )
            )
    observations.reverse()
    return observations


def filter_observations(
        observations: list[BreakevenStopPnlObservation],
        apply_liquidity_structure_filter: bool,
        apply_holding_time_filter: bool,
) -> list[BreakevenStopPnlObservation]:
    retained: list[BreakevenStopPnlObservation] = []
    for observation in observations:
        if apply_liquidity_structure_filter and not observation_passes_liquidity_structure_filter(
                observation=observation,
                minimum_ratio=settings.TRADING_LIQUIDITY_STRUCTURE_MIN_MARKET_CAP_TO_LIQUIDITY_RATIO,
                maximum_ratio=settings.TRADING_LIQUIDITY_STRUCTURE_MAX_MARKET_CAP_TO_LIQUIDITY_RATIO,
        ):
            continue
        if apply_holding_time_filter and not observation_passes_holding_time_filter(
                observation=observation,
                minimum_hours=settings.TRADING_CORTEX_HOLDING_TIME_MIN_HOURS,
                maximum_hours=settings.TRADING_CORTEX_HOLDING_TIME_MAX_HOURS,
        ):
            continue
        retained.append(observation)
    return retained


def evaluate_breakeven_stop_pnl_fraction(
        observations: list[BreakevenStopPnlObservation],
        breakeven_stop_pnl_fraction: float,
) -> BreakevenStopPnlSweepMatrixRow:
    baseline_percentages: list[float] = []
    counterfactual_percentages: list[float] = []
    baseline_usd_values: list[float] = []
    counterfactual_usd_values: list[float] = []
    stopped_count = 0
    original_winner_count = 0
    original_loser_count = 0
    stopped_original_winner_count = 0
    stopped_original_loser_count = 0
    saved_catastrophic_count = 0
    cut_original_winner_count = 0

    for observation in observations:
        baseline_percentage = observation.realized_profit_and_loss_percentage
        counterfactual_result = resolve_counterfactual_profit_and_loss(
            observation=observation,
            breakeven_stop_pnl_fraction=breakeven_stop_pnl_fraction,
        )
        baseline_percentages.append(baseline_percentage)
        counterfactual_percentages.append(counterfactual_result.profit_and_loss_percentage)

        notional = observation.order_notional_value_usd
        baseline_usd_values.append(notional * baseline_percentage / 100.0)
        counterfactual_usd_values.append(notional * counterfactual_result.profit_and_loss_percentage / 100.0)

        is_original_winner = baseline_percentage > 0.0
        if is_original_winner:
            original_winner_count += 1
        else:
            original_loser_count += 1

        if counterfactual_result.stopped:
            stopped_count += 1
            if is_original_winner:
                stopped_original_winner_count += 1
                cut_original_winner_count += 1
            else:
                stopped_original_loser_count += 1
                if observation.exit_reason == STALED_EXIT_REASON or baseline_percentage <= -50.0:
                    saved_catastrophic_count += 1

    evaluated_count = len(observations)
    baseline_average = compute_average(baseline_percentages)
    counterfactual_average = compute_average(counterfactual_percentages)
    baseline_empirical_profit_factor = compute_empirical_profit_factor(baseline_percentages)
    counterfactual_empirical_profit_factor = compute_empirical_profit_factor(counterfactual_percentages)

    return BreakevenStopPnlSweepMatrixRow(
        breakeven_stop_pnl_fraction=breakeven_stop_pnl_fraction,
        breakeven_stop_pnl_percentage=breakeven_stop_pnl_fraction * 100.0,
        evaluated_count=evaluated_count,
        stopped_count=stopped_count,
        stop_rate=(stopped_count / evaluated_count) if evaluated_count > 0 else 0.0,
        stop_rate_among_original_winners=(
            stopped_original_winner_count / original_winner_count if original_winner_count > 0 else 0.0
        ),
        stop_rate_among_original_losers=(
            stopped_original_loser_count / original_loser_count if original_loser_count > 0 else 0.0
        ),
        baseline_average_profit_and_loss_percentage=baseline_average,
        counterfactual_average_profit_and_loss_percentage=counterfactual_average,
        average_profit_and_loss_uplift_percentage=counterfactual_average - baseline_average,
        baseline_win_rate=(
            sum(1 for value in baseline_percentages if value > 0.0) / evaluated_count if evaluated_count > 0 else 0.0
        ),
        counterfactual_win_rate=(
            sum(1 for value in counterfactual_percentages if value > 0.0) / evaluated_count if evaluated_count > 0 else 0.0
        ),
        baseline_empirical_profit_factor=baseline_empirical_profit_factor,
        counterfactual_empirical_profit_factor=counterfactual_empirical_profit_factor,
        profit_factor_uplift=(
            counterfactual_empirical_profit_factor - baseline_empirical_profit_factor
            if math.isfinite(counterfactual_empirical_profit_factor) and math.isfinite(baseline_empirical_profit_factor)
            else float("nan")
        ),
        saved_catastrophic_count=saved_catastrophic_count,
        cut_original_winner_count=cut_original_winner_count,
        counterfactual_total_profit_and_loss_usd=sum(counterfactual_usd_values),
        baseline_total_profit_and_loss_usd=sum(baseline_usd_values),
    )


def resolve_rank_metric(matrix_row: BreakevenStopPnlSweepMatrixRow, rank_by: str) -> float:
    if rank_by == RANK_BY_AVERAGE_PROFIT_AND_LOSS_UPLIFT_PERCENTAGE:
        return matrix_row.average_profit_and_loss_uplift_percentage
    if rank_by == RANK_BY_COUNTERFACTUAL_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE:
        return matrix_row.counterfactual_average_profit_and_loss_percentage
    if rank_by == RANK_BY_COUNTERFACTUAL_EMPIRICAL_PROFIT_FACTOR:
        return matrix_row.counterfactual_empirical_profit_factor
    if rank_by == RANK_BY_PROFIT_FACTOR_UPLIFT:
        return matrix_row.profit_factor_uplift
    raise ValueError(f"unsupported rank_by value: {rank_by}")


def render_matrix_cell(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return f"{value:.6f}"
    return str(value)


def format_matrix_as_padded_text_lines(rows: list[BreakevenStopPnlSweepMatrixRow]) -> list[str]:
    if not rows:
        return []
    column_keys = list(BreakevenStopPnlSweepMatrixRow.model_fields.keys())
    table: list[list[str]] = [list(column_keys)]
    for row in rows:
        serialized_row = row.model_dump()
        table.append([render_matrix_cell(serialized_row[column_key]) for column_key in column_keys])
    column_widths = [
        max(len(table[row_index][column_index]) for row_index in range(len(table)))
        for column_index in range(len(column_keys))
    ]
    return [
        "  ".join(
            table_row[column_index].ljust(column_widths[column_index])
            for column_index in range(len(column_keys))
        )
        for table_row in table
    ]


def write_csv(rows: list[BreakevenStopPnlSweepMatrixRow], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    column_keys = list(BreakevenStopPnlSweepMatrixRow.model_fields.keys())
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=column_keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())


def attach_log_file() -> Path:
    SWEEP_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = get_current_local_datetime().strftime("%Y%m%d_%H%M%S")
    log_file_path = SWEEP_LOG_DIR / f"breakeven_stop_pnl_sweetspot_scan_{timestamp}.log"
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.root.addHandler(file_handler)
    logging.root.setLevel(logging.INFO)
    return log_file_path


def resolve_csv_path(raw_csv_name: str | None) -> Path | None:
    if raw_csv_name is None or not raw_csv_name.strip():
        return None
    candidate = Path(raw_csv_name.strip())
    if candidate.is_absolute() or len(candidate.parts) > 1:
        return candidate
    SWEEP_CSV_DIR.mkdir(parents=True, exist_ok=True)
    return SWEEP_CSV_DIR / candidate.name


def main() -> None:
    argument_parser = argparse.ArgumentParser(
        description=(
            "Sweep TRADING_EXIT_BREAKEVEN_STOP_PNL_FRACTION on instrumented shadowing verdicts "
            "(BE-arm hit + post-arm lowest price). Signed PnL versus entry: "
            "-0.05 stops at -5 percent; +0.05 stops at +5 percent (strictly below BE arm)."
        ),
        epilog=(
            "Example runs:\n"
            "  Default PnL grid on live-like universe:\n"
            "    python scripts/breakeven_stop_pnl_sweetspot_scan.py "
            "--probed-since 2026-08-01T00:00:00 --apply-live-filters\n"
            "  Focus around fee-recovery versus small locked gains:\n"
            "    python scripts/breakeven_stop_pnl_sweetspot_scan.py "
            "--pnl-fractions -0.05,-0.02,-0.01,0,0.01,0.02,0.05 --apply-live-filters "
            "--csv breakeven_stop_pnl_sweep.csv\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    argument_parser.add_argument(
        "--pnl-fractions",
        dest="pnl_fractions",
        default=DEFAULT_BREAKEVEN_STOP_PNL_FRACTIONS,
        help=(
            "Comma-separated signed BE stop PnL fractions versus entry "
            f"(default: {DEFAULT_BREAKEVEN_STOP_PNL_FRACTIONS})"
        ),
    )
    argument_parser.add_argument(
        "--probed-since",
        default=None,
        help=(
            "ISO local datetime lower bound on probe.probed_at. "
            "Required in practice: NULL instrumentation rows mean unmeasured, not untouched"
        ),
    )
    argument_parser.add_argument(
        "--lookback-days",
        type=float,
        default=None,
        help="Optional alternative to --probed-since: keep probes from now - lookback",
    )
    argument_parser.add_argument(
        "--max-fetch",
        type=int,
        default=500_000,
        help="Maximum instrumented BE-arm verdicts to fetch",
    )
    argument_parser.add_argument(
        "--apply-live-filters",
        action="store_true",
        help=(
            "Restrict to live-like universe: market-cap/liquidity band and Cortex holding-time window "
            "from current settings"
        ),
    )
    argument_parser.add_argument(
        "--min-n",
        type=int,
        default=30,
        help="Minimum evaluated count before ranking a row as usable",
    )
    argument_parser.add_argument(
        "--rank-by",
        choices=(
            RANK_BY_AVERAGE_PROFIT_AND_LOSS_UPLIFT_PERCENTAGE,
            RANK_BY_COUNTERFACTUAL_AVERAGE_PROFIT_AND_LOSS_PERCENTAGE,
            RANK_BY_COUNTERFACTUAL_EMPIRICAL_PROFIT_FACTOR,
            RANK_BY_PROFIT_FACTOR_UPLIFT,
        ),
        default=RANK_BY_AVERAGE_PROFIT_AND_LOSS_UPLIFT_PERCENTAGE,
        help="Primary ranking objective for the printable matrix",
    )
    argument_parser.add_argument(
        "--csv",
        default=None,
        help="Optional CSV filename (written under scripts/csv/ when bare)",
    )
    argument_parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable timestamped log file under scripts/logs/",
    )
    arguments = argument_parser.parse_args()

    if not arguments.no_log_file:
        log_file_path = attach_log_file()
        logger.info("[TRADING][BREAKEVEN][STOP_PNL][SWEEP] Log file: %s", log_file_path)

    maximum_breakeven_stop_pnl_fraction = resolve_maximum_breakeven_stop_pnl_fraction()
    raw_pnl_fractions = sorted(set(parse_comma_separated_floats(arguments.pnl_fractions)))
    pnl_fractions: list[float] = []
    for raw_pnl_fraction in raw_pnl_fractions:
        try:
            pnl_fractions.append(
                clamp_breakeven_stop_pnl_fraction(
                    breakeven_stop_pnl_fraction=raw_pnl_fraction,
                    maximum_breakeven_stop_pnl_fraction=maximum_breakeven_stop_pnl_fraction,
                )
            )
        except ValueError as error:
            logger.warning("[TRADING][BREAKEVEN][STOP_PNL][SWEEP] Skipping invalid PnL fraction: %s", error)

    if not pnl_fractions:
        raise SystemExit("no valid --pnl-fractions remaining after BE-arm clamp")

    probed_since = parse_optional_local_datetime(arguments.probed_since)
    if probed_since is None and arguments.lookback_days is not None:
        probed_since = get_current_local_datetime() - timedelta(days=arguments.lookback_days)

    if probed_since is None:
        logger.warning(
            "[TRADING][BREAKEVEN][STOP_PNL][SWEEP] No --probed-since / --lookback-days: "
            "rows without instrumentation are already excluded, but mixing pre/post deploy eras is discouraged",
        )

    observations = fetch_instrumented_breakeven_arm_observations(
        maximum_fetch_count=arguments.max_fetch,
        probed_since=probed_since,
    )
    if arguments.apply_live_filters:
        observations = filter_observations(
            observations=observations,
            apply_liquidity_structure_filter=True,
            apply_holding_time_filter=True,
        )

    logger.info(
        "[TRADING][BREAKEVEN][STOP_PNL][SWEEP] Loaded %d instrumented BE-arm observations "
        "(probed_since=%s, live_filters=%s)",
        len(observations),
        probed_since.isoformat() if probed_since is not None else "none",
        arguments.apply_live_filters,
    )
    logger.info(
        "[TRADING][BREAKEVEN][STOP_PNL][SWEEP] Signed PnL versus entry in (-1, BE arm=%.2f%%): "
        "-0.05 -> -5%% stop, +0.05 -> +5%% stop",
        maximum_breakeven_stop_pnl_fraction * 100.0,
    )
    if observations:
        breakeven_touched_count = sum(
            1 for observation in observations if observation.post_take_profit_tier_1_breakeven_touched
        )
        logger.info(
            "[TRADING][BREAKEVEN][STOP_PNL][SWEEP] Entry re-touch rate at PnL 0 (instrumented flag): %.2f%% (%d / %d)",
            100.0 * breakeven_touched_count / len(observations),
            breakeven_touched_count,
            len(observations),
        )

    matrix_rows = [
        evaluate_breakeven_stop_pnl_fraction(
            observations=observations,
            breakeven_stop_pnl_fraction=pnl_fraction,
        )
        for pnl_fraction in pnl_fractions
    ]
    usable_rows = [row for row in matrix_rows if row.evaluated_count >= arguments.min_n]
    ranked_rows = sorted(
        usable_rows,
        key=lambda row: resolve_rank_metric(row, arguments.rank_by),
        reverse=True,
    )

    current_configured_pnl_fraction = settings.TRADING_EXIT_BREAKEVEN_STOP_PNL_FRACTION
    logger.info(
        "[TRADING][BREAKEVEN][STOP_PNL][SWEEP] Current configured BE stop PnL=%.4f (%+.2f%%) | rank_by=%s | min_n=%d",
        current_configured_pnl_fraction,
        current_configured_pnl_fraction * 100.0,
        arguments.rank_by,
        arguments.min_n,
    )

    for line in format_matrix_as_padded_text_lines(ranked_rows if ranked_rows else matrix_rows):
        logger.info("%s", line)

    if ranked_rows:
        best_row = ranked_rows[0]
        logger.info(
            "[TRADING][BREAKEVEN][STOP_PNL][SWEEP] Best by %s -> pnl=%.4f (%+.2f%%) | avg pnl uplift %+.3f pp | "
            "PF uplift %+.3f | stop_rate=%.2f%% | cut_winners=%d | saved_catastrophic=%d",
            arguments.rank_by,
            best_row.breakeven_stop_pnl_fraction,
            best_row.breakeven_stop_pnl_percentage,
            best_row.average_profit_and_loss_uplift_percentage,
            best_row.profit_factor_uplift if math.isfinite(best_row.profit_factor_uplift) else float("nan"),
            best_row.stop_rate * 100.0,
            best_row.cut_original_winner_count,
            best_row.saved_catastrophic_count,
        )
        matching_current = next(
            (
                row
                for row in matrix_rows
                if abs(row.breakeven_stop_pnl_fraction - current_configured_pnl_fraction) < 1e-12
            ),
            None,
        )
        if matching_current is not None:
            logger.info(
                "[TRADING][BREAKEVEN][STOP_PNL][SWEEP] Configured PnL %.4f (%+.2f%%) -> avg pnl uplift %+.3f pp | "
                "PF uplift %+.3f | stop_rate=%.2f%%",
                matching_current.breakeven_stop_pnl_fraction,
                matching_current.breakeven_stop_pnl_percentage,
                matching_current.average_profit_and_loss_uplift_percentage,
                (
                    matching_current.profit_factor_uplift
                    if math.isfinite(matching_current.profit_factor_uplift)
                    else float("nan")
                ),
                matching_current.stop_rate * 100.0,
            )

    csv_path = resolve_csv_path(arguments.csv)
    if csv_path is not None:
        write_csv(rows=matrix_rows, csv_path=csv_path)
        logger.info("[TRADING][BREAKEVEN][STOP_PNL][SWEEP] CSV written: %s", csv_path)


if __name__ == "__main__":
    main()
