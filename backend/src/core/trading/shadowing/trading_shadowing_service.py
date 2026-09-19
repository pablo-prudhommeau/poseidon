from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Iterable

from pydantic import ValidationError

from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import (
    CHRONICLE_ALL_BUCKET_LABEL,
    CHRONICLE_ALL_VERDICT_SCAN_BATCH_SIZE,
    CHRONICLE_MAX_METRIC_POINTS,
    CHRONICLE_MAX_SELL_CLOUD_POINTS,
    CHRONICLE_MAX_VOLUME_POINTS,
    compute_profit_factor as _compute_profit_factor,
    downsample_series_indices,
    floor_datetime_to_granularity as _floor_datetime_to_granularity,
    iter_chronicle_display_bucket_epoch_milliseconds as _iter_chronicle_display_bucket_epoch_milliseconds,
    resolve_all_chronicle_granularity_seconds,
    sample_evenly_spaced_items,
    to_epoch_milliseconds as _to_epoch_milliseconds,
)
from src.core.trading.shadowing.trading_shadowing_cortex_rollout_timeline import load_cortex_model_rollouts_for_chronicle
from src.core.trading.shadowing.trading_shadowing_regime_gate_timeline import (
    build_regime_gate_timeline_for_metric_timestamps,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingVerdictChronicleBucketConfiguration,
    TradingShadowingVerdictChronicleCortexReliabilityBin,
    TradingShadowingVerdictChroniclePortfolioWalletValuePoint,
    TradingShadowingVerdictChronicleVerdict,
    TradingShadowingVerdictChronicleMetricPoint,
    TradingShadowingVerdictChronicleVolumePoint,
    TradingShadowingVerdictChronicleVerdictPoint,
    TradingShadowingVerdictChronicleSellPoint,
    TradingShadowingVerdictChronicleBucket,
    TradingShadowingVerdictChronicle,
    TradingShadowingVerdictChronicleComputationResult,
)
from src.core.trading.trading_structures import TradingCortexInferenceSnapshot
from src.core.utils.date_utils import (
    ensure_timezone_aware,
    get_current_local_datetime,
)
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_outcome_dao import TradingOutcomeDao
from src.persistence.dao.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading_position_dao import TradingPositionDao
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingOutcome, TradingPosition, TradingShadowingVerdict

logger = get_application_logger(__name__)

_CORTEX_RELIABILITY_BIN_COUNT = 10
_CORTEX_HIGH_CONVICTION_DISTANCE_FROM_HALF = 0.15


def _cortex_holding_time_max_minutes() -> float:
    return settings.TRADING_CORTEX_HOLDING_TIME_MAX_HOURS * 60.0


def _has_complete_cortex_inference(verdict: TradingShadowingVerdictChronicleVerdict) -> bool:
    return (
            verdict.cortex_probability is not None
            and verdict.cortex_toxicity_probability is not None
            and verdict.cortex_expected_pnl_percentage is not None
            and verdict.cortex_predicted_holding_time_minutes is not None
    )


def _compute_cortex_skill_score_percentage(verdicts: list[TradingShadowingVerdictChronicleVerdict]) -> Optional[float]:
    paired = [
        (verdict.cortex_probability, 1.0 if verdict.is_profitable else 0.0)
        for verdict in verdicts
        if _has_complete_cortex_inference(verdict)
    ]
    if not paired:
        return None
    mean_score = sum((2.0 * probability - 1.0) * (2.0 * outcome - 1.0) for probability, outcome in paired) / len(paired)
    return mean_score * 100.0


def _compute_cortex_actionability_metrics(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    paired = [
        (verdict.cortex_probability, 1.0 if verdict.is_profitable else 0.0)
        for verdict in verdicts
        if _has_complete_cortex_inference(verdict)
    ]
    if not paired:
        return None, None, None

    average_prediction_percentage = sum(probability for probability, _ in paired) / len(paired) * 100.0
    empirical_win_rate_percentage = sum(outcome for _, outcome in paired) / len(paired) * 100.0
    calibration_gap_percentage_points = average_prediction_percentage - empirical_win_rate_percentage

    high_conviction = [
        (probability, outcome)
        for probability, outcome in paired
        if abs(probability - 0.5) >= _CORTEX_HIGH_CONVICTION_DISTANCE_FROM_HALF
    ]
    if not high_conviction:
        return calibration_gap_percentage_points, None, 0.0

    high_conviction_hit_count = sum(
        1
        for probability, outcome in high_conviction
        if (probability >= 0.5 and outcome >= 0.5) or (probability < 0.5 and outcome < 0.5)
    )
    high_conviction_accuracy_percentage = high_conviction_hit_count / len(high_conviction) * 100.0
    high_conviction_share_percentage = len(high_conviction) / len(paired) * 100.0
    return calibration_gap_percentage_points, high_conviction_accuracy_percentage, high_conviction_share_percentage


def _is_cortex_gate_accepted(verdict: TradingShadowingVerdictChronicleVerdict) -> bool:
    if not _has_complete_cortex_inference(verdict):
        return False
    assert verdict.cortex_probability is not None
    assert verdict.cortex_toxicity_probability is not None
    assert verdict.cortex_expected_pnl_percentage is not None
    assert verdict.cortex_predicted_holding_time_minutes is not None
    return (
            verdict.cortex_probability >= settings.TRADING_CORTEX_SUCCESS_PROBABILITY_THRESHOLD
            and verdict.cortex_toxicity_probability <= settings.TRADING_CORTEX_TOXICITY_PROBABILITY_THRESHOLD
            and verdict.cortex_expected_pnl_percentage >= settings.TRADING_CORTEX_PNL_THRESHOLD
            and verdict.cortex_predicted_holding_time_minutes <= _cortex_holding_time_max_minutes()
    )


def _compute_cortex_gate_quality_metrics(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
) -> tuple[Optional[float], Optional[float]]:
    inference_complete = [
        verdict
        for verdict in verdicts
        if _has_complete_cortex_inference(verdict)
    ]
    if not inference_complete:
        return None, None

    accepted = [verdict for verdict in inference_complete if _is_cortex_gate_accepted(verdict)]
    pass_rate_percentage = len(accepted) / len(inference_complete) * 100.0
    if not accepted:
        return 0.0, pass_rate_percentage

    precision_percentage = sum(1 for verdict in accepted if verdict.is_profitable) / len(accepted) * 100.0
    return precision_percentage, pass_rate_percentage


def _build_cortex_reliability_diagram(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
) -> list[TradingShadowingVerdictChronicleCortexReliabilityBin]:
    bins: list[list[tuple[float, float]]] = [[] for _ in range(_CORTEX_RELIABILITY_BIN_COUNT)]
    for verdict in verdicts:
        if not _has_complete_cortex_inference(verdict):
            continue
        probability = verdict.cortex_probability
        assert probability is not None
        clamped_probability = max(0.0, min(1.0, probability))
        bin_index = min(_CORTEX_RELIABILITY_BIN_COUNT - 1, int(clamped_probability * _CORTEX_RELIABILITY_BIN_COUNT))
        bins[bin_index].append((clamped_probability, 1.0 if verdict.is_profitable else 0.0))

    result: list[TradingShadowingVerdictChronicleCortexReliabilityBin] = []
    for index, points in enumerate(bins):
        if not points:
            continue
        count = len(points)
        mean_predicted_probability = sum(probability for probability, _ in points) / count
        empirical_win_rate = sum(outcome for _, outcome in points) / count
        result.append(TradingShadowingVerdictChronicleCortexReliabilityBin(
            predicted_probability_bin_center=(index + 0.5) / _CORTEX_RELIABILITY_BIN_COUNT,
            mean_predicted_probability=mean_predicted_probability,
            empirical_win_rate=empirical_win_rate,
            verdict_count=count,
        ))
    return result


def compute_trading_shadowing_verdict_chronicle() -> TradingShadowingVerdictChronicleComputationResult:
    now_local = get_current_local_datetime()
    bucket_configurations = _trading_shadowing_verdict_chronicle_bucket_configurations()
    fetch_end_datetime = _verdict_fetch_end_datetime(now_local, bucket_configurations)
    global_from_datetime = now_local - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)

    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        portfolio_snapshot_dao = TradingPortfolioSnapshotDao(database_session)
        outcome_dao = TradingOutcomeDao(database_session)
        earliest_resolved_at = verdict_dao.retrieve_earliest_resolved_at()
        all_from_datetime = ensure_timezone_aware(earliest_resolved_at) if earliest_resolved_at is not None else global_from_datetime
        if all_from_datetime is None:
            all_from_datetime = global_from_datetime
        sell_from_datetime = min(global_from_datetime, all_from_datetime)
        resolved_verdicts = verdict_dao.retrieve_resolved_in_window(
            start_datetime=global_from_datetime,
            end_datetime=fetch_end_datetime,
            limit_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
        )
        verdicts = _convert_verdicts(resolved_verdicts)
        portfolio_snapshots = _load_portfolio_snapshots_for_chronicle(
            portfolio_snapshot_dao=portfolio_snapshot_dao,
            global_from_datetime=sell_from_datetime,
            fetch_end_datetime=fetch_end_datetime,
        )
        closed_sell_outcomes = outcome_dao.retrieve_closed_sells_in_window(
            start_datetime=sell_from_datetime,
            end_datetime=fetch_end_datetime,
        )
        evaluation_ids: list[int] = [outcome.evaluation_id for outcome in closed_sell_outcomes]
        position_dao = TradingPositionDao(database_session)
        positions: list[TradingPosition] = position_dao.retrieve_by_evaluation_ids(evaluation_ids)
        opened_at_by_evaluation_id: dict[int, datetime] = _earliest_opened_at_by_evaluation_id(positions)
        breakeven_arm_by_evaluation_id: dict[int, tuple[datetime, float]] = _breakeven_arm_by_evaluation_id(positions)
        sell_points = _convert_closed_sells_to_chronicle_points(
            outcomes=closed_sell_outcomes,
            opened_at_by_evaluation_id=opened_at_by_evaluation_id,
            breakeven_arm_by_evaluation_id=breakeven_arm_by_evaluation_id,
        )
        all_bucket = _build_all_chronicle_bucket(
            verdict_dao=verdict_dao,
            portfolio_wallet_value_points=portfolio_snapshots,
            sell_points=sell_points,
            from_datetime=all_from_datetime,
            to_datetime=fetch_end_datetime,
            as_of_datetime=now_local,
        )

    logger.info(
        "[TRADING][SHADOWING][HISTORY] Full chronicle built — verdict_count=%d bucket_layer_count=%d sell_cloud_count=%d",
        len(verdicts),
        len(bucket_configurations) + 1,
        len(sell_points),
    )
    chronicle = _build_trading_shadowing_verdict_chronicle(
        verdicts,
        portfolio_snapshots,
        sell_points,
        now_local,
        bucket_configurations,
        fetch_end_datetime,
        global_from_datetime,
    )
    chronicle.buckets.append(all_bucket)
    return TradingShadowingVerdictChronicleComputationResult(
        chronicle=chronicle,
        verdicts=verdicts,
    )


def _build_trading_shadowing_verdict_chronicle(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        portfolio_wallet_value_points: list[TradingShadowingVerdictChroniclePortfolioWalletValuePoint],
        sell_points: list[TradingShadowingVerdictChronicleSellPoint],
        now_local: datetime,
        bucket_configurations: list[TradingShadowingVerdictChronicleBucketConfiguration],
        fetch_end_datetime: datetime,
        global_from_datetime: datetime,
) -> TradingShadowingVerdictChronicle:
    buckets: list[TradingShadowingVerdictChronicleBucket] = []
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS
    for bucket_configuration in bucket_configurations:
        bucket_from_datetime = max(
            global_from_datetime,
            now_local - bucket_configuration.lookback,
        )
        bucket_to_datetime = now_local + timedelta(
            seconds=bucket_configuration.granularity_seconds * max(0, trailing),
        )
        buckets.append(_build_bucket(
            verdicts=verdicts,
            portfolio_wallet_value_points=portfolio_wallet_value_points,
            sell_points=sell_points,
            bucket_configuration=bucket_configuration,
            from_datetime=bucket_from_datetime,
            to_datetime=bucket_to_datetime,
            as_of_datetime=now_local,
        ))

    return TradingShadowingVerdictChronicle(
        generated_at=now_local,
        as_of=now_local,
        from_datetime=global_from_datetime,
        to_datetime=fetch_end_datetime,
        total_verdicts_considered=len(verdicts),
        source="computed",
        buckets=buckets,
        cortex_model_rollouts=load_cortex_model_rollouts_for_chronicle(global_from_datetime, fetch_end_datetime),
    )


def _build_bucket(
        verdicts: Iterable[TradingShadowingVerdictChronicleVerdict],
        portfolio_wallet_value_points: list[TradingShadowingVerdictChroniclePortfolioWalletValuePoint],
        sell_points: list[TradingShadowingVerdictChronicleSellPoint],
        bucket_configuration: TradingShadowingVerdictChronicleBucketConfiguration,
        from_datetime: datetime,
        to_datetime: datetime,
        as_of_datetime: datetime,
        history_from_datetime: Optional[datetime] = None,
) -> TradingShadowingVerdictChronicleBucket:
    window_from = ensure_timezone_aware(from_datetime)
    window_to = ensure_timezone_aware(to_datetime)
    as_of_aware = ensure_timezone_aware(as_of_datetime)
    assert window_from is not None and window_to is not None and as_of_aware is not None

    all_verdicts = list(verdicts)
    grouped_verdicts: dict[int, list[TradingShadowingVerdictChronicleVerdict]] = defaultdict(list)
    bounded_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []

    for verdict in all_verdicts:
        resolved_at = ensure_timezone_aware(verdict.resolved_at)
        if resolved_at is None:
            continue
        if resolved_at < window_from or resolved_at > window_to:
            continue
        bucket_start = _floor_datetime_to_granularity(resolved_at, bucket_configuration.granularity_seconds)
        grouped_verdicts[_to_epoch_milliseconds(bucket_start)].append(verdict)
        if resolved_at <= as_of_aware:
            bounded_verdicts.append(verdict)

    display_bucket_timestamps = _iter_chronicle_display_bucket_epoch_milliseconds(
        window_from,
        as_of_aware,
        bucket_configuration.granularity_seconds,
    )

    metric_points: list[TradingShadowingVerdictChronicleMetricPoint] = []
    volume_points: list[TradingShadowingVerdictChronicleVolumePoint] = []
    sorted_portfolio_wallet_value_points: list[TradingShadowingVerdictChroniclePortfolioWalletValuePoint] = sorted(
        portfolio_wallet_value_points,
        key=lambda portfolio_wallet_value_point: portfolio_wallet_value_point.timestamp_milliseconds,
    )
    portfolio_wallet_value_point_index = 0
    latest_known_portfolio_wallet_value: float = (
        sorted_portfolio_wallet_value_points[0].total_wallet_value_usd
        if sorted_portfolio_wallet_value_points
        else 0.0
    )

    for bucket_timestamp in display_bucket_timestamps:
        while portfolio_wallet_value_point_index < len(sorted_portfolio_wallet_value_points):
            portfolio_wallet_value_point = sorted_portfolio_wallet_value_points[portfolio_wallet_value_point_index]
            if portfolio_wallet_value_point.timestamp_milliseconds > bucket_timestamp:
                break
            latest_known_portfolio_wallet_value = portfolio_wallet_value_point.total_wallet_value_usd
            portfolio_wallet_value_point_index += 1

        items = grouped_verdicts.get(bucket_timestamp, [])
        verdict_count = len(items)
        volume_points.append(TradingShadowingVerdictChronicleVolumePoint(
            timestamp_milliseconds=bucket_timestamp,
            verdict_count=verdict_count,
        ))
        if verdict_count == 0:
            metric_points.append(TradingShadowingVerdictChronicleMetricPoint(
                timestamp_milliseconds=bucket_timestamp,
                average_pnl_percentage=0.0,
                average_win_rate_percentage=0.0,
                expected_value_per_trade_usd=0.0,
                total_wallet_value_usd=latest_known_portfolio_wallet_value,
                closed_verdicts_per_hour=0.0,
                profit_factor=0.0,
            ))
            continue

        metric_points.append(_build_chronicle_metric_point_for_verdict_items(
            bucket_timestamp=bucket_timestamp,
            items=items,
            latest_known_portfolio_wallet_value=latest_known_portfolio_wallet_value,
            granularity_seconds=bucket_configuration.granularity_seconds,
        ))

    cloud_source = _sample_cloud_points(
        sorted(bounded_verdicts, key=lambda verdict: verdict.resolved_at),
        settings.TRADING_SHADOWING_HISTORY_MAX_CLOUD_POINTS_PER_BUCKET,
    )
    verdict_cloud = sorted(
        (
            TradingShadowingVerdictChronicleVerdictPoint(
                verdict_id=chronicle_verdict.id,
                timestamp_milliseconds=_to_epoch_milliseconds(chronicle_verdict.resolved_at),
                pnl_percentage=chronicle_verdict.realized_pnl_percentage,
                pnl_usd=chronicle_verdict.realized_pnl_usd,
                exit_reason=chronicle_verdict.exit_reason,
                order_notional_usd=chronicle_verdict.order_notional_value_usd,
                point_size=_clamp_point_size(chronicle_verdict.order_notional_value_usd),
                is_profitable=chronicle_verdict.is_profitable,
                cortex_probability=chronicle_verdict.cortex_probability,
            )
            for chronicle_verdict in cloud_source
        ),
        key=lambda payload: (payload.timestamp_milliseconds, payload.verdict_id),
    )

    regime_gate = build_regime_gate_timeline_for_metric_timestamps(
        verdicts=all_verdicts,
        as_of_datetime=as_of_datetime,
        metric_timestamps_milliseconds=display_bucket_timestamps,
        history_from_datetime=history_from_datetime,
    )
    cortex_reliability_diagram = _build_cortex_reliability_diagram(bounded_verdicts)
    sell_cloud = _sell_cloud_for_window(
        sell_points=sell_points,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        as_of_datetime=as_of_datetime,
    )

    return TradingShadowingVerdictChronicleBucket(
        bucket_label=bucket_configuration.label,
        granularity_seconds=bucket_configuration.granularity_seconds,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        metrics=metric_points,
        volumes=volume_points,
        verdict_cloud=verdict_cloud,
        sell_cloud=sell_cloud,
        cortex_reliability_diagram=cortex_reliability_diagram,
        regime_gate=regime_gate,
    )


def _convert_trading_shadowing_verdict_to_chronicle_verdict(
        verdict: TradingShadowingVerdict,
) -> Optional[TradingShadowingVerdictChronicleVerdict]:
    resolved_at = ensure_timezone_aware(verdict.resolved_at)
    if resolved_at is None:
        return None
    if verdict.realized_pnl_percentage is None or verdict.realized_pnl_usd is None:
        return None
    if verdict.is_profitable is None:
        return None

    cortex_probability: Optional[float] = None
    cortex_toxicity_probability: Optional[float] = None
    cortex_expected_pnl_percentage: Optional[float] = None
    cortex_predicted_holding_time_minutes: Optional[float] = None
    if verdict.probe.cortex_inference_summary is not None:
        try:
            cortex_inference_snapshot = TradingCortexInferenceSnapshot.model_validate(verdict.probe.cortex_inference_summary)
            cortex_probability = cortex_inference_snapshot.success_probability
            cortex_toxicity_probability = cortex_inference_snapshot.toxicity_probability
            cortex_expected_pnl_percentage = cortex_inference_snapshot.expected_profit_and_loss_percentage
            cortex_predicted_holding_time_minutes = cortex_inference_snapshot.predicted_holding_time_minutes
        except ValidationError:
            logger.debug(
                "[TRADING][SHADOWING][HISTORY][CORTEX] Ignoring incomplete legacy cortex_inference_summary for verdict_id=%s",
                verdict.id,
            )

    return TradingShadowingVerdictChronicleVerdict(
        id=verdict.id,
        resolved_at=resolved_at,
        realized_pnl_percentage=verdict.realized_pnl_percentage,
        realized_pnl_usd=verdict.realized_pnl_usd,
        is_profitable=bool(verdict.is_profitable),
        exit_reason=verdict.exit_reason or "UNRESOLVED",
        order_notional_value_usd=verdict.probe.order_notional_value_usd,
        cortex_probability=cortex_probability,
        cortex_toxicity_probability=cortex_toxicity_probability,
        cortex_expected_pnl_percentage=cortex_expected_pnl_percentage,
        cortex_predicted_holding_time_minutes=cortex_predicted_holding_time_minutes,
    )


def _trading_shadowing_verdict_chronicle_bucket_configurations() -> list[TradingShadowingVerdictChronicleBucketConfiguration]:
    return [
        TradingShadowingVerdictChronicleBucketConfiguration(label="last_30m_1m", lookback=timedelta(minutes=30), granularity_seconds=60),
        TradingShadowingVerdictChronicleBucketConfiguration(label="last_24h_1h", lookback=timedelta(hours=24), granularity_seconds=3600),
        TradingShadowingVerdictChronicleBucketConfiguration(label="last_7d_15m", lookback=timedelta(days=7), granularity_seconds=900),
        TradingShadowingVerdictChronicleBucketConfiguration(label="last_30d_30m", lookback=timedelta(days=30), granularity_seconds=1800),
    ]


def _verdict_fetch_end_datetime(
        as_of_datetime: datetime,
        bucket_configurations: list[TradingShadowingVerdictChronicleBucketConfiguration],
) -> datetime:
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS
    if trailing <= 0 or not bucket_configurations:
        return as_of_datetime
    max_granularity_seconds = max(configuration.granularity_seconds for configuration in bucket_configurations)
    return as_of_datetime + timedelta(seconds=max_granularity_seconds * trailing)


def _convert_verdicts(verdicts: list[TradingShadowingVerdict]) -> list[TradingShadowingVerdictChronicleVerdict]:
    chronicle_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []
    for verdict in verdicts:
        chronicle_verdict = _convert_trading_shadowing_verdict_to_chronicle_verdict(verdict)
        if chronicle_verdict is not None:
            chronicle_verdicts.append(chronicle_verdict)
    return chronicle_verdicts


def _trim_verdicts_for_window(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        global_from_datetime: datetime,
        fetch_end_datetime: datetime,
        max_count: int,
) -> list[TradingShadowingVerdictChronicleVerdict]:
    window_from = ensure_timezone_aware(global_from_datetime)
    window_to = ensure_timezone_aware(fetch_end_datetime)
    assert window_from is not None and window_to is not None

    filtered: list[TradingShadowingVerdictChronicleVerdict] = []
    for chronicle_verdict in verdicts:
        resolved_at = ensure_timezone_aware(chronicle_verdict.resolved_at)
        if resolved_at is None:
            continue
        if resolved_at < window_from or resolved_at > window_to:
            continue
        filtered.append(chronicle_verdict)
    filtered.sort(key=lambda chronicle_verdict: chronicle_verdict.resolved_at)
    if len(filtered) <= max_count:
        return filtered
    return filtered[-max_count:]


def _build_chronicle_metric_point_for_verdict_items(
        bucket_timestamp: int,
        items: list[TradingShadowingVerdictChronicleVerdict],
        latest_known_portfolio_wallet_value: float,
        granularity_seconds: int,
) -> TradingShadowingVerdictChronicleMetricPoint:
    verdict_count = len(items)
    pnl_usd_values = [item.realized_pnl_usd for item in items]
    pnl_percentage_values = [item.realized_pnl_percentage for item in items]
    complete_cortex_items = [item for item in items if _has_complete_cortex_inference(item)]
    cortex_probabilities = [
        item.cortex_probability
        for item in complete_cortex_items
        if item.cortex_probability is not None
    ]
    cortex_predicted_holding_times_minutes = [
        item.cortex_predicted_holding_time_minutes
        for item in complete_cortex_items
        if item.cortex_predicted_holding_time_minutes is not None
    ]
    win_count = sum(1 for item in items if item.is_profitable)
    gross_profit_usd = sum(value for value in pnl_usd_values if value > 0.0)
    gross_loss_usd = abs(sum(value for value in pnl_usd_values if value < 0.0))

    average_cortex_prediction_win_rate_percentage = None
    if len(cortex_probabilities) > 0:
        average_cortex_prediction_win_rate_percentage = (sum(cortex_probabilities) / len(cortex_probabilities)) * 100.0
    average_cortex_predicted_holding_time_minutes = None
    if cortex_predicted_holding_times_minutes:
        average_cortex_predicted_holding_time_minutes = (
                sum(cortex_predicted_holding_times_minutes) / len(cortex_predicted_holding_times_minutes)
        )

    (
        cortex_calibration_gap_percentage_points,
        cortex_high_conviction_accuracy_percentage,
        cortex_high_conviction_share_percentage,
    ) = _compute_cortex_actionability_metrics(items)
    (
        cortex_gate_precision_percentage,
        cortex_gate_pass_rate_percentage,
    ) = _compute_cortex_gate_quality_metrics(items)

    return TradingShadowingVerdictChronicleMetricPoint(
        timestamp_milliseconds=bucket_timestamp,
        average_pnl_percentage=sum(pnl_percentage_values) / verdict_count,
        average_win_rate_percentage=(win_count / verdict_count) * 100.0,
        expected_value_per_trade_usd=sum(pnl_usd_values) / verdict_count,
        total_wallet_value_usd=latest_known_portfolio_wallet_value,
        closed_verdicts_per_hour=_compute_closed_verdicts_per_hour(verdict_count, granularity_seconds),
        profit_factor=_compute_profit_factor(gross_profit_usd, gross_loss_usd),
        average_cortex_prediction_win_rate_percentage=average_cortex_prediction_win_rate_percentage,
        average_cortex_predicted_holding_time_minutes=average_cortex_predicted_holding_time_minutes,
        cortex_skill_score_percentage=_compute_cortex_skill_score_percentage(items),
        cortex_calibration_gap_percentage_points=cortex_calibration_gap_percentage_points,
        cortex_high_conviction_accuracy_percentage=cortex_high_conviction_accuracy_percentage,
        cortex_high_conviction_share_percentage=cortex_high_conviction_share_percentage,
        cortex_gate_precision_percentage=cortex_gate_precision_percentage,
        cortex_gate_pass_rate_percentage=cortex_gate_pass_rate_percentage,
    )


def _compute_closed_verdicts_per_hour(verdict_count: int, granularity_seconds: int) -> float:
    if granularity_seconds <= 0:
        return 0.0
    return verdict_count * 3600.0 / float(granularity_seconds)


def _load_portfolio_snapshots_for_chronicle(
        portfolio_snapshot_dao: TradingPortfolioSnapshotDao,
        global_from_datetime: datetime,
        fetch_end_datetime: datetime,
) -> list[TradingShadowingVerdictChroniclePortfolioWalletValuePoint]:
    chronicle_portfolio_wallet_value_points: list[TradingShadowingVerdictChroniclePortfolioWalletValuePoint] = []
    snapshots_in_window = portfolio_snapshot_dao.retrieve_snapshots_in_window(
        start_datetime=global_from_datetime,
        end_datetime=fetch_end_datetime,
    )
    for snapshot in snapshots_in_window:
        chronicle_portfolio_wallet_value_points.append(TradingShadowingVerdictChroniclePortfolioWalletValuePoint(
            timestamp_milliseconds=int(snapshot.created_at.timestamp() * 1000),
            total_wallet_value_usd=snapshot.total_equity_value,
        ))
    return sorted(
        chronicle_portfolio_wallet_value_points,
        key=lambda chronicle_portfolio_wallet_value_point: chronicle_portfolio_wallet_value_point.timestamp_milliseconds,
    )


def _sample_cloud_points(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        limit_count: int,
) -> list[TradingShadowingVerdictChronicleVerdict]:
    return sample_evenly_spaced_items(verdicts, limit_count)


def _clamp_point_size(order_notional_usd: float) -> float:
    if order_notional_usd <= 0:
        return 3.0
    return max(3.0, min(18.0, (order_notional_usd ** 0.5) / 2.0))


def _earliest_opened_at_by_evaluation_id(
        positions: list[TradingPosition],
) -> dict[int, datetime]:
    opened_at_by_evaluation_id: dict[int, datetime] = {}
    for position in positions:
        evaluation_id = position.evaluation_id
        opened_at = ensure_timezone_aware(position.opened_at)
        if opened_at is None:
            continue
        if evaluation_id in opened_at_by_evaluation_id:
            existing_opened_at = opened_at_by_evaluation_id[evaluation_id]
            if opened_at < existing_opened_at:
                opened_at_by_evaluation_id[evaluation_id] = opened_at
            continue
        opened_at_by_evaluation_id[evaluation_id] = opened_at
    return opened_at_by_evaluation_id


def _compute_breakeven_arm_pnl_percentage(position: TradingPosition) -> float:
    entry_price = position.entry_price
    breakeven_arm_price = position.breakeven_arm_price
    if entry_price > 0 and breakeven_arm_price > 0:
        return (breakeven_arm_price / entry_price - 1.0) * 100.0
    return settings.TRADING_BREAKEVEN_ARM_FRACTION * 100.0


def _breakeven_arm_by_evaluation_id(
        positions: list[TradingPosition],
) -> dict[int, tuple[datetime, float]]:
    breakeven_arm_by_evaluation_id: dict[int, tuple[datetime, float]] = {}
    for position in positions:
        evaluation_id = position.evaluation_id
        armed_at = ensure_timezone_aware(position.breakeven_stop_armed_at)
        if armed_at is None:
            continue
        arm_pnl_percentage = _compute_breakeven_arm_pnl_percentage(position)
        if evaluation_id in breakeven_arm_by_evaluation_id:
            existing_armed_at = breakeven_arm_by_evaluation_id[evaluation_id][0]
            if armed_at < existing_armed_at:
                breakeven_arm_by_evaluation_id[evaluation_id] = (armed_at, arm_pnl_percentage)
            continue
        breakeven_arm_by_evaluation_id[evaluation_id] = (armed_at, arm_pnl_percentage)
    return breakeven_arm_by_evaluation_id


def _resolve_in_window_breakeven_arm(
        opened_at_milliseconds: int,
        closed_at_milliseconds: int,
        breakeven_arm: tuple[datetime, float] | None,
) -> tuple[int | None, float | None]:
    if breakeven_arm is None:
        return None, None
    armed_at, arm_pnl_percentage = breakeven_arm
    armed_at_milliseconds = _to_epoch_milliseconds(armed_at)
    if opened_at_milliseconds < armed_at_milliseconds < closed_at_milliseconds and math.isfinite(arm_pnl_percentage):
        return armed_at_milliseconds, arm_pnl_percentage
    return None, None


def _convert_closed_sells_to_chronicle_points(
        outcomes: list[TradingOutcome],
        opened_at_by_evaluation_id: dict[int, datetime],
        breakeven_arm_by_evaluation_id: dict[int, tuple[datetime, float]],
) -> list[TradingShadowingVerdictChronicleSellPoint]:
    sell_points: list[TradingShadowingVerdictChronicleSellPoint] = []
    omitted_without_opened_at = 0
    for outcome in outcomes:
        trade = outcome.trade
        if trade is None:
            continue
        occurred_at = ensure_timezone_aware(outcome.occurred_at)
        if occurred_at is None:
            continue
        if outcome.evaluation_id in opened_at_by_evaluation_id:
            opened_at = ensure_timezone_aware(opened_at_by_evaluation_id[outcome.evaluation_id])
        elif outcome.holding_duration_minutes > 0:
            opened_at = occurred_at - timedelta(minutes=outcome.holding_duration_minutes)
        else:
            omitted_without_opened_at += 1
            continue
        if opened_at is None:
            omitted_without_opened_at += 1
            continue
        opened_at_milliseconds = _to_epoch_milliseconds(opened_at)
        timestamp_milliseconds = _to_epoch_milliseconds(occurred_at)
        if opened_at_milliseconds >= timestamp_milliseconds:
            omitted_without_opened_at += 1
            continue
        execution_status = trade.execution_status.value
        if outcome.evaluation_id in breakeven_arm_by_evaluation_id:
            breakeven_arm = breakeven_arm_by_evaluation_id[outcome.evaluation_id]
        else:
            breakeven_arm = None
        resolved_breakeven_arm = _resolve_in_window_breakeven_arm(
            opened_at_milliseconds=opened_at_milliseconds,
            closed_at_milliseconds=timestamp_milliseconds,
            breakeven_arm=breakeven_arm,
        )
        sell_points.append(TradingShadowingVerdictChronicleSellPoint(
            trade_id=trade.id,
            timestamp_milliseconds=timestamp_milliseconds,
            opened_at_milliseconds=opened_at_milliseconds,
            pnl_percentage=outcome.realized_profit_and_loss_percentage,
            pnl_usd=outcome.realized_profit_and_loss_usd,
            is_profitable=bool(outcome.is_profitable),
            token_symbol=trade.token_symbol,
            execution_status=execution_status,
            blockchain_network=trade.blockchain_network,
            token_address=trade.token_address,
            breakeven_stop_armed_at_milliseconds=resolved_breakeven_arm[0],
            breakeven_arm_pnl_percentage=resolved_breakeven_arm[1],
        ))
    logger.debug(
        "[TRADING][SHADOWING][HISTORY] Converted closed sells to chronicle points — sell_count=%d omitted_without_opened_at=%d",
        len(sell_points),
        omitted_without_opened_at,
    )
    return sell_points


def _sell_cloud_for_window(
        sell_points: list[TradingShadowingVerdictChronicleSellPoint],
        from_datetime: datetime,
        to_datetime: datetime,
        as_of_datetime: datetime,
) -> list[TradingShadowingVerdictChronicleSellPoint]:
    window_from = ensure_timezone_aware(from_datetime)
    window_to = ensure_timezone_aware(to_datetime)
    as_of_aware = ensure_timezone_aware(as_of_datetime)
    if window_from is None or window_to is None or as_of_aware is None:
        raise ValueError("Chronicle sell cloud window datetimes must be timezone-aware")
    window_from_milliseconds = _to_epoch_milliseconds(window_from)
    window_to_milliseconds = _to_epoch_milliseconds(min(window_to, as_of_aware))
    filtered_sell_points = [
        sell_point
        for sell_point in sell_points
        if window_from_milliseconds <= sell_point.timestamp_milliseconds <= window_to_milliseconds
    ]
    return sample_evenly_spaced_items(filtered_sell_points, CHRONICLE_MAX_SELL_CLOUD_POINTS)


def _load_all_chronicle_verdicts(
        verdict_dao: TradingShadowingVerdictDao,
        from_datetime: datetime,
        to_datetime: datetime,
) -> list[TradingShadowingVerdictChronicleVerdict]:
    chronicle_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []
    after_resolved_at: Optional[datetime] = None
    after_id: int = 0
    while True:
        batch = verdict_dao.retrieve_resolved_in_window_after_resolved_cursor(
            start_datetime=from_datetime,
            end_datetime=to_datetime,
            after_resolved_at=after_resolved_at,
            after_id=after_id,
            limit_count=CHRONICLE_ALL_VERDICT_SCAN_BATCH_SIZE,
        )
        if not batch:
            break
        chronicle_verdicts.extend(_convert_verdicts(batch))
        last_verdict = batch[-1]
        after_resolved_at = last_verdict.resolved_at
        after_id = last_verdict.id
        if len(batch) < CHRONICLE_ALL_VERDICT_SCAN_BATCH_SIZE:
            break
    logger.info(
        "[TRADING][SHADOWING][HISTORY] All-range verdict scan complete — verdict_count=%d",
        len(chronicle_verdicts),
    )
    return chronicle_verdicts


def _downsample_chronicle_bucket_series(
        chronicle_bucket: TradingShadowingVerdictChronicleBucket,
) -> TradingShadowingVerdictChronicleBucket:
    metric_indices = downsample_series_indices(len(chronicle_bucket.metrics), CHRONICLE_MAX_METRIC_POINTS)
    volume_indices = downsample_series_indices(len(chronicle_bucket.volumes), CHRONICLE_MAX_VOLUME_POINTS)
    downsampled_metrics = [chronicle_bucket.metrics[index] for index in metric_indices]
    downsampled_volumes = [chronicle_bucket.volumes[index] for index in volume_indices]
    regime_gate_by_timestamp = {
        regime_gate_point.timestamp_milliseconds: regime_gate_point
        for regime_gate_point in chronicle_bucket.regime_gate
    }
    downsampled_regime_gate = [
        regime_gate_by_timestamp[metric_point.timestamp_milliseconds]
        for metric_point in downsampled_metrics
        if metric_point.timestamp_milliseconds in regime_gate_by_timestamp
    ]
    return chronicle_bucket.model_copy(
        update={
            "metrics": downsampled_metrics,
            "volumes": downsampled_volumes,
            "regime_gate": downsampled_regime_gate,
        }
    )


def _build_all_chronicle_bucket(
        verdict_dao: TradingShadowingVerdictDao,
        portfolio_wallet_value_points: list[TradingShadowingVerdictChroniclePortfolioWalletValuePoint],
        sell_points: list[TradingShadowingVerdictChronicleSellPoint],
        from_datetime: datetime,
        to_datetime: datetime,
        as_of_datetime: datetime,
) -> TradingShadowingVerdictChronicleBucket:
    from_aware = ensure_timezone_aware(from_datetime)
    as_of_aware = ensure_timezone_aware(as_of_datetime)
    assert from_aware is not None and as_of_aware is not None
    span_seconds = max(0.0, (as_of_aware - from_aware).total_seconds())
    granularity_seconds = resolve_all_chronicle_granularity_seconds(span_seconds)
    bucket_configuration = TradingShadowingVerdictChronicleBucketConfiguration(
        label=CHRONICLE_ALL_BUCKET_LABEL,
        lookback=timedelta(seconds=span_seconds) if span_seconds > 0 else timedelta(days=1),
        granularity_seconds=granularity_seconds,
    )
    all_verdicts = _load_all_chronicle_verdicts(
        verdict_dao=verdict_dao,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
    )
    all_bucket = _build_bucket(
        verdicts=all_verdicts,
        portfolio_wallet_value_points=portfolio_wallet_value_points,
        sell_points=sell_points,
        bucket_configuration=bucket_configuration,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        as_of_datetime=as_of_datetime,
        history_from_datetime=from_datetime,
    )
    downsampled_bucket = _downsample_chronicle_bucket_series(all_bucket)
    logger.info(
        "[TRADING][SHADOWING][HISTORY] All-range bucket built — granularity_seconds=%d metric_count=%d volume_count=%d verdict_cloud_count=%d sell_cloud_count=%d",
        downsampled_bucket.granularity_seconds,
        len(downsampled_bucket.metrics),
        len(downsampled_bucket.volumes),
        len(downsampled_bucket.verdict_cloud),
        len(downsampled_bucket.sell_cloud),
    )
    return downsampled_bucket

