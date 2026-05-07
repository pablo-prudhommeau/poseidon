from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.trading.analytics.trading_analytics_helpers import map_trading_shadowing_verdict
from src.core.trading.analytics.trading_analytics_metric_bucket_statistics_engine import (
    compute_all_metric_bucket_profiles,
)
from src.core.trading.analytics.trading_analytics_structures import MetricBucketProfile
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceMetricSnapshot, ShadowIntelligenceSnapshot
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.shadowing_probe_dao import TradingShadowingProbeDao
from src.persistence.dao.trading.shadowing_verdict_dao import TradingShadowingVerdictDao
from src.persistence.db import get_database_session

logger = get_application_logger(__name__)


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

        analytics_records = [map_trading_shadowing_verdict(verdict) for verdict in resolved_verdicts]

        closed_records = [record for record in analytics_records if record.has_outcome]
        meta_win_rate = 0.0
        meta_average_pnl = 0.0
        meta_average_holding_time_hours = 0.0
        meta_capital_velocity = 0.0

        if closed_records:
            meta_win_count = sum(1 for record in closed_records if record.is_profitable)
            meta_win_rate = meta_win_count / len(closed_records)
            meta_average_pnl = sum(record.realized_profit_and_loss_percentage for record in closed_records) / len(closed_records)
            meta_average_holding_time_minutes = sum(record.holding_duration_minutes for record in closed_records) / len(closed_records)
            meta_average_holding_time_hours = meta_average_holding_time_minutes / 60.0
            if meta_average_holding_time_hours > 0:
                meta_capital_velocity = (meta_average_pnl * meta_win_rate) / meta_average_holding_time_hours

        from src.core.trading.analytics.trading_analytics_structures import MetaStatistics
        meta_statistics = MetaStatistics(
            win_rate=meta_win_rate,
            average_pnl=meta_average_pnl,
            average_holding_time_hours=meta_average_holding_time_hours,
            capital_velocity=meta_capital_velocity,
        )

        bucket_profiles = compute_all_metric_bucket_profiles(analytics_records, meta_statistics)

        metric_snapshots: list[ShadowIntelligenceMetricSnapshot] = []
        for profile in bucket_profiles:
            snapshot = _convert_bucket_profile_to_metric_snapshot(profile)
            if snapshot is not None:
                metric_snapshots.append(snapshot)

        logger.info(
            "[TRADING][SHADOW][INTELLIGENCE] Shadow intelligence snapshot computed — %d outcomes analyzed, %d metrics profiled, meta(WR=%.1f%%, PnL=%.2f%%, Hold=%.1fh, Vel=%.2f)",
            total_outcomes, len(metric_snapshots), meta_win_rate * 100, meta_average_pnl, meta_average_holding_time_hours, meta_capital_velocity,
        )

        return ShadowIntelligenceSnapshot(
            metric_snapshots=metric_snapshots,
            total_outcomes_analyzed=total_outcomes,
            is_activated=True,
            resolved_outcome_count=resolved_count,
            elapsed_hours=elapsed_hours,
            meta_win_rate=meta_win_rate,
            meta_average_pnl=meta_average_pnl,
            meta_average_holding_time_hours=meta_average_holding_time_hours,
            meta_capital_velocity=meta_capital_velocity,
        )


def _convert_bucket_profile_to_metric_snapshot(
        profile: MetricBucketProfile,
) -> Optional[ShadowIntelligenceMetricSnapshot]:
    if not profile.bucket_statistics:
        return None

    return ShadowIntelligenceMetricSnapshot(
        metric_key=profile.metric_key,
        bucket_edges=profile.bucket_edges,
        bucket_win_rates=[bucket.win_rate / 100.0 for bucket in profile.bucket_statistics],
        bucket_average_pnl=[bucket.average_pnl for bucket in profile.bucket_statistics],
        bucket_average_holding_time=[bucket.average_holding_time_minutes for bucket in profile.bucket_statistics],
        bucket_capital_velocity=[bucket.capital_velocity for bucket in profile.bucket_statistics],
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


def extract_metric_value_from_candidate(candidate: TradingCandidate, metric_key: str) -> float | None:
    token_information = candidate.dexscreener_token_information
    extraction_map = {
        "quality_score": lambda: candidate.quality_score,
        "ai_adjusted_quality_score": lambda: candidate.ai_adjusted_quality_score,
        "liquidity_usd": lambda: token_information.liquidity.usd if token_information.liquidity else None,
        "market_cap_usd": lambda: token_information.market_cap,
        "volume_m5_usd": lambda: token_information.volume.m5 if token_information.volume else None,
        "volume_h1_usd": lambda: token_information.volume.h1 if token_information.volume else None,
        "volume_h6_usd": lambda: token_information.volume.h6 if token_information.volume else None,
        "volume_h24_usd": lambda: token_information.volume.h24 if token_information.volume else None,
        "price_change_m5": lambda: token_information.price_change.m5 if token_information.price_change else None,
        "price_change_h1": lambda: token_information.price_change.h1 if token_information.price_change else None,
        "price_change_h6": lambda: token_information.price_change.h6 if token_information.price_change else None,
        "price_change_h24": lambda: token_information.price_change.h24 if token_information.price_change else None,
        "token_age_hours": lambda: token_information.age_hours,
        "transaction_count_m5": lambda: token_information.transactions.m5.total_transactions if token_information.transactions and token_information.transactions.m5 else None,
        "transaction_count_h1": lambda: token_information.transactions.h1.total_transactions if token_information.transactions and token_information.transactions.h1 else None,
        "transaction_count_h6": lambda: token_information.transactions.h6.total_transactions if token_information.transactions and token_information.transactions.h6 else None,
        "transaction_count_h24": lambda: token_information.transactions.h24.total_transactions if token_information.transactions and token_information.transactions.h24 else None,
        "buy_to_sell_ratio": lambda: _compute_buy_to_sell_ratio(token_information),
        "fully_diluted_valuation_usd": lambda: token_information.fully_diluted_valuation,
        "dexscreener_boost": lambda: token_information.boost,
        "liquidity_churn_h24": lambda: (token_information.volume.h24 / token_information.liquidity.usd) if token_information.volume and token_information.liquidity and token_information.liquidity.usd and token_information.liquidity.usd > 0 else 0.0,
        "momentum_acceleration_5m_1h": lambda: (token_information.price_change.m5 / token_information.price_change.h1) if token_information.price_change and token_information.price_change.h1 and token_information.price_change.h1 != 0 else 0.0,
    }

    extractor = extraction_map.get(metric_key)
    if extractor is None:
        return None

    return extractor()


def _compute_buy_to_sell_ratio(token_information) -> float | None:
    transactions = token_information.transactions
    if not transactions:
        return None
    reference_bucket = transactions.h1 if transactions.h1 else transactions.h24
    if not reference_bucket:
        return None
    total = reference_bucket.buys + reference_bucket.sells
    if total <= 0:
        return None
    return reference_bucket.buys / total
