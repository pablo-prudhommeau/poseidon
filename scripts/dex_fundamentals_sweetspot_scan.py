from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
from datetime import datetime, timedelta
from itertools import product
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
UNBOUNDED_MAXIMUM = 1.0e18

SWEEP_AXES = (
    "liquidity_structure",
    "age",
    "liquidity_min",
    "volume_h1",
    "volume_h24",
    "fdv",
    "market_cap",
    "liq_to_fdv",
    "momentum_abs_24h",
    "holding_hours",
    "combo_ls_holding",
)

BUCKET_FEATURES = (
    "mcap_to_liq",
    "age_hours",
    "liquidity_usd",
    "volume_h1_usd",
    "volume_h24_usd",
    "fdv_usd",
    "market_cap_usd",
    "liq_to_fdv",
    "abs_price_change_h24",
    "holding_hours",
)


class DexFundamentalsObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    resolved_at: datetime
    exit_reason: str
    realized_profit_and_loss_percentage: float
    realized_profit_and_loss_usd: float
    is_profitable: bool
    market_cap_usd: float
    liquidity_usd: float
    fully_diluted_valuation_usd: float
    token_age_hours: float
    volume_h1_usd: float
    volume_h24_usd: float
    price_change_percentage_h24: float
    price_change_percentage_h1: float
    price_change_percentage_h6: float
    price_change_percentage_m5: float
    predicted_holding_time_hours: float | None
    cortex_gate_accepted: bool | None

    @property
    def market_cap_to_liquidity_ratio(self) -> float | None:
        if self.market_cap_usd <= 0.0 or self.liquidity_usd <= 0.0:
            return None
        return self.market_cap_usd / self.liquidity_usd

    @property
    def liquidity_to_fdv_ratio(self) -> float | None:
        if self.fully_diluted_valuation_usd <= 0.0 or self.liquidity_usd < 0.0:
            return None
        return self.liquidity_usd / self.fully_diluted_valuation_usd

    @property
    def absolute_price_change_h24(self) -> float:
        return abs(self.price_change_percentage_h24)


class DexBucketMatrixRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: str
    bucket_label: str
    bucket_minimum: float
    bucket_maximum: float
    count: int
    pass_rate_pct: float
    trades_per_day: float
    average_profit_and_loss_percentage: float
    win_rate_pct: float
    empirical_profit_factor: float
    staled_rate_pct: float
    take_profit_tier_2_rate_pct: float
    catastrophic_rate_pct: float


class DexSweepMatrixRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    axis: str
    configuration_label: str
    selected_count: int
    pass_rate_pct: float
    trades_per_day: float
    average_profit_and_loss_percentage: float
    win_rate_pct: float
    empirical_profit_factor: float
    staled_rate_pct: float
    take_profit_tier_2_rate_pct: float
    catastrophic_rate_pct: float
    rejected_average_profit_and_loss_percentage: float
    average_profit_and_loss_uplift_versus_rejected: float
    average_profit_and_loss_uplift_versus_baseline: float


def parse_comma_separated_floats(raw_value: str) -> list[float]:
    values: list[float] = []
    for fragment in raw_value.split(","):
        normalized = fragment.strip()
        if not normalized:
            continue
        if normalized.lower() in {"inf", "+inf", "none"}:
            values.append(UNBOUNDED_MAXIMUM)
            continue
        values.append(float(normalized))
    if not values:
        raise ValueError("expected at least one float")
    return values


def parse_band_pairs(raw_value: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for fragment in raw_value.split(";"):
        normalized = fragment.strip()
        if not normalized:
            continue
        bounds = [part.strip() for part in normalized.split(":")]
        if len(bounds) != 2:
            raise ValueError(f"invalid band '{normalized}', expected min:max")
        minimum = float("inf") if bounds[0].lower() in {"inf", "+inf"} else float(bounds[0])
        maximum = (
            UNBOUNDED_MAXIMUM
            if bounds[1].lower() in {"inf", "+inf", "none"}
            else float(bounds[1])
        )
        pairs.append((minimum, maximum))
    if not pairs:
        raise ValueError("expected at least one min:max band")
    return pairs


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


def format_bound(value: float) -> str:
    if value >= UNBOUNDED_MAXIMUM / 10.0:
        return "inf"
    if abs(value) >= 1000:
        return f"{value:.0f}"
    return f"{value:g}"


def resolve_feature_value(observation: DexFundamentalsObservation, feature: str) -> float | None:
    if feature == "mcap_to_liq":
        return observation.market_cap_to_liquidity_ratio
    if feature == "age_hours":
        return observation.token_age_hours
    if feature == "liquidity_usd":
        return observation.liquidity_usd
    if feature == "volume_h1_usd":
        return observation.volume_h1_usd
    if feature == "volume_h24_usd":
        return observation.volume_h24_usd
    if feature == "fdv_usd":
        return observation.fully_diluted_valuation_usd
    if feature == "market_cap_usd":
        return observation.market_cap_usd
    if feature == "liq_to_fdv":
        return observation.liquidity_to_fdv_ratio
    if feature == "abs_price_change_h24":
        return observation.absolute_price_change_h24
    if feature == "holding_hours":
        return observation.predicted_holding_time_hours
    raise ValueError(f"unsupported feature '{feature}'")


def observation_passes_band(value: float | None, minimum: float, maximum: float) -> bool:
    if value is None:
        return False
    return minimum <= value <= maximum


def fetch_dex_fundamentals_observations(
        maximum_fetch_count: int,
        lookback_days: float | None,
        include_staled: bool,
) -> list[DexFundamentalsObservation]:
    current_time = get_current_local_datetime()
    lower_bound = (
        current_time - timedelta(days=lookback_days)
        if lookback_days is not None
        else current_time - timedelta(days=3650)
    )

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
                    TradingShadowingVerdict.realized_pnl_usd,
                    TradingShadowingVerdict.is_profitable,
                    TradingShadowingVerdict.resolved_at,
                ),
                joinedload(TradingShadowingVerdict.probe).load_only(
                    TradingShadowingProbe.id,
                    TradingShadowingProbe.market_cap_usd,
                    TradingShadowingProbe.liquidity_usd,
                    TradingShadowingProbe.fully_diluted_valuation_usd,
                    TradingShadowingProbe.token_age_hours,
                    TradingShadowingProbe.volume_h1_usd,
                    TradingShadowingProbe.volume_h24_usd,
                    TradingShadowingProbe.price_change_percentage_m5,
                    TradingShadowingProbe.price_change_percentage_h1,
                    TradingShadowingProbe.price_change_percentage_h6,
                    TradingShadowingProbe.price_change_percentage_h24,
                    TradingShadowingProbe.cortex_inference_summary,
                ),
            )
            .where(TradingShadowingVerdict.exit_reason.is_not(None))
            .where(TradingShadowingVerdict.resolved_at.is_not(None))
            .where(TradingShadowingVerdict.resolved_at >= lower_bound)
            .where(TradingShadowingVerdict.realized_pnl_percentage.is_not(None))
            .order_by(TradingShadowingVerdict.resolved_at.desc())
            .limit(maximum_fetch_count)
        )
        if not include_staled:
            statement = statement.where(TradingShadowingVerdict.exit_reason != STALED_EXIT_REASON)

        verdicts = list(database_session.scalars(statement).unique().all())

        observations: list[DexFundamentalsObservation] = []
        for verdict in verdicts:
            probe = verdict.probe
            if probe is None or verdict.resolved_at is None or verdict.realized_pnl_percentage is None:
                continue

            predicted_holding_time_hours: float | None = None
            cortex_gate_accepted: bool | None = None
            cortex_inference_summary = probe.cortex_inference_summary
            if cortex_inference_summary is not None:
                predicted_holding_time_hours = cortex_inference_summary.predicted_holding_time_minutes / 60.0
                if cortex_inference_summary.gate_verdict is not None:
                    cortex_gate_accepted = bool(cortex_inference_summary.gate_verdict.is_accepted)

            observations.append(
                DexFundamentalsObservation(
                    resolved_at=ensure_timezone_aware(verdict.resolved_at),
                    exit_reason=str(verdict.exit_reason),
                    realized_profit_and_loss_percentage=float(verdict.realized_pnl_percentage),
                    realized_profit_and_loss_usd=float(verdict.realized_pnl_usd or 0.0),
                    is_profitable=(
                        bool(verdict.is_profitable)
                        if verdict.is_profitable is not None
                        else float(verdict.realized_pnl_percentage) > 0.0
                    ),
                    market_cap_usd=float(probe.market_cap_usd),
                    liquidity_usd=float(probe.liquidity_usd),
                    fully_diluted_valuation_usd=float(probe.fully_diluted_valuation_usd),
                    token_age_hours=float(probe.token_age_hours),
                    volume_h1_usd=float(probe.volume_h1_usd),
                    volume_h24_usd=float(probe.volume_h24_usd),
                    price_change_percentage_h24=float(probe.price_change_percentage_h24),
                    price_change_percentage_h1=float(probe.price_change_percentage_h1),
                    price_change_percentage_h6=float(probe.price_change_percentage_h6),
                    price_change_percentage_m5=float(probe.price_change_percentage_m5),
                    predicted_holding_time_hours=predicted_holding_time_hours,
                    cortex_gate_accepted=cortex_gate_accepted,
                )
            )

    observations.reverse()
    return observations


def filter_base_universe(
        observations: list[DexFundamentalsObservation],
        require_cortex_accepted: bool,
) -> list[DexFundamentalsObservation]:
    if not require_cortex_accepted:
        return observations
    return [
        observation
        for observation in observations
        if observation.cortex_gate_accepted is True
    ]


def aggregate_observation_metrics(
        selected: list[DexFundamentalsObservation],
        total_count: int,
        window_days: float,
) -> dict[str, float | int]:
    percentages = [observation.realized_profit_and_loss_percentage for observation in selected]
    selected_count = len(selected)
    staled_count = sum(1 for observation in selected if observation.exit_reason == STALED_EXIT_REASON)
    take_profit_tier_2_count = sum(
        1 for observation in selected if observation.exit_reason == "TAKE_PROFIT_2"
    )
    catastrophic_count = sum(
        1
        for observation in selected
        if observation.exit_reason == STALED_EXIT_REASON
        or observation.realized_profit_and_loss_percentage <= -50.0
    )
    win_count = sum(1 for percentage in percentages if percentage > 0.0)
    safe_window_days = max(window_days, 1e-9)
    return {
        "selected_count": selected_count,
        "pass_rate_pct": 100.0 * selected_count / total_count if total_count > 0 else 0.0,
        "trades_per_day": selected_count / safe_window_days,
        "average_profit_and_loss_percentage": compute_average(percentages),
        "win_rate_pct": 100.0 * win_count / selected_count if selected_count > 0 else 0.0,
        "empirical_profit_factor": compute_empirical_profit_factor(percentages),
        "staled_rate_pct": 100.0 * staled_count / selected_count if selected_count > 0 else 0.0,
        "take_profit_tier_2_rate_pct": (
            100.0 * take_profit_tier_2_count / selected_count if selected_count > 0 else 0.0
        ),
        "catastrophic_rate_pct": (
            100.0 * catastrophic_count / selected_count if selected_count > 0 else 0.0
        ),
    }


def resolve_window_days(observations: list[DexFundamentalsObservation]) -> float:
    if len(observations) < 2:
        return 1.0
    span_seconds = (observations[-1].resolved_at - observations[0].resolved_at).total_seconds()
    return max(span_seconds / 86400.0, 1.0 / 24.0)


def default_bucket_edges(feature: str) -> list[float]:
    if feature == "mcap_to_liq":
        return [0.0, 5.0, 10.0, 20.0, 30.0, 50.0, 100.0, UNBOUNDED_MAXIMUM]
    if feature == "age_hours":
        return [0.0, 1.0, 6.0, 24.0, 72.0, 164.0, 336.0, UNBOUNDED_MAXIMUM]
    if feature == "liquidity_usd":
        return [0.0, 2000.0, 5000.0, 10000.0, 25000.0, 50000.0, 100000.0, UNBOUNDED_MAXIMUM]
    if feature in {"volume_h1_usd", "volume_h24_usd"}:
        return [0.0, 5000.0, 15000.0, 25000.0, 50000.0, 90000.0, 200000.0, UNBOUNDED_MAXIMUM]
    if feature in {"fdv_usd", "market_cap_usd"}:
        return [0.0, 30000.0, 100000.0, 500000.0, 2000000.0, 10000000.0, 30000000.0, UNBOUNDED_MAXIMUM]
    if feature == "liq_to_fdv":
        return [0.0, 0.01, 0.03, 0.05, 0.10, 0.20, 1.0]
    if feature == "abs_price_change_h24":
        return [0.0, 20.0, 50.0, 100.0, 150.0, 300.0, UNBOUNDED_MAXIMUM]
    if feature == "holding_hours":
        return [0.0, 1.0, 2.0, 5.0, 6.0, 10.0, 20.0, UNBOUNDED_MAXIMUM]
    raise ValueError(f"unsupported feature '{feature}'")


def build_bucket_rows(
        observations: list[DexFundamentalsObservation],
        feature: str,
        bucket_edges: list[float] | None,
) -> list[DexBucketMatrixRow]:
    edges = bucket_edges if bucket_edges is not None else default_bucket_edges(feature)
    if len(edges) < 2:
        raise ValueError("bucket edges require at least two values")
    window_days = resolve_window_days(observations)
    total_count = len(observations)
    rows: list[DexBucketMatrixRow] = []
    for index in range(len(edges) - 1):
        minimum = edges[index]
        maximum = edges[index + 1]
        selected = [
            observation
            for observation in observations
            if observation_passes_band(resolve_feature_value(observation, feature), minimum, maximum)
        ]
        metrics = aggregate_observation_metrics(selected, total_count, window_days)
        label = f"[{format_bound(minimum)}, {format_bound(maximum)})"
        rows.append(
            DexBucketMatrixRow(
                feature=feature,
                bucket_label=label,
                bucket_minimum=minimum,
                bucket_maximum=maximum,
                count=int(metrics["selected_count"]),
                pass_rate_pct=float(metrics["pass_rate_pct"]),
                trades_per_day=float(metrics["trades_per_day"]),
                average_profit_and_loss_percentage=float(metrics["average_profit_and_loss_percentage"]),
                win_rate_pct=float(metrics["win_rate_pct"]),
                empirical_profit_factor=float(metrics["empirical_profit_factor"]),
                staled_rate_pct=float(metrics["staled_rate_pct"]),
                take_profit_tier_2_rate_pct=float(metrics["take_profit_tier_2_rate_pct"]),
                catastrophic_rate_pct=float(metrics["catastrophic_rate_pct"]),
            )
        )
    return rows


def select_for_axis_configuration(
        observations: list[DexFundamentalsObservation],
        axis: str,
        configuration: tuple[float, ...],
) -> list[DexFundamentalsObservation]:
    if axis == "liquidity_structure":
        minimum_ratio, maximum_ratio = configuration
        return [
            observation
            for observation in observations
            if observation_passes_band(observation.market_cap_to_liquidity_ratio, minimum_ratio, maximum_ratio)
        ]
    if axis == "age":
        minimum_age, maximum_age = configuration
        return [
            observation
            for observation in observations
            if observation_passes_band(observation.token_age_hours, minimum_age, maximum_age)
        ]
    if axis == "liquidity_min":
        minimum_liquidity = configuration[0]
        return [
            observation
            for observation in observations
            if observation.liquidity_usd >= minimum_liquidity
        ]
    if axis == "volume_h1":
        minimum_volume = configuration[0]
        return [
            observation
            for observation in observations
            if observation.volume_h1_usd >= minimum_volume
        ]
    if axis == "volume_h24":
        minimum_volume = configuration[0]
        return [
            observation
            for observation in observations
            if observation.volume_h24_usd >= minimum_volume
        ]
    if axis == "fdv":
        minimum_fdv, maximum_fdv = configuration
        return [
            observation
            for observation in observations
            if observation_passes_band(observation.fully_diluted_valuation_usd, minimum_fdv, maximum_fdv)
        ]
    if axis == "market_cap":
        minimum_market_cap, maximum_market_cap = configuration
        return [
            observation
            for observation in observations
            if observation_passes_band(observation.market_cap_usd, minimum_market_cap, maximum_market_cap)
        ]
    if axis == "liq_to_fdv":
        minimum_ratio = configuration[0]
        return [
            observation
            for observation in observations
            if observation.liquidity_to_fdv_ratio is not None
            and observation.liquidity_to_fdv_ratio >= minimum_ratio
        ]
    if axis == "momentum_abs_24h":
        maximum_absolute = configuration[0]
        return [
            observation
            for observation in observations
            if observation.absolute_price_change_h24 <= maximum_absolute
        ]
    if axis == "holding_hours":
        minimum_hours, maximum_hours = configuration
        return [
            observation
            for observation in observations
            if observation_passes_band(observation.predicted_holding_time_hours, minimum_hours, maximum_hours)
        ]
    if axis == "combo_ls_holding":
        minimum_ratio, maximum_ratio, minimum_hours, maximum_hours = configuration
        return [
            observation
            for observation in observations
            if observation_passes_band(observation.market_cap_to_liquidity_ratio, minimum_ratio, maximum_ratio)
            and observation_passes_band(observation.predicted_holding_time_hours, minimum_hours, maximum_hours)
        ]
    raise ValueError(f"unsupported axis '{axis}'")


def configuration_label(axis: str, configuration: tuple[float, ...]) -> str:
    if axis in {"liquidity_structure", "age", "fdv", "market_cap", "holding_hours"}:
        return f"[{format_bound(configuration[0])}, {format_bound(configuration[1])}]"
    if axis == "combo_ls_holding":
        return (
            f"mcap/liq[{format_bound(configuration[0])}, {format_bound(configuration[1])}] "
            f"hold[{format_bound(configuration[2])}, {format_bound(configuration[3])}]h"
        )
    if axis in {"liquidity_min", "volume_h1", "volume_h24", "liq_to_fdv"}:
        return f">={format_bound(configuration[0])}"
    if axis == "momentum_abs_24h":
        return f"|d24h|<={format_bound(configuration[0])}"
    return str(configuration)


def default_axis_configurations(axis: str) -> list[tuple[float, ...]]:
    if axis == "liquidity_structure":
        return [
            (5.0, 10.0),
            (10.0, 30.0),
            (10.0, 50.0),
            (10.0, UNBOUNDED_MAXIMUM),
            (20.0, 50.0),
            (0.0, 5.0),
            (50.0, UNBOUNDED_MAXIMUM),
        ]
    if axis == "age":
        return [
            (1.0, 24.0),
            (1.0, 72.0),
            (1.0, 164.0),
            (6.0, 164.0),
            (24.0, 336.0),
            (0.0, 1.0),
        ]
    if axis == "liquidity_min":
        return [(1000.0,), (2500.0,), (5000.0,), (10000.0,), (25000.0,), (50000.0,)]
    if axis == "volume_h1":
        return [(5000.0,), (15000.0,), (25000.0,), (50000.0,), (100000.0,)]
    if axis == "volume_h24":
        return [(25000.0,), (50000.0,), (90000.0,), (150000.0,), (250000.0,)]
    if axis == "fdv":
        return [
            (100000.0, 40000000.0),
            (100000.0, 10000000.0),
            (300000.0, 40000000.0),
            (0.0, 100000.0),
            (10000000.0, UNBOUNDED_MAXIMUM),
        ]
    if axis == "market_cap":
        return [
            (30000.0, 30000000.0),
            (100000.0, 10000000.0),
            (0.0, 30000.0),
            (30000000.0, UNBOUNDED_MAXIMUM),
        ]
    if axis == "liq_to_fdv":
        return [(0.01,), (0.03,), (0.05,), (0.10,)]
    if axis == "momentum_abs_24h":
        return [(50.0,), (100.0,), (150.0,), (300.0,), (UNBOUNDED_MAXIMUM,)]
    if axis == "holding_hours":
        return [
            (0.0, 2.0),
            (2.0, 5.0),
            (2.0, 6.0),
            (2.0, 10.0),
            (5.0, 10.0),
            (10.0, 20.0),
            (20.0, UNBOUNDED_MAXIMUM),
        ]
    if axis == "combo_ls_holding":
        liquidity_structure_bands = [(10.0, 30.0), (10.0, 50.0), (10.0, UNBOUNDED_MAXIMUM)]
        holding_bands = [(2.0, 6.0), (2.0, 10.0), (2.0, 20.0)]
        return [
            (minimum_ratio, maximum_ratio, minimum_hours, maximum_hours)
            for (minimum_ratio, maximum_ratio), (minimum_hours, maximum_hours) in product(
                liquidity_structure_bands,
                holding_bands,
            )
        ]
    raise ValueError(f"unsupported axis '{axis}'")


def build_sweep_rows(
        observations: list[DexFundamentalsObservation],
        axis: str,
        configurations: list[tuple[float, ...]],
        minimum_selected_count: int,
) -> list[DexSweepMatrixRow]:
    window_days = resolve_window_days(observations)
    total_count = len(observations)
    baseline_average = compute_average(
        [observation.realized_profit_and_loss_percentage for observation in observations]
    )
    rows: list[DexSweepMatrixRow] = []
    for configuration in configurations:
        selected = select_for_axis_configuration(observations, axis, configuration)
        if len(selected) < minimum_selected_count:
            continue
        selected_identity_set = {id(observation) for observation in selected}
        rejected = [
            observation
            for observation in observations
            if id(observation) not in selected_identity_set
        ]
        selected_metrics = aggregate_observation_metrics(selected, total_count, window_days)
        rejected_average = compute_average(
            [observation.realized_profit_and_loss_percentage for observation in rejected]
        )
        selected_average = float(selected_metrics["average_profit_and_loss_percentage"])
        rows.append(
            DexSweepMatrixRow(
                axis=axis,
                configuration_label=configuration_label(axis, configuration),
                selected_count=int(selected_metrics["selected_count"]),
                pass_rate_pct=float(selected_metrics["pass_rate_pct"]),
                trades_per_day=float(selected_metrics["trades_per_day"]),
                average_profit_and_loss_percentage=selected_average,
                win_rate_pct=float(selected_metrics["win_rate_pct"]),
                empirical_profit_factor=float(selected_metrics["empirical_profit_factor"]),
                staled_rate_pct=float(selected_metrics["staled_rate_pct"]),
                take_profit_tier_2_rate_pct=float(selected_metrics["take_profit_tier_2_rate_pct"]),
                catastrophic_rate_pct=float(selected_metrics["catastrophic_rate_pct"]),
                rejected_average_profit_and_loss_percentage=rejected_average,
                average_profit_and_loss_uplift_versus_rejected=selected_average - rejected_average,
                average_profit_and_loss_uplift_versus_baseline=selected_average - baseline_average,
            )
        )
    return rows


def render_matrix_cell(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return f"{value:.6f}"
    return str(value)


def format_model_rows_as_padded_text_lines(rows: list[BaseModel]) -> list[str]:
    if not rows:
        return []
    column_keys = list(type(rows[0]).model_fields.keys())
    table: list[list[str]] = [list(column_keys)]
    for row in rows:
        table.append([render_matrix_cell(getattr(row, key)) for key in column_keys])
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


def write_model_rows_csv(rows: list[BaseModel], csv_path: Path) -> None:
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    column_keys = list(type(rows[0]).model_fields.keys())
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=column_keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: getattr(row, key) for key in column_keys})


def attach_log_file() -> Path:
    SWEEP_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = get_current_local_datetime().strftime("%Y%m%d_%H%M%S")
    log_file_path = SWEEP_LOG_DIR / f"dex_fundamentals_sweetspot_scan_{timestamp}.log"
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
            "DEX / fundamentals sweetspot scan over shadowing outcomes: "
            "bucket diagnostics and filter-band sweeps (liquidity structure, age, volume, FDV, ...)"
        ),
        epilog=(
            "Example runs:\n"
            "  Recreate the mcap/liq discovery buckets (includes STALED):\n"
            "    python scripts/dex_fundamentals_sweetspot_scan.py --mode bucket --feature mcap_to_liq "
            "--require-cortex-accepted\n"
            "  Sweep liquidity-structure bands:\n"
            "    python scripts/dex_fundamentals_sweetspot_scan.py --mode sweep --axis liquidity_structure "
            "--require-cortex-accepted --csv ls_sweep.csv\n"
            "  Sweep the live-like combo mcap/liq x holding:\n"
            "    python scripts/dex_fundamentals_sweetspot_scan.py --mode sweep --axis combo_ls_holding "
            "--require-cortex-accepted\n"
            "  Run every single-axis sweep:\n"
            "    python scripts/dex_fundamentals_sweetspot_scan.py --mode sweep --axis all "
            "--require-cortex-accepted\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    argument_parser.add_argument("--mode", choices=("bucket", "sweep"), required=True)
    argument_parser.add_argument(
        "--feature",
        choices=BUCKET_FEATURES,
        default="mcap_to_liq",
        help="Feature for --mode bucket",
    )
    argument_parser.add_argument(
        "--bucket-edges",
        default=None,
        help="Optional comma-separated bucket edges for --mode bucket",
    )
    argument_parser.add_argument(
        "--axis",
        default="liquidity_structure",
        help=f"Sweep axis or 'all' ({', '.join(SWEEP_AXES)})",
    )
    argument_parser.add_argument(
        "--bands",
        default=None,
        help="Optional custom bands for band axes, format 'min:max;min:max' (liquidity_structure/age/fdv/market_cap/holding)",
    )
    argument_parser.add_argument(
        "--thresholds",
        default=None,
        help="Optional comma-separated thresholds for floor/ceiling axes (liquidity_min/volume_*/liq_to_fdv/momentum_abs_24h)",
    )
    argument_parser.add_argument("--lookback-days", type=float, default=None)
    argument_parser.add_argument("--max-fetch", type=int, default=500_000)
    argument_parser.add_argument(
        "--exclude-staled",
        action="store_true",
        help="Drop STALED verdicts (default keeps them — required for mortality analysis)",
    )
    argument_parser.add_argument(
        "--require-cortex-accepted",
        action="store_true",
        help="Restrict to probes whose persisted cortex gate_verdict.is_accepted is true",
    )
    argument_parser.add_argument("--min-n", type=int, default=50)
    argument_parser.add_argument(
        "--rank-by",
        choices=(
            "average_profit_and_loss_percentage",
            "empirical_profit_factor",
            "average_profit_and_loss_uplift_versus_baseline",
            "average_profit_and_loss_uplift_versus_rejected",
            "staled_rate_pct",
        ),
        default="average_profit_and_loss_percentage",
    )
    argument_parser.add_argument("--csv", default=None)
    argument_parser.add_argument("--no-log-file", action="store_true")
    arguments = argument_parser.parse_args()

    if not arguments.no_log_file:
        log_file_path = attach_log_file()
        logger.info("[DEX][FUNDAMENTALS][SWEEP] Log file: %s", log_file_path)

    observations = fetch_dex_fundamentals_observations(
        maximum_fetch_count=arguments.max_fetch,
        lookback_days=arguments.lookback_days,
        include_staled=not arguments.exclude_staled,
    )
    observations = filter_base_universe(
        observations,
        require_cortex_accepted=arguments.require_cortex_accepted,
    )
    logger.info(
        "[DEX][FUNDAMENTALS][SWEEP] Loaded %d observations (lookback=%s, include_staled=%s, cortex_accepted_only=%s)",
        len(observations),
        arguments.lookback_days if arguments.lookback_days is not None else "all",
        not arguments.exclude_staled,
        arguments.require_cortex_accepted,
    )
    if not observations:
        logger.warning("[DEX][FUNDAMENTALS][SWEEP] No observations — aborting")
        return

    baseline_metrics = aggregate_observation_metrics(
        observations,
        len(observations),
        resolve_window_days(observations),
    )
    logger.info(
        "[DEX][FUNDAMENTALS][SWEEP] Baseline — n=%d avg_pnl=%.3f%% pf=%s staled=%.2f%% tp2=%.2f%%",
        baseline_metrics["selected_count"],
        baseline_metrics["average_profit_and_loss_percentage"],
        render_matrix_cell(baseline_metrics["empirical_profit_factor"]),
        baseline_metrics["staled_rate_pct"],
        baseline_metrics["take_profit_tier_2_rate_pct"],
    )

    csv_path = resolve_csv_path(arguments.csv)

    if arguments.mode == "bucket":
        bucket_edges = (
            parse_comma_separated_floats(arguments.bucket_edges)
            if arguments.bucket_edges is not None
            else None
        )
        rows = build_bucket_rows(observations, arguments.feature, bucket_edges)
        for line in format_model_rows_as_padded_text_lines(rows):
            logger.info("%s", line)
        if csv_path is not None:
            write_model_rows_csv(rows, csv_path)
            logger.info("[DEX][FUNDAMENTALS][SWEEP] CSV written: %s", csv_path)
        return

    axis_argument = arguments.axis.strip().lower()
    axes = list(SWEEP_AXES) if axis_argument == "all" else [axis_argument]
    for axis in axes:
        if axis not in SWEEP_AXES:
            raise SystemExit(f"unsupported axis '{axis}'")

        if arguments.bands is not None and axis in {
            "liquidity_structure",
            "age",
            "fdv",
            "market_cap",
            "holding_hours",
        }:
            configurations = [pair for pair in parse_band_pairs(arguments.bands)]
        elif arguments.thresholds is not None and axis in {
            "liquidity_min",
            "volume_h1",
            "volume_h24",
            "liq_to_fdv",
            "momentum_abs_24h",
        }:
            configurations = [(value,) for value in parse_comma_separated_floats(arguments.thresholds)]
        else:
            configurations = default_axis_configurations(axis)

        rows = build_sweep_rows(
            observations,
            axis,
            configurations,
            minimum_selected_count=arguments.min_n,
        )
        reverse = arguments.rank_by != "staled_rate_pct"
        ranked_rows = sorted(rows, key=lambda row: getattr(row, arguments.rank_by), reverse=reverse)

        logger.info("[DEX][FUNDAMENTALS][SWEEP] Axis=%s configurations=%d usable=%d", axis, len(configurations), len(ranked_rows))
        for line in format_model_rows_as_padded_text_lines(ranked_rows):
            logger.info("%s", line)
        if ranked_rows:
            best_row = ranked_rows[0]
            logger.info(
                "[DEX][FUNDAMENTALS][SWEEP] Best %s by %s → %s | avg_pnl=%.3f%% pf=%s staled=%.2f%% n=%d uplift_vs_base=%+.3f",
                axis,
                arguments.rank_by,
                best_row.configuration_label,
                best_row.average_profit_and_loss_percentage,
                render_matrix_cell(best_row.empirical_profit_factor),
                best_row.staled_rate_pct,
                best_row.selected_count,
                best_row.average_profit_and_loss_uplift_versus_baseline,
            )

        if csv_path is not None:
            axis_csv_path = csv_path
            if axis_argument == "all":
                axis_csv_path = csv_path.with_name(f"{csv_path.stem}_{axis}{csv_path.suffix}")
            write_model_rows_csv(ranked_rows, axis_csv_path)
            logger.info("[DEX][FUNDAMENTALS][SWEEP] CSV written: %s", axis_csv_path)


if __name__ == "__main__":
    main()
