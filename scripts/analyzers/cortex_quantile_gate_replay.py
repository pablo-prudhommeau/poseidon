from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import psycopg
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ENV_FILE = Path("V:/opt/poseidon/.env")
BACKEND_PACKAGE_ROOT = ROOT / "backend"
if str(BACKEND_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_PACKAGE_ROOT))

try:
    from dotenv import load_dotenv
except ImportError as dotenv_import_error:
    raise RuntimeError("[ANALYZER] python-dotenv is required to load the deployment environment file") from dotenv_import_error

if not DEPLOYMENT_ENV_FILE.is_file():
    raise RuntimeError(f"[ANALYZER] deployment environment file not found: {DEPLOYMENT_ENV_FILE}")

load_dotenv(DEPLOYMENT_ENV_FILE)

from src.configuration.config import settings
from src.core.trading.cortex.trading_cortex_quantile_gate_service import (
    build_absolute_gate_thresholds,
    compute_quantile,
)

SCORED_PROBES_SQL = """
select p.id,
       p.probed_at,
       (p.cortex_inference_summary->>'model_version') as model_version,
       (p.cortex_inference_summary->>'success_probability')::float as success_probability,
       (p.cortex_inference_summary->>'toxicity_probability')::float as toxicity_probability,
       (p.cortex_inference_summary->>'fragility_probability')::float as fragility_probability,
       (p.cortex_inference_summary->>'expected_profit_and_loss_percentage')::float as expected_profit_and_loss_percentage,
       (p.cortex_inference_summary->>'predicted_holding_time_minutes')::float as predicted_holding_time_minutes,
       v.realized_pnl_usd,
       v.is_profitable,
       v.resolved_at,
       v.exit_reason
from trading_shadowing_probes p
left join trading_shadowing_verdicts v on v.probe_id = p.id
where p.cortex_inference_summary is not null
  and (p.cortex_inference_summary->>'success_probability') is not null
  and (p.cortex_inference_summary->>'toxicity_probability') is not null
  and (p.cortex_inference_summary->>'fragility_probability') is not null
  and (p.cortex_inference_summary->>'expected_profit_and_loss_percentage') is not null
  and (p.cortex_inference_summary->>'predicted_holding_time_minutes') is not null
order by p.probed_at
"""


class ScoredProbeReplayRow(BaseModel):
    model_config = ConfigDict(frozen=True, protected_namespaces=())

    probe_id: int
    probed_at: datetime
    model_version: str
    success_probability: float
    toxicity_probability: float
    fragility_probability: float
    expected_profit_and_loss_percentage: float
    predicted_holding_time_minutes: float
    realized_profit_and_loss_usd: float | None
    is_profitable: bool | None
    resolved_at: datetime | None
    exit_reason: str | None


class QuantileGateReplayArrays(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, protected_namespaces=())

    probe_ids: np.ndarray
    probed_at_epoch_seconds: np.ndarray
    model_versions: np.ndarray
    success_probability: np.ndarray
    toxicity_probability: np.ndarray
    fragility_probability: np.ndarray
    expected_profit_and_loss_percentage: np.ndarray
    predicted_holding_time_minutes: np.ndarray
    realized_profit_and_loss_usd: np.ndarray
    is_resolved: np.ndarray
    is_staled: np.ndarray
    has_mark_to_market_pnl: np.ndarray


class QuantileGatePolicyMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_name: str
    accepted_per_day: float
    evaluated_count: int
    staled_rate_percentage: float
    win_rate_percentage: float
    average_profit_and_loss_usd: float
    total_profit_and_loss_usd: float
    empirical_profit_factor: float
    profit_factor_first_half: float
    profit_factor_second_half: float


class EffectiveQuantileGateThresholds(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    success_probability_threshold: np.ndarray
    toxicity_probability_threshold: np.ndarray
    fragility_probability_threshold: np.ndarray
    derived_from_quantiles: np.ndarray


def load_scored_probe_replay_rows() -> list[ScoredProbeReplayRow]:
    database_name = os.getenv("DATABASE_NAME")
    if database_name is None or database_name.strip() == "":
        raise ValueError("DATABASE_NAME is required to replay the quantile gate")
    with psycopg.connect(
        host=os.getenv("DATABASE_HOST"),
        port=int(os.getenv("DATABASE_PORT", "5432")),
        dbname=database_name,
        user=os.getenv("DATABASE_USER"),
        password=os.getenv("DATABASE_PASSWORD"),
        connect_timeout=30,
    ) as connection:
        database_rows = connection.execute(SCORED_PROBES_SQL).fetchall()

    replay_rows: list[ScoredProbeReplayRow] = []
    for database_row in database_rows:
        model_version = database_row[2]
        if model_version is None or str(model_version).strip() == "":
            continue
        replay_rows.append(
            ScoredProbeReplayRow(
                probe_id=int(database_row[0]),
                probed_at=database_row[1],
                model_version=str(model_version),
                success_probability=float(database_row[3]),
                toxicity_probability=float(database_row[4]),
                fragility_probability=float(database_row[5]),
                expected_profit_and_loss_percentage=float(database_row[6]),
                predicted_holding_time_minutes=float(database_row[7]),
                realized_profit_and_loss_usd=None if database_row[8] is None else float(database_row[8]),
                is_profitable=None if database_row[9] is None else bool(database_row[9]),
                resolved_at=database_row[10],
                exit_reason=None if database_row[11] is None else str(database_row[11]),
            )
        )
    return replay_rows


def build_quantile_gate_replay_arrays(replay_rows: list[ScoredProbeReplayRow]) -> QuantileGateReplayArrays:
    realized_profit_and_loss_usd = np.array(
        [np.nan if row.realized_profit_and_loss_usd is None else row.realized_profit_and_loss_usd for row in replay_rows],
        dtype=np.float64,
    )
    return QuantileGateReplayArrays(
        probe_ids=np.array([row.probe_id for row in replay_rows], dtype=np.int64),
        probed_at_epoch_seconds=np.array([row.probed_at.timestamp() for row in replay_rows], dtype=np.float64),
        model_versions=np.array([row.model_version for row in replay_rows]),
        success_probability=np.array([row.success_probability for row in replay_rows], dtype=np.float64),
        toxicity_probability=np.array([row.toxicity_probability for row in replay_rows], dtype=np.float64),
        fragility_probability=np.array([row.fragility_probability for row in replay_rows], dtype=np.float64),
        expected_profit_and_loss_percentage=np.array(
            [row.expected_profit_and_loss_percentage for row in replay_rows],
            dtype=np.float64,
        ),
        predicted_holding_time_minutes=np.array(
            [row.predicted_holding_time_minutes for row in replay_rows],
            dtype=np.float64,
        ),
        realized_profit_and_loss_usd=realized_profit_and_loss_usd,
        is_resolved=np.array([row.resolved_at is not None for row in replay_rows], dtype=bool),
        is_staled=np.array([row.exit_reason == "STALED" for row in replay_rows], dtype=bool),
        has_mark_to_market_pnl=np.array(
            [
                row.realized_profit_and_loss_usd is not None and row.exit_reason != "STALED"
                for row in replay_rows
            ],
            dtype=bool,
        ),
    )


def compute_effective_quantile_gate_thresholds(
        replay_arrays: QuantileGateReplayArrays,
) -> EffectiveQuantileGateThresholds:
    absolute_thresholds = build_absolute_gate_thresholds()
    probe_count = replay_arrays.probed_at_epoch_seconds.size
    success_probability_threshold = np.full(probe_count, absolute_thresholds.success_probability_threshold, dtype=np.float64)
    toxicity_probability_threshold = np.full(probe_count, absolute_thresholds.toxicity_probability_threshold, dtype=np.float64)
    fragility_probability_threshold = np.full(probe_count, absolute_thresholds.fragility_probability_threshold, dtype=np.float64)
    derived_from_quantiles = np.zeros(probe_count, dtype=bool)

    if not settings.TRADING_CORTEX_QUANTILE_GATE_ENABLED or probe_count == 0:
        return EffectiveQuantileGateThresholds(
            success_probability_threshold=success_probability_threshold,
            toxicity_probability_threshold=toxicity_probability_threshold,
            fragility_probability_threshold=fragility_probability_threshold,
            derived_from_quantiles=derived_from_quantiles,
        )

    start_epoch_seconds = float(replay_arrays.probed_at_epoch_seconds.min())
    end_epoch_seconds = float(replay_arrays.probed_at_epoch_seconds.max())
    refresh_seconds = max(settings.TRADING_CORTEX_QUANTILE_GATE_REFRESH_MINUTES, 1.0) * 60.0
    lookback_seconds = settings.TRADING_CORTEX_QUANTILE_GATE_LOOKBACK_DAYS * 86400.0
    grid = np.arange(start_epoch_seconds, end_epoch_seconds + refresh_seconds, refresh_seconds)

    for bucket_start in grid:
        in_bucket = (
            (replay_arrays.probed_at_epoch_seconds >= bucket_start)
            & (replay_arrays.probed_at_epoch_seconds < bucket_start + refresh_seconds)
        )
        if not in_bucket.any():
            continue
        window = (
            (replay_arrays.probed_at_epoch_seconds >= bucket_start - lookback_seconds)
            & (replay_arrays.probed_at_epoch_seconds < bucket_start)
        )
        candidate_indexes = np.flatnonzero(window)
        if candidate_indexes.size > settings.TRADING_CORTEX_QUANTILE_GATE_MAX_SAMPLE_COUNT:
            candidate_indexes = candidate_indexes[-settings.TRADING_CORTEX_QUANTILE_GATE_MAX_SAMPLE_COUNT:]
        for model_version in np.unique(replay_arrays.model_versions[in_bucket]):
            target = in_bucket & (replay_arrays.model_versions == model_version)
            same_model_indexes = candidate_indexes[replay_arrays.model_versions[candidate_indexes] == model_version]
            if same_model_indexes.size < settings.TRADING_CORTEX_QUANTILE_GATE_MIN_SAMPLE_COUNT:
                continue
            success_probability_threshold[target] = compute_quantile(
                sorted(replay_arrays.success_probability[same_model_indexes].tolist()),
                settings.TRADING_CORTEX_QUANTILE_GATE_SUCCESS_PROBABILITY_QUANTILE,
            )
            toxicity_probability_threshold[target] = compute_quantile(
                sorted(replay_arrays.toxicity_probability[same_model_indexes].tolist()),
                settings.TRADING_CORTEX_QUANTILE_GATE_TOXICITY_PROBABILITY_QUANTILE,
            )
            fragility_probability_threshold[target] = compute_quantile(
                sorted(replay_arrays.fragility_probability[same_model_indexes].tolist()),
                settings.TRADING_CORTEX_QUANTILE_GATE_FRAGILITY_PROBABILITY_QUANTILE,
            )
            derived_from_quantiles[target] = True

    return EffectiveQuantileGateThresholds(
        success_probability_threshold=success_probability_threshold,
        toxicity_probability_threshold=toxicity_probability_threshold,
        fragility_probability_threshold=fragility_probability_threshold,
        derived_from_quantiles=derived_from_quantiles,
    )


def build_live_cortex_gate_acceptance_mask(
        replay_arrays: QuantileGateReplayArrays,
        effective_thresholds: EffectiveQuantileGateThresholds,
        holding_time_minimum_minutes: float,
        holding_time_maximum_minutes: float,
        expected_profit_and_loss_threshold: float,
) -> np.ndarray:
    return (
        (replay_arrays.success_probability >= effective_thresholds.success_probability_threshold)
        & (replay_arrays.toxicity_probability <= effective_thresholds.toxicity_probability_threshold)
        & (replay_arrays.fragility_probability <= effective_thresholds.fragility_probability_threshold)
        & (replay_arrays.expected_profit_and_loss_percentage >= expected_profit_and_loss_threshold)
        & (replay_arrays.predicted_holding_time_minutes >= holding_time_minimum_minutes)
        & (replay_arrays.predicted_holding_time_minutes <= holding_time_maximum_minutes)
    )


def compute_accepted_probe_identifiers(
        replay_arrays: QuantileGateReplayArrays,
        acceptance_mask: np.ndarray,
) -> set[int]:
    return set(int(probe_id) for probe_id in replay_arrays.probe_ids[acceptance_mask].tolist())


def _compute_profit_factor(profit_and_loss_values: np.ndarray) -> float:
    gains = float(profit_and_loss_values[profit_and_loss_values > 0.0].sum())
    losses = float(-profit_and_loss_values[profit_and_loss_values < 0.0].sum())
    if losses <= 0.0:
        return float("inf") if gains > 0.0 else float("nan")
    return gains / losses


def evaluate_quantile_gate_policy(
        policy_name: str,
        replay_rows: list[ScoredProbeReplayRow],
        replay_arrays: QuantileGateReplayArrays,
        acceptance_mask: np.ndarray,
) -> QuantileGatePolicyMetrics:
    span_days = (
        (float(replay_arrays.probed_at_epoch_seconds.max()) - float(replay_arrays.probed_at_epoch_seconds.min()))
        / 86400.0
    )
    accepted_resolved = acceptance_mask & replay_arrays.is_resolved
    evaluated = accepted_resolved & replay_arrays.has_mark_to_market_pnl
    evaluated_count = int(evaluated.sum())
    accepted_resolved_count = int(accepted_resolved.sum())
    staled_rate_percentage = (
        100.0 * float((accepted_resolved & replay_arrays.is_staled).sum()) / max(1, accepted_resolved_count)
    )
    if evaluated_count == 0:
        return QuantileGatePolicyMetrics(
            policy_name=policy_name,
            accepted_per_day=int(acceptance_mask.sum()) / max(span_days, 1e-9),
            evaluated_count=0,
            staled_rate_percentage=staled_rate_percentage,
            win_rate_percentage=float("nan"),
            average_profit_and_loss_usd=float("nan"),
            total_profit_and_loss_usd=float("nan"),
            empirical_profit_factor=float("nan"),
            profit_factor_first_half=float("nan"),
            profit_factor_second_half=float("nan"),
        )

    profit_and_loss_values = replay_arrays.realized_profit_and_loss_usd[evaluated]
    resolution_epoch_seconds = np.array(
        [replay_rows[index].resolved_at.timestamp() for index in np.flatnonzero(evaluated)],
        dtype=np.float64,
    )
    midpoint_epoch_seconds = float(np.median(resolution_epoch_seconds))
    return QuantileGatePolicyMetrics(
        policy_name=policy_name,
        accepted_per_day=int(acceptance_mask.sum()) / max(span_days, 1e-9),
        evaluated_count=evaluated_count,
        staled_rate_percentage=staled_rate_percentage,
        win_rate_percentage=100.0 * float((profit_and_loss_values > 0.0).mean()),
        average_profit_and_loss_usd=float(profit_and_loss_values.mean()),
        total_profit_and_loss_usd=float(profit_and_loss_values.sum()),
        empirical_profit_factor=_compute_profit_factor(profit_and_loss_values),
        profit_factor_first_half=_compute_profit_factor(
            profit_and_loss_values[resolution_epoch_seconds <= midpoint_epoch_seconds]
        ),
        profit_factor_second_half=_compute_profit_factor(
            profit_and_loss_values[resolution_epoch_seconds > midpoint_epoch_seconds]
        ),
    )


def _format_metric(value: float) -> str:
    if np.isnan(value):
        return "nan"
    if np.isinf(value):
        return "inf"
    return f"{value:.3f}"


def main() -> None:
    replay_rows = load_scored_probe_replay_rows()
    if not replay_rows:
        print("No scored probes — nothing to replay")
        return

    replay_arrays = build_quantile_gate_replay_arrays(replay_rows)
    effective_thresholds = compute_effective_quantile_gate_thresholds(replay_arrays)
    derived_count = int(effective_thresholds.derived_from_quantiles.sum())
    fallback_count = int((~effective_thresholds.derived_from_quantiles).sum())

    print(f"Loaded {len(replay_rows)} scored probes from {os.getenv('DATABASE_NAME')}")
    print(
        f"Window: {replay_rows[0].probed_at:%Y-%m-%d} -> {replay_rows[-1].probed_at:%Y-%m-%d} "
        f"resolved={int(replay_arrays.is_resolved.sum())} staled={int(replay_arrays.is_staled.sum())}"
    )
    print(
        f"Quantile gate enabled={settings.TRADING_CORTEX_QUANTILE_GATE_ENABLED} "
        f"derived={derived_count} absolute_fallback={fallback_count}"
    )
    if derived_count > 0:
        derived = effective_thresholds.derived_from_quantiles
        print(
            "Effective success threshold median="
            f"{float(np.nanmedian(effective_thresholds.success_probability_threshold[derived])):.4f} "
            f"[{float(np.nanmin(effective_thresholds.success_probability_threshold[derived])):.4f}, "
            f"{float(np.nanmax(effective_thresholds.success_probability_threshold[derived])):.4f}]"
        )
        print(
            "Effective toxicity threshold median="
            f"{float(np.nanmedian(effective_thresholds.toxicity_probability_threshold[derived])):.4f} "
            f"[{float(np.nanmin(effective_thresholds.toxicity_probability_threshold[derived])):.4f}, "
            f"{float(np.nanmax(effective_thresholds.toxicity_probability_threshold[derived])):.4f}]"
        )
        print(
            "Effective fragility threshold median="
            f"{float(np.nanmedian(effective_thresholds.fragility_probability_threshold[derived])):.4f} "
            f"[{float(np.nanmin(effective_thresholds.fragility_probability_threshold[derived])):.4f}, "
            f"{float(np.nanmax(effective_thresholds.fragility_probability_threshold[derived])):.4f}]"
        )

    holding_time_minimum_minutes = settings.TRADING_CORTEX_HOLDING_TIME_MIN_HOURS * 60.0
    holding_time_maximum_minutes = settings.TRADING_CORTEX_HOLDING_TIME_MAX_HOURS * 60.0
    live_acceptance = build_live_cortex_gate_acceptance_mask(
        replay_arrays=replay_arrays,
        effective_thresholds=effective_thresholds,
        holding_time_minimum_minutes=holding_time_minimum_minutes,
        holding_time_maximum_minutes=holding_time_maximum_minutes,
        expected_profit_and_loss_threshold=settings.TRADING_CORTEX_PNL_THRESHOLD,
    )
    high_throughput_acceptance = build_live_cortex_gate_acceptance_mask(
        replay_arrays=replay_arrays,
        effective_thresholds=effective_thresholds,
        holding_time_minimum_minutes=120.0,
        holding_time_maximum_minutes=240.0,
        expected_profit_and_loss_threshold=0.0,
    )
    absolute_acceptance = (
        (replay_arrays.success_probability >= settings.TRADING_CORTEX_SUCCESS_PROBABILITY_THRESHOLD)
        & (replay_arrays.toxicity_probability <= settings.TRADING_CORTEX_TOXICITY_PROBABILITY_THRESHOLD)
        & (replay_arrays.fragility_probability <= settings.TRADING_CORTEX_FRAGILITY_PROBABILITY_THRESHOLD)
        & (replay_arrays.expected_profit_and_loss_percentage >= settings.TRADING_CORTEX_PNL_THRESHOLD)
        & (replay_arrays.predicted_holding_time_minutes >= holding_time_minimum_minutes)
        & (replay_arrays.predicted_holding_time_minutes <= holding_time_maximum_minutes)
    )

    policies = [
        evaluate_quantile_gate_policy(
            "A. Live quantile gate + settings PnL/holding",
            replay_rows,
            replay_arrays,
            live_acceptance,
        ),
        evaluate_quantile_gate_policy(
            "B. Live quantile gate + PnL>=0 + hold[120,240]",
            replay_rows,
            replay_arrays,
            high_throughput_acceptance,
        ),
        evaluate_quantile_gate_policy(
            "C. Absolute fallback thresholds + settings PnL/holding",
            replay_rows,
            replay_arrays,
            absolute_acceptance,
        ),
    ]

    print("=" * 132)
    print("UNIVERSE: mark-to-market PnL only (STALED excluded from PF / win / avg$ ; staled_rate reported separately)")
    print("=" * 132)
    print(
        f"{'policy':<58} {'acc/day':>8} {'n_eval':>7} {'staled%':>8} {'win%':>6} "
        f"{'avg$':>9} {'total$':>11} {'PF':>6} {'PF_1st':>7} {'PF_2nd':>7}"
    )
    print("-" * 132)
    for policy in policies:
        print(
            f"{policy.policy_name:<58} {policy.accepted_per_day:>8.1f} {policy.evaluated_count:>7} "
            f"{policy.staled_rate_percentage:>8.1f} {_format_metric(policy.win_rate_percentage):>6} "
            f"{_format_metric(policy.average_profit_and_loss_usd):>9} "
            f"{_format_metric(policy.total_profit_and_loss_usd):>11} "
            f"{_format_metric(policy.empirical_profit_factor):>6} "
            f"{_format_metric(policy.profit_factor_first_half):>7} "
            f"{_format_metric(policy.profit_factor_second_half):>7}"
        )
    print("=" * 132)


if __name__ == "__main__":
    main()
