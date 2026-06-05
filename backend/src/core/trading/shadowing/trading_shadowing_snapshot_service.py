from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from src.configuration.config import settings
from src.core.trading.analytics.trading_analytics_helpers import map_trading_shadowing_verdict
from src.core.trading.analytics.trading_analytics_metric_bucket_statistics_engine import (
    compute_all_metric_bucket_profiles,
)
from src.core.trading.analytics.trading_analytics_service import compute_kpis
from src.core.trading.analytics.trading_analytics_structures import MetricBucketProfile, MetaStatistics
from src.core.trading.shadowing.trading_shadowing_chronicle_helpers import (
    compute_profit_factor,
    floor_datetime_to_granularity,
    simple_moving_average_like_trading_shadowing_verdict_chronicle_chart,
    winsorize_series_like_trading_shadowing_verdict_chronicle_chart,
)
from src.core.trading.shadowing.trading_shadowing_regime_helpers import derive_trading_shadowing_phase
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingCandidateShadowingDiagnostics,
    TradingCandidateShadowingMetricEvaluation,
    TradingShadowingMetricProfile,
    TradingShadowingRegime,
    TradingShadowingSnapshot,
    TradingShadowingPhase,
)
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.date_utils import ensure_timezone_aware, get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.dao.trading_shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.database_session_manager import get_database_session

logger = get_application_logger(__name__)


def _format_optional_float(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def compute_shadowing_snapshot() -> TradingShadowingSnapshot:
    lookback_limit = settings.TRADING_SHADOWING_LOOKBACK_EVALUATIONS
    minimum_outcomes_for_shadowing = settings.TRADING_SHADOWING_MIN_ELIGIBLE_OUTCOMES_FOR_SHADOWING
    minimum_outcomes_for_shadow_gate = settings.TRADING_GATE_SHADOWING_MIN_ELIGIBLE_OUTCOMES_FOR_ACTIVATION
    minimum_hours = settings.TRADING_SHADOWING_MIN_HOURS_FOR_ACTIVATION

    with get_database_session() as database_session:
        verdict_dao = TradingShadowingVerdictDao(database_session)
        probe_dao = TradingShadowingProbeDao(database_session)

        resolved_verdicts = verdict_dao.retrieve_recent_resolved(limit_count=lookback_limit)
        total_outcomes = len(resolved_verdicts)
        resolved_shadowing_and_cortex_inference_aware_count = (
            verdict_dao.count_resolved_shadowing_and_cortex_inference_aware_outcomes()
        )
        resolved_count = verdict_dao.count_resolved()
        elapsed_hours = probe_dao.retrieve_oldest_probe_timestamp()

        outcomes_insufficient = resolved_count < minimum_outcomes_for_shadowing
        hours_insufficient = elapsed_hours < minimum_hours

        if outcomes_insufficient or hours_insufficient:
            logger.info(
                "[TRADING][SHADOWING][SNAPSHOT] Learning warmup in progress — resolved=%d/%d, elapsed_hours=%.1f/%.1f",
                resolved_count, minimum_outcomes_for_shadowing, elapsed_hours, minimum_hours,
            )

        analytics_records = [map_trading_shadowing_verdict(verdict) for verdict in resolved_verdicts]

        closed_records = [record for record in analytics_records if record.has_outcome]
        meta_win_rate = 0.0
        meta_average_pnl = 0.0
        meta_average_holding_time_hours = 0.0
        meta_expected_pnl_velocity = 0.0
        meta_profit_factor = 0.0
        meta_expected_value_usd = 0.0

        if closed_records:
            meta_kpis = compute_kpis(analytics_records, total_outcomes)
            meta_win_rate = meta_kpis.win_rate_percentage / 100.0
            meta_average_pnl = meta_kpis.average_pnl_percentage
            meta_average_holding_time_hours = meta_kpis.average_holding_duration_minutes / 60.0
            meta_expected_pnl_velocity = meta_kpis.expected_pnl_velocity
            meta_profit_factor = meta_kpis.profit_factor
            meta_expected_value_usd = meta_kpis.expected_value_usd

        meta_statistics = MetaStatistics(
            win_rate=meta_win_rate,
            average_pnl=meta_average_pnl,
            average_holding_time_hours=meta_average_holding_time_hours,
            expected_pnl_velocity=meta_expected_pnl_velocity,
        )

        bucket_profiles = compute_all_metric_bucket_profiles(analytics_records, meta_statistics)

        metric_profiles: list[TradingShadowingMetricProfile] = []
        for profile in bucket_profiles:
            snapshot = _convert_bucket_profile_to_metric_profile(profile)
            if snapshot is not None:
                metric_profiles.append(snapshot)

        current_time = get_current_local_datetime()
        chronicle_moving_average_period = settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_PERIOD
        sparse_moving_average_period = settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_PERIOD
        chronicle_profit_factor, sparse_pf_buckets = _compute_shadow_chart_sma_profit_factor_at_series_end(
            resolved_verdicts=resolved_verdicts,
            current_time=current_time,
            sma_period=chronicle_moving_average_period,
        )
        sparse_expected_value_usd, sparse_ev_buckets = _compute_shadow_chart_sma_expected_value_usd_at_series_end(
            resolved_verdicts=resolved_verdicts,
            current_time=current_time,
            sma_period=sparse_moving_average_period,
        )

        chronicle_profit_factor_threshold = settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_THRESHOLD
        sparse_expected_value_usd_threshold = settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_USD_THRESHOLD
        edge_gate_enabled = settings.TRADING_GATE_SHADOWING_EDGE_ENABLED
        edge_gate_satisfied = _is_shadow_edge_gate_satisfied(
            edge_gate_enabled=edge_gate_enabled,
            chronicle_profit_factor=chronicle_profit_factor,
            chronicle_profit_factor_threshold=chronicle_profit_factor_threshold,
            sparse_expected_value_usd=sparse_expected_value_usd,
            sparse_expected_value_usd_threshold=sparse_expected_value_usd_threshold,
        )

        logger.info(
            "[TRADING][SHADOWING][SNAPSHOT][CHRONICLE_PF] Chronicle profit factor SMA — period=%d sparse_buckets=%d chronicle_pf=%s",
            chronicle_moving_average_period,
            sparse_pf_buckets,
            _format_optional_float(chronicle_profit_factor),
        )
        logger.info(
            "[TRADING][SHADOWING][SNAPSHOT][SPARSE_EV] Sparse expected value USD — lookback_days=%.1f bucket_width_seconds=%d period=%d sparse_buckets=%d sparse_ev_usd=%s",
            settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_LOOKBACK_DAYS,
            settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_BUCKET_WIDTH_SECONDS,
            sparse_moving_average_period,
            sparse_ev_buckets,
            _format_optional_float(sparse_expected_value_usd),
        )

        logger.info(
            "[TRADING][SHADOWING][SNAPSHOT] Shadowing snapshot computed — outcomes=%d metrics=%d wr=%.1f%% pf=%.2f ev=%.2f velocity=%.2f chronicle_pf=%s sparse_ev_usd=%s edge_gate_satisfied=%s",
            total_outcomes, len(metric_profiles), meta_win_rate * 100, meta_profit_factor, meta_expected_value_usd, meta_expected_pnl_velocity, _format_optional_float(chronicle_profit_factor), _format_optional_float(sparse_expected_value_usd), edge_gate_satisfied
        )

        is_shadow_gate_eligible_outcomes_sufficient = (
                resolved_shadowing_and_cortex_inference_aware_count >= minimum_outcomes_for_shadow_gate
        )
        is_cortex_training_sufficient = (
                resolved_shadowing_and_cortex_inference_aware_count >= settings.TRADING_CORTEX_MIN_ELIGIBLE_OUTCOMES_FOR_TRAINING
        )
        shadowing_snapshot_ready = len(metric_profiles) > 0
        phase = derive_trading_shadowing_phase(
            shadowing_ready=not (outcomes_insufficient or hours_insufficient),
            shadow_gate_ready=is_shadow_gate_eligible_outcomes_sufficient,
            cortex_training_ready=is_cortex_training_sufficient,
            edge_gate_enabled=edge_gate_enabled,
            toxic_metrics_gate_enabled=settings.TRADING_GATE_SHADOWING_TOXIC_METRICS_ENABLED,
            cortex_gate_enabled=settings.TRADING_GATE_CORTEX_ENABLED,
            fundamentals_gate_enabled=settings.TRADING_GATE_FUNDAMENTALS_ENABLED,
            shadowing_snapshot_ready=shadowing_snapshot_ready,
            edge_gate_satisfied=edge_gate_satisfied,
        )

        if phase == TradingShadowingPhase.SHADOWING:
            logger.info(
                "[TRADING][SHADOWING][SNAPSHOT] Shadowing snapshot computed but not yet tradable — shadowing_cortex_aware_outcomes=%d/%d cortex_training_outcomes=%d/%d",
                resolved_shadowing_and_cortex_inference_aware_count,
                minimum_outcomes_for_shadow_gate,
                resolved_shadowing_and_cortex_inference_aware_count,
                settings.TRADING_CORTEX_MIN_ELIGIBLE_OUTCOMES_FOR_TRAINING,
            )

        if phase == TradingShadowingPhase.BEAR:
            logger.warning(
                "[TRADING][SHADOWING][SNAPSHOT][BEAR] Edge gate enabled but not satisfied — live trading blocked: chronicle_pf=%s/%.2f sparse_ev_usd=%s/%.2f",
                _format_optional_float(chronicle_profit_factor),
                chronicle_profit_factor_threshold,
                _format_optional_float(sparse_expected_value_usd),
                sparse_expected_value_usd_threshold,
            )

        return TradingShadowingSnapshot(
            regime=TradingShadowingRegime(
                phase=phase,
                edge_gate_enabled=settings.TRADING_GATE_SHADOWING_EDGE_ENABLED,
                cortex_gate_enabled=settings.TRADING_GATE_CORTEX_ENABLED,
                fundamentals_gate_enabled=settings.TRADING_GATE_FUNDAMENTALS_ENABLED,
                toxic_metrics_gate_enabled=settings.TRADING_GATE_SHADOWING_TOXIC_METRICS_ENABLED,
                resolved_outcome_count=resolved_count,
                required_outcome_count=minimum_outcomes_for_shadowing,
                elapsed_hours=elapsed_hours,
                required_hours=minimum_hours,
                edge_eligible_outcome_count=resolved_shadowing_and_cortex_inference_aware_count,
                edge_required_outcome_count=minimum_outcomes_for_shadow_gate,
                edge_chronicle_profit_factor=chronicle_profit_factor,
                edge_chronicle_profit_factor_threshold=settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_THRESHOLD,
                edge_chronicle_profit_factor_lookback_days=settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_LOOKBACK_DAYS,
                edge_chronicle_profit_factor_bucket_width_seconds=settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_BUCKET_WIDTH_SECONDS,
                edge_chronicle_profit_factor_moving_average_period=settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_PERIOD,
                edge_sparse_expected_value_usd=sparse_expected_value_usd,
                edge_sparse_expected_value_usd_threshold=settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_USD_THRESHOLD,
                edge_sparse_expected_value_lookback_days=settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_LOOKBACK_DAYS,
                edge_sparse_expected_value_bucket_width_seconds=settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_BUCKET_WIDTH_SECONDS,
                edge_sparse_expected_value_moving_average_period=settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_PERIOD,
                metrics_meta_win_rate=meta_win_rate,
                metrics_meta_average_pnl=meta_average_pnl,
                metrics_meta_average_holding_time_hours=meta_average_holding_time_hours,
                metrics_meta_expected_pnl_velocity=meta_expected_pnl_velocity,
                metrics_meta_profit_factor=meta_profit_factor,
                metrics_meta_expected_value_usd=meta_expected_value_usd,
                cortex_training_eligible_outcome_count=resolved_shadowing_and_cortex_inference_aware_count,
                cortex_training_required_outcome_count=settings.TRADING_CORTEX_MIN_ELIGIBLE_OUTCOMES_FOR_TRAINING,
            ),
            metric_profiles=metric_profiles,
        )


def _build_chronicle_sparse_profit_factor_and_mean_pnl_usd_series(
        resolved_verdicts: list,
        current_time: datetime,
        lookback: timedelta,
        granularity_seconds: int,
) -> tuple[list[float], list[float], int]:
    trailing = settings.TRADING_SHADOWING_HISTORY_TRAILING_BUCKETS

    global_from_datetime = current_time - timedelta(days=settings.TRADING_SHADOWING_HISTORY_RETENTION_DAYS)
    bucket_from_datetime = max(global_from_datetime, current_time - lookback)
    bucket_to_datetime = current_time + timedelta(seconds=granularity_seconds * max(0, trailing))

    grouped_verdicts: defaultdict = defaultdict(list)
    for verdict in resolved_verdicts:
        verdict_resolved_at = ensure_timezone_aware(verdict.resolved_at)
        if verdict_resolved_at is None:
            continue
        if verdict_resolved_at < bucket_from_datetime or verdict_resolved_at > bucket_to_datetime:
            continue
        if verdict.realized_pnl_usd is None:
            continue
        bucket_start = floor_datetime_to_granularity(verdict_resolved_at, granularity_seconds)
        grouped_verdicts[bucket_start].append(verdict)

    profit_factors_sparse: list[float] = []
    mean_pnl_usd_sparse: list[float] = []
    for bucket_timestamp in sorted(grouped_verdicts.keys()):
        items = grouped_verdicts[bucket_timestamp]
        pnl_usd_values = [item.realized_pnl_usd for item in items if item.realized_pnl_usd is not None]
        if not pnl_usd_values:
            continue
        gross_profit_usd = sum(value for value in pnl_usd_values if value > 0.0)
        gross_loss_usd = abs(sum(value for value in pnl_usd_values if value < 0.0))
        profit_factors_sparse.append(compute_profit_factor(gross_profit_usd, gross_loss_usd))
        mean_pnl_usd_sparse.append(sum(pnl_usd_values) / float(len(pnl_usd_values)))

    return profit_factors_sparse, mean_pnl_usd_sparse, len(profit_factors_sparse)


def _shadow_chart_sma_at_series_end(
        series_values: list[float],
        sma_period: int,
) -> Optional[float]:
    if not series_values:
        return None
    winsorized = winsorize_series_like_trading_shadowing_verdict_chronicle_chart(series_values)
    sma_series = simple_moving_average_like_trading_shadowing_verdict_chronicle_chart(winsorized, sma_period)
    return sma_series[-1]


def _compute_shadow_chart_sma_profit_factor_at_series_end(
        resolved_verdicts: list,
        current_time: datetime,
        sma_period: int,
) -> tuple[Optional[float], int]:
    chronicle_lookback = timedelta(days=settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_MOVING_AVERAGE_LOOKBACK_DAYS)
    chronicle_bucket_width_seconds = settings.TRADING_SHADOWING_EDGE_CHRONICLE_PROFIT_FACTOR_BUCKET_WIDTH_SECONDS
    profit_factors_sparse, _, sparse_bucket_count = _build_chronicle_sparse_profit_factor_and_mean_pnl_usd_series(
        resolved_verdicts,
        current_time,
        chronicle_lookback,
        chronicle_bucket_width_seconds,
    )
    chronicle_pf = _shadow_chart_sma_at_series_end(profit_factors_sparse, sma_period)
    return chronicle_pf, sparse_bucket_count


def _compute_shadow_chart_sma_expected_value_usd_at_series_end(
        resolved_verdicts: list,
        current_time: datetime,
        sma_period: int,
) -> tuple[Optional[float], int]:
    lookback = timedelta(days=settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_MOVING_AVERAGE_LOOKBACK_DAYS)
    granularity_seconds = settings.TRADING_SHADOWING_EDGE_SPARSE_EXPECTED_VALUE_BUCKET_WIDTH_SECONDS
    _, mean_pnl_usd_sparse, sparse_bucket_count = _build_chronicle_sparse_profit_factor_and_mean_pnl_usd_series(
        resolved_verdicts,
        current_time,
        lookback,
        granularity_seconds,
    )
    sma_ev_usd = _shadow_chart_sma_at_series_end(mean_pnl_usd_sparse, sma_period)
    return sma_ev_usd, sparse_bucket_count


def _is_shadow_edge_gate_satisfied(
        edge_gate_enabled: bool,
        chronicle_profit_factor: Optional[float],
        chronicle_profit_factor_threshold: float,
        sparse_expected_value_usd: Optional[float],
        sparse_expected_value_usd_threshold: float,
) -> bool:
    if not edge_gate_enabled:
        return True
    if chronicle_profit_factor is None or sparse_expected_value_usd is None:
        return False
    return (
            chronicle_profit_factor >= chronicle_profit_factor_threshold
            and sparse_expected_value_usd >= sparse_expected_value_usd_threshold
    )


def _convert_bucket_profile_to_metric_profile(
        profile: MetricBucketProfile,
) -> Optional[TradingShadowingMetricProfile]:
    if not profile.bucket_statistics:
        return None

    return TradingShadowingMetricProfile(
        metric_key=profile.metric_key,
        bucket_edges=profile.bucket_edges,
        bucket_win_rates=[bucket.win_rate / 100.0 for bucket in profile.bucket_statistics],
        bucket_average_pnl=[bucket.average_pnl for bucket in profile.bucket_statistics],
        bucket_average_holding_time=[bucket.average_holding_time_minutes for bucket in profile.bucket_statistics],
        bucket_expected_pnl_velocity=[bucket.expected_pnl_velocity for bucket in profile.bucket_statistics],
        bucket_outlier_hit_rates=[bucket.outlier_hit_rate / 100.0 for bucket in profile.bucket_statistics],
        bucket_sample_counts=[bucket.sample_count for bucket in profile.bucket_statistics],
        bucket_is_golden=[bucket.is_golden for bucket in profile.bucket_statistics],
        bucket_is_toxic=[bucket.is_toxic for bucket in profile.bucket_statistics],
        influence_score=profile.influence_score,
        winner_deviation=profile.winner_deviation,
    )


def find_bucket_index_for_value(value: float, bucket_edges: list[float]) -> int:
    if value is None or len(bucket_edges) < 2:
        return -1
    last_valid_bucket = len(bucket_edges) - 2
    for edge_index in range(len(bucket_edges) - 1):
        if bucket_edges[edge_index] <= value <= bucket_edges[edge_index + 1]:
            return min(edge_index, last_valid_bucket)
    if value > bucket_edges[-1]:
        return last_valid_bucket
    if value < bucket_edges[0]:
        return 0
    return last_valid_bucket


def evaluate_candidate_shadowing(
        candidate: TradingCandidate,
        snapshot: TradingShadowingSnapshot,
) -> TradingCandidateShadowingDiagnostics:
    toxic_metric_count = 0
    total_metrics_evaluated = 0
    evaluated_metrics: list[TradingCandidateShadowingMetricEvaluation] = []
    toxic_metric_keys: list[str] = []
    golden_metric_keys: list[str] = []

    for metric_profile in snapshot.metric_profiles:
        try:
            candidate_value = extract_metric_value_from_candidate(candidate, metric_profile.metric_key)
        except Exception:
            continue

        if candidate_value is None:
            continue

        total_metrics_evaluated += 1
        bucket_index = find_bucket_index_for_value(candidate_value, metric_profile.bucket_edges)

        if bucket_index < len(metric_profile.bucket_win_rates):
            bucket_win_rate = metric_profile.bucket_win_rates[bucket_index]
            bucket_average_pnl = metric_profile.bucket_average_pnl[bucket_index] if bucket_index < len(metric_profile.bucket_average_pnl) else 0.0
            bucket_average_holding_time = metric_profile.bucket_average_holding_time[bucket_index] if bucket_index < len(metric_profile.bucket_average_holding_time) else 0.0
            bucket_expected_pnl_velocity = metric_profile.bucket_expected_pnl_velocity[bucket_index] if bucket_index < len(metric_profile.bucket_expected_pnl_velocity) else 0.0
            bucket_outlier_hit_rate = metric_profile.bucket_outlier_hit_rates[bucket_index] if bucket_index < len(metric_profile.bucket_outlier_hit_rates) else 0.0
            bucket_sample_count = metric_profile.bucket_sample_counts[bucket_index] if bucket_index < len(metric_profile.bucket_sample_counts) else 0

            is_toxic = metric_profile.bucket_is_toxic[bucket_index] if bucket_index < len(metric_profile.bucket_is_toxic) else False
            is_golden = metric_profile.bucket_is_golden[bucket_index] if bucket_index < len(metric_profile.bucket_is_golden) else False

            if is_toxic:
                toxic_metric_count += 1
                toxic_metric_keys.append(metric_profile.metric_key)

            if is_golden:
                golden_metric_keys.append(metric_profile.metric_key)

            evaluated_metrics.append(TradingCandidateShadowingMetricEvaluation(
                metric_key=metric_profile.metric_key,
                candidate_value=candidate_value,
                bucket_index=bucket_index,
                bucket_win_rate=bucket_win_rate,
                bucket_average_pnl=bucket_average_pnl,
                bucket_average_holding_time=bucket_average_holding_time,
                bucket_expected_pnl_velocity=bucket_expected_pnl_velocity,
                bucket_outlier_hit_rate=bucket_outlier_hit_rate,
                bucket_sample_count=bucket_sample_count,
                is_toxic=is_toxic,
                is_golden=is_golden,
            ))

    return TradingCandidateShadowingDiagnostics(
        toxic_metric_count=toxic_metric_count,
        total_metrics_evaluated=total_metrics_evaluated,
        toxic_metric_keys=toxic_metric_keys,
        golden_metric_keys=golden_metric_keys,
        evaluated_metrics=evaluated_metrics,
    )


def extract_metric_value_from_candidate(candidate: TradingCandidate, metric_key: str) -> float | None:
    market_snapshot = candidate.market_snapshot
    extraction_map = {
        "quality_score": lambda: candidate.quality_score,
        "ai_adjusted_quality_score": lambda: candidate.ai_analysis.adjusted_quality_score,
        "liquidity_usd": lambda: market_snapshot.liquidity_usd,
        "market_cap_usd": lambda: market_snapshot.market_cap_usd,
        "volume_m5_usd": lambda: market_snapshot.volume_m5_usd,
        "volume_h1_usd": lambda: market_snapshot.volume_h1_usd,
        "volume_h6_usd": lambda: market_snapshot.volume_h6_usd,
        "volume_h24_usd": lambda: market_snapshot.volume_h24_usd,
        "price_change_m5": lambda: market_snapshot.price_change_percentage_m5,
        "price_change_h1": lambda: market_snapshot.price_change_percentage_h1,
        "price_change_h6": lambda: market_snapshot.price_change_percentage_h6,
        "price_change_h24": lambda: market_snapshot.price_change_percentage_h24,
        "token_age_hours": lambda: market_snapshot.token_age_hours,
        "transaction_count_m5": lambda: float(market_snapshot.transaction_count_m5),
        "transaction_count_h1": lambda: float(market_snapshot.transaction_count_h1),
        "transaction_count_h6": lambda: float(market_snapshot.transaction_count_h6),
        "transaction_count_h24": lambda: float(market_snapshot.transaction_count_h24),
        "buy_to_sell_ratio": lambda: market_snapshot.buy_to_sell_ratio,
        "fully_diluted_valuation_usd": lambda: market_snapshot.fully_diluted_valuation_usd,
        "promotion_score": lambda: market_snapshot.promotion_score,
        "liquidity_churn_h24": lambda: market_snapshot.volume_h24_usd / market_snapshot.liquidity_usd,
        "momentum_acceleration_5m_1h": lambda: (
            market_snapshot.price_change_percentage_m5 / market_snapshot.price_change_percentage_h1
            if market_snapshot.price_change_percentage_h1 != 0.0
            else None
        ),
    }

    extractor = extraction_map.get(metric_key)
    if extractor is None:
        return None

    return extractor()
