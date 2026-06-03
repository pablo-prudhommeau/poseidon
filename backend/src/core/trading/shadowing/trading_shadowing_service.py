from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Iterable

from pydantic import ValidationError

from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import (
    chronicle_display_lag_timedelta as _chronicle_display_lag_timedelta,
    compute_profit_factor as _compute_profit_factor,
    floor_datetime_to_granularity as _floor_datetime_to_granularity,
    series_end_datetime as _series_end_datetime,
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
from src.persistence.dao.trading_portfolio_snapshot_dao import TradingPortfolioSnapshotDao
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session
from src.persistence.models import TradingShadowingVerdict

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
    series_end_datetime = _series_end_datetime(now_local)
    fetch_end_datetime = _verdict_fetch_end_datetime(series_end_datetime, bucket_configurations)
    global_from_datetime = series_end_datetime - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)

    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        portfolio_snapshot_dao = TradingPortfolioSnapshotDao(database_session)
        resolved_verdicts = verdict_dao.retrieve_resolved_in_window(
            start_datetime=global_from_datetime,
            end_datetime=fetch_end_datetime,
            limit_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
        )
        verdicts = _convert_verdicts(resolved_verdicts)
        portfolio_snapshots = _load_portfolio_snapshots_for_chronicle(
            portfolio_snapshot_dao=portfolio_snapshot_dao,
            global_from_datetime=global_from_datetime,
            fetch_end_datetime=fetch_end_datetime,
        )

    logger.info(
        "[TRADING][SHADOWING][HISTORY] Full chronicle built — verdict_count=%d bucket_layer_count=%d",
        len(verdicts),
        len(bucket_configurations),
    )
    return TradingShadowingVerdictChronicleComputationResult(
        chronicle=_build_trading_shadowing_verdict_chronicle(
            verdicts,
            portfolio_snapshots,
            now_local,
            bucket_configurations,
            series_end_datetime,
            fetch_end_datetime,
            global_from_datetime,
        ),
        verdicts=verdicts,
    )


def compute_trading_shadowing_verdict_chronicle_incremental(
        previous_verdicts: list[TradingShadowingVerdictChronicleVerdict],
) -> TradingShadowingVerdictChronicleComputationResult:
    now_local = get_current_local_datetime()
    bucket_configurations = _trading_shadowing_verdict_chronicle_bucket_configurations()
    series_end_datetime = _series_end_datetime(now_local)
    fetch_end_datetime = _verdict_fetch_end_datetime(series_end_datetime, bucket_configurations)
    global_from_datetime = series_end_datetime - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)

    working_verdicts = _trim_verdicts_for_window(
        previous_verdicts,
        global_from_datetime=global_from_datetime,
        fetch_end_datetime=fetch_end_datetime,
        max_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
    )
    if not working_verdicts:
        return compute_trading_shadowing_verdict_chronicle()

    max_id = max(chronicle_verdict.id for chronicle_verdict in working_verdicts)
    new_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []
    portfolio_snapshots: list[TradingShadowingVerdictChroniclePortfolioWalletValuePoint] = []
    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        portfolio_snapshot_dao = TradingPortfolioSnapshotDao(database_session)
        new_orms = verdict_dao.retrieve_resolved_in_window_after_id(
            after_id_exclusive=max_id,
            start_datetime=global_from_datetime,
            end_datetime=fetch_end_datetime,
            limit_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
        )
        new_verdicts = _convert_verdicts(new_orms)
        portfolio_snapshots = _load_portfolio_snapshots_for_chronicle(
            portfolio_snapshot_dao=portfolio_snapshot_dao,
            global_from_datetime=global_from_datetime,
            fetch_end_datetime=fetch_end_datetime,
        )

    if new_verdicts:
        merged_by_id = {chronicle_verdict.id: chronicle_verdict for chronicle_verdict in working_verdicts}
        for chronicle_verdict in new_verdicts:
            merged_by_id[chronicle_verdict.id] = chronicle_verdict
        working_verdicts = sorted(merged_by_id.values(), key=lambda chronicle_verdict: chronicle_verdict.resolved_at)
        working_verdicts = _trim_verdicts_for_window(
            working_verdicts,
            global_from_datetime=global_from_datetime,
            fetch_end_datetime=fetch_end_datetime,
            max_count=settings.TRADING_SHADOWING_HISTORY_MAX_VERDICTS_FETCH,
        )

    new_chronicle = _build_trading_shadowing_verdict_chronicle(
        working_verdicts,
        portfolio_snapshots,
        now_local,
        bucket_configurations,
        series_end_datetime,
        fetch_end_datetime,
        global_from_datetime,
    )
    logger.debug(
        "[TRADING][SHADOWING][HISTORY] Incremental chronicle — verdict_count=%d new_verdict_count_from_database=%d",
        len(working_verdicts),
        len(new_verdicts),
    )
    return TradingShadowingVerdictChronicleComputationResult(
        chronicle=new_chronicle,
        verdicts=working_verdicts,
    )


def _build_trading_shadowing_verdict_chronicle(
        verdicts: list[TradingShadowingVerdictChronicleVerdict],
        portfolio_wallet_value_points: list[TradingShadowingVerdictChroniclePortfolioWalletValuePoint],
        now_local: datetime,
        bucket_configurations: list[TradingShadowingVerdictChronicleBucketConfiguration],
        series_end_datetime: datetime,
        fetch_end_datetime: datetime,
        global_from_datetime: datetime,
) -> TradingShadowingVerdictChronicle:
    buckets: list[TradingShadowingVerdictChronicleBucket] = []
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS
    chronicle_lag_td = _chronicle_display_lag_timedelta()
    for bucket_configuration in bucket_configurations:
        bucket_from_datetime = max(
            global_from_datetime,
            series_end_datetime - bucket_configuration.lookback - chronicle_lag_td,
        )
        bucket_to_datetime = series_end_datetime + timedelta(
            seconds=bucket_configuration.granularity_seconds * max(0, trailing),
        )
        buckets.append(_build_bucket(
            verdicts=verdicts,
            portfolio_wallet_value_points=portfolio_wallet_value_points,
            bucket_configuration=bucket_configuration,
            from_datetime=bucket_from_datetime,
            to_datetime=bucket_to_datetime,
            series_end_datetime=series_end_datetime,
        ))

    return TradingShadowingVerdictChronicle(
        generated_at=now_local,
        as_of=series_end_datetime,
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
        bucket_configuration: TradingShadowingVerdictChronicleBucketConfiguration,
        from_datetime: datetime,
        to_datetime: datetime,
        series_end_datetime: datetime,
) -> TradingShadowingVerdictChronicleBucket:
    window_from = ensure_timezone_aware(from_datetime)
    window_to = ensure_timezone_aware(to_datetime)
    assert window_from is not None and window_to is not None

    grouped_verdicts: dict[int, list[TradingShadowingVerdictChronicleVerdict]] = defaultdict(list)
    bounded_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []

    for verdict in verdicts:
        resolved_at = ensure_timezone_aware(verdict.resolved_at)
        if resolved_at is None:
            continue
        if resolved_at < window_from or resolved_at > window_to:
            continue
        bounded_verdicts.append(verdict)
        bucket_start = _floor_datetime_to_granularity(resolved_at, bucket_configuration.granularity_seconds)
        grouped_verdicts[_to_epoch_milliseconds(bucket_start)].append(verdict)

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

    for bucket_timestamp in sorted(grouped_verdicts.keys()):
        while portfolio_wallet_value_point_index < len(sorted_portfolio_wallet_value_points):
            portfolio_wallet_value_point = sorted_portfolio_wallet_value_points[portfolio_wallet_value_point_index]
            if portfolio_wallet_value_point.timestamp_milliseconds > bucket_timestamp:
                break
            latest_known_portfolio_wallet_value = portfolio_wallet_value_point.total_wallet_value_usd
            portfolio_wallet_value_point_index += 1

        items = grouped_verdicts[bucket_timestamp]
        verdict_count = len(items)
        if verdict_count == 0:
            continue

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
        cortex_skill_score_percentage = _compute_cortex_skill_score_percentage(items)
        (
            cortex_calibration_gap_percentage_points,
            cortex_high_conviction_accuracy_percentage,
            cortex_high_conviction_share_percentage,
        ) = _compute_cortex_actionability_metrics(items)
        (
            cortex_gate_precision_percentage,
            cortex_gate_pass_rate_percentage,
        ) = _compute_cortex_gate_quality_metrics(items)

        metric_points.append(TradingShadowingVerdictChronicleMetricPoint(
            timestamp_milliseconds=bucket_timestamp,
            average_pnl_percentage=sum(pnl_percentage_values) / verdict_count,
            average_win_rate_percentage=(win_count / verdict_count) * 100.0,
            expected_value_per_trade_usd=sum(pnl_usd_values) / verdict_count,
            total_wallet_value_usd=latest_known_portfolio_wallet_value,
            closed_verdicts_per_hour=_compute_closed_verdicts_per_hour(verdict_count, bucket_configuration.granularity_seconds),
            profit_factor=_compute_profit_factor(gross_profit_usd, gross_loss_usd),
            average_cortex_prediction_win_rate_percentage=average_cortex_prediction_win_rate_percentage,
            average_cortex_predicted_holding_time_minutes=average_cortex_predicted_holding_time_minutes,
            cortex_skill_score_percentage=cortex_skill_score_percentage,
            cortex_calibration_gap_percentage_points=cortex_calibration_gap_percentage_points,
            cortex_high_conviction_accuracy_percentage=cortex_high_conviction_accuracy_percentage,
            cortex_high_conviction_share_percentage=cortex_high_conviction_share_percentage,
            cortex_gate_precision_percentage=cortex_gate_precision_percentage,
            cortex_gate_pass_rate_percentage=cortex_gate_pass_rate_percentage,
        ))
        volume_points.append(TradingShadowingVerdictChronicleVolumePoint(
            timestamp_milliseconds=bucket_timestamp,
            verdict_count=verdict_count,
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
        verdicts=bounded_verdicts,
        series_end_datetime=series_end_datetime,
        metric_timestamps_milliseconds=[metric_point.timestamp_milliseconds for metric_point in metric_points],
    )
    cortex_reliability_diagram = _build_cortex_reliability_diagram(bounded_verdicts)

    return TradingShadowingVerdictChronicleBucket(
        bucket_label=bucket_configuration.label,
        granularity_seconds=bucket_configuration.granularity_seconds,
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        metrics=metric_points,
        volumes=volume_points,
        verdict_cloud=verdict_cloud,
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
        series_end_datetime: datetime,
        bucket_configurations: list[TradingShadowingVerdictChronicleBucketConfiguration],
) -> datetime:
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS
    if trailing <= 0 or not bucket_configurations:
        return series_end_datetime
    max_granularity_seconds = max(configuration.granularity_seconds for configuration in bucket_configurations)
    return series_end_datetime + timedelta(seconds=max_granularity_seconds * trailing)


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
    if len(verdicts) <= limit_count:
        return verdicts

    step = len(verdicts) / float(limit_count)
    return [verdicts[int(index * step)] for index in range(limit_count)]


def _clamp_point_size(order_notional_usd: float) -> float:
    if order_notional_usd <= 0:
        return 3.0
    return max(3.0, min(18.0, (order_notional_usd ** 0.5) / 2.0))
