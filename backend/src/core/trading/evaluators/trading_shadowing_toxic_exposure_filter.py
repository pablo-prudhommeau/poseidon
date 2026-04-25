from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.evaluators.trading_shadowing_decile_toxicity_filter import _extract_metric_value_from_candidate
from src.core.trading.shadowing.shadow_analytics_intelligence import find_decile_index_for_value
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceSnapshot, \
    ShadowIntelligenceSnapshotMetricPayload
from src.core.trading.trading_structures import TradingCandidate
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def apply_shadowing_toxic_exposure_filter(
        candidates: list[TradingCandidate],
        snapshot: ShadowIntelligenceSnapshot,
) -> list[TradingCandidate]:
    if not snapshot.is_activated:
        logger.debug("[TRADING][EVALUATOR][SHADOW_EXPOSURE] Shadow intelligence not activated, bypassing filter")
        return candidates

    toxic_win_rate_threshold = settings.TRADING_SHADOWING_TOXIC_WIN_RATE_THRESHOLD
    maximum_toxic_exposure = settings.TRADING_SHADOWING_MAX_TOXIC_EXPOSURE

    retained: list[TradingCandidate] = []

    for candidate in candidates:
        toxic_metric_count = 0
        total_metrics_evaluated = 0

        evaluated_metrics_snapshot = []

        for metric_snapshot in snapshot.metric_snapshots:
            try:
                candidate_value = _extract_metric_value_from_candidate(candidate, metric_snapshot.metric_key)
            except Exception:
                continue

            if candidate_value is None:
                continue

            total_metrics_evaluated += 1
            decile_index = find_decile_index_for_value(candidate_value, metric_snapshot.decile_edges)

            if decile_index < len(metric_snapshot.decile_win_rates):
                decile_win_rate = metric_snapshot.decile_win_rates[decile_index]
                decile_median_pnl = metric_snapshot.decile_median_pnl[decile_index] if decile_index < len(metric_snapshot.decile_median_pnl) else 0.0
                is_toxic = False

                if decile_win_rate < toxic_win_rate_threshold:
                    toxic_metric_count += 1
                    candidate.shadow_diagnostics.toxic_metric_keys.append(metric_snapshot.metric_key)
                    is_toxic = True

                evaluated_metrics_snapshot.append(ShadowIntelligenceSnapshotMetricPayload(
                    metric_key=metric_snapshot.metric_key,
                    candidate_value=candidate_value,
                    decile_index=decile_index,
                    decile_win_rate=decile_win_rate,
                    decile_median_pnl=decile_median_pnl,
                    is_toxic=is_toxic
                ))

        candidate.shadow_diagnostics.intelligence_snapshot.evaluated_metrics = evaluated_metrics_snapshot

        candidate.shadow_diagnostics.toxic_metric_count = toxic_metric_count
        candidate.shadow_diagnostics.total_metrics_evaluated = total_metrics_evaluated

        if toxic_metric_count >= maximum_toxic_exposure:
            logger.debug(
                "[TRADING][EVALUATOR][SHADOW_EXPOSURE] %s rejected — toxic on %d / %d metrics (threshold: %d)",
                candidate.token.symbol, toxic_metric_count, total_metrics_evaluated, maximum_toxic_exposure,
            )
        else:
            retained.append(candidate)

    if len(retained) < len(candidates):
        logger.info("[TRADING][EVALUATOR][SHADOW_EXPOSURE] Retained %d / %d candidates", len(retained), len(candidates))
    else:
        logger.debug("[TRADING][EVALUATOR][SHADOW_EXPOSURE] All %d candidates passed", len(candidates))

    return retained
