from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.shadowing.shadow_analytics_intelligence import find_bucket_index_for_value, extract_metric_value_from_candidate
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceSnapshot
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_shadowing_notional_boost(
        candidates: list[TradingCandidate],
        snapshot: ShadowIntelligenceSnapshot,
) -> None:
    if not snapshot.is_activated:
        logger.debug("[TRADING][EVALUATOR][SHADOW_BOOST] Shadow intelligence not activated, all multipliers stay at 1.0")
        return

    golden_win_rate_threshold = settings.TRADING_SHADOWING_GOLDEN_WIN_RATE_THRESHOLD
    minimum_metric_influence = settings.TRADING_SHADOWING_MIN_METRIC_INFLUENCE
    maximum_notional_multiplier = settings.TRADING_SHADOWING_MAX_NOTIONAL_MULTIPLIER
    tp_multiplier_min = settings.TRADING_SHADOWING_TP_MULTIPLIER_MIN
    tp_multiplier_max = settings.TRADING_SHADOWING_TP_MULTIPLIER_MAX

    influential_metrics = [
        metric_snapshot for metric_snapshot in snapshot.metric_snapshots
        if metric_snapshot.influence_score >= minimum_metric_influence
    ]

    if not influential_metrics:
        logger.debug("[TRADING][EVALUATOR][SHADOW_BOOST] No influential metrics for boost calculation")
        return

    total_influence_weight = sum(metric_snapshot.influence_score for metric_snapshot in influential_metrics)

    for candidate in candidates:
        golden_notional_accumulator = 0.0
        golden_tp_accumulator = 0.0
        evaluated_influence_weight = 0.0

        for metric_snapshot in influential_metrics:
            try:
                candidate_value = extract_metric_value_from_candidate(candidate, metric_snapshot.metric_key)
            except Exception:
                continue

            if candidate_value is None:
                continue

            bucket_index = find_bucket_index_for_value(candidate_value, metric_snapshot.bucket_edges)
            if bucket_index >= len(metric_snapshot.bucket_win_rates):
                continue

            bucket_win_rate = metric_snapshot.bucket_win_rates[bucket_index]
            bucket_capital_velocity = metric_snapshot.bucket_capital_velocity[bucket_index] if bucket_index < len(metric_snapshot.bucket_capital_velocity) else 0.0
            normalized_influence = metric_snapshot.influence_score / total_influence_weight
            evaluated_influence_weight += normalized_influence

            is_golden = metric_snapshot.bucket_is_golden[bucket_index] if bucket_index < len(metric_snapshot.bucket_is_golden) else False

            if is_golden:
                base_strength = (bucket_win_rate - golden_win_rate_threshold) / (1.0 - golden_win_rate_threshold) if golden_win_rate_threshold < 1.0 else 0.0
                velocity_multiplier = max(0.0, 1.0 + bucket_capital_velocity)
                golden_strength = base_strength * velocity_multiplier

                if golden_strength > 0:
                    golden_notional_accumulator += normalized_influence * golden_strength
                    golden_tp_accumulator += normalized_influence * golden_strength
                    candidate.shadow_diagnostics.golden_metric_keys.append(metric_snapshot.metric_key)

            for evaluated_metric in candidate.shadow_diagnostics.intelligence_snapshot.evaluated_metrics:
                if evaluated_metric.metric_key == metric_snapshot.metric_key:
                    evaluated_metric.is_golden = is_golden
                    evaluated_metric.normalized_influence = normalized_influence
                    break

        notional_multiplier = 1.0 + golden_notional_accumulator * (maximum_notional_multiplier - 1.0)
        notional_multiplier = max(1.0, min(maximum_notional_multiplier, notional_multiplier))

        tp_multiplier = 1.0 + golden_tp_accumulator * (tp_multiplier_max - 1.0)
        tp_multiplier = max(tp_multiplier_min, min(tp_multiplier_max, tp_multiplier))

        candidate.shadow_notional_multiplier = notional_multiplier
        candidate.shadow_tp_multiplier = tp_multiplier
        candidate.shadow_diagnostics.notional_boost_factor = notional_multiplier
        candidate.shadow_diagnostics.take_profit_boost_factor = tp_multiplier

        if notional_multiplier > 1.05 or tp_multiplier > 1.05:
            logger.debug(
                "[TRADING][EVALUATOR][SHADOW_BOOST] %s — notional_mult=%.2fx tp_mult=%.2fx (golden_accum=%.3f)",
                candidate.token.symbol, notional_multiplier, tp_multiplier, golden_notional_accumulator,
            )

    boosted_count = sum(1 for candidate in candidates if candidate.shadow_notional_multiplier > 1.05)
    logger.info("[TRADING][EVALUATOR][SHADOW_BOOST] %d / %d candidates received golden niche boost", boosted_count, len(candidates))
