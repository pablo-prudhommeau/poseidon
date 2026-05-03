from __future__ import annotations

from src.configuration.config import settings
from src.core.trading.shadowing.shadow_analytics_intelligence import find_bucket_index_for_value, extract_metric_value_from_candidate
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceSnapshot, \
    ShadowIntelligenceSnapshotMetricPayload
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.log_utils import get_visual_width
from src.logging.logger import get_application_logger, console_color_codes

logger = get_application_logger(__name__)


def apply_shadowing_toxic_exposure_filter(
        candidates: list[TradingCandidate],
        snapshot: ShadowIntelligenceSnapshot,
) -> list[TradingCandidate]:
    if not snapshot.is_activated:
        logger.debug("[TRADING][EVALUATOR][SHADOW_EXPOSURE] Shadow intelligence not activated, bypassing filter")
        return candidates

    toxic_win_rate_threshold = settings.TRADING_SHADOWING_TOXIC_WIN_RATE_THRESHOLD
    toxic_max_average_pnl = settings.TRADING_SHADOWING_TOXIC_AVERAGE_PNL_THRESHOLD * 100.0
    toxic_min_capital_velocity = settings.TRADING_SHADOWING_TOXIC_CAPITAL_VELOCITY_THRESHOLD
    toxic_max_holding_time_minutes = settings.TRADING_SHADOWING_TOXIC_HOLDING_TIME_THRESHOLD * 60.0
    maximum_toxic_exposure = settings.TRADING_SHADOWING_TOXIC_MAX_EXPOSURE

    retained: list[TradingCandidate] = []

    for candidate in candidates:
        toxic_metric_count = 0
        total_metrics_evaluated = 0

        evaluated_metrics_snapshot = []

        for metric_snapshot in snapshot.metric_snapshots:
            try:
                candidate_value = extract_metric_value_from_candidate(candidate, metric_snapshot.metric_key)
            except Exception:
                continue

            if candidate_value is None:
                continue

            total_metrics_evaluated += 1
            bucket_index = find_bucket_index_for_value(candidate_value, metric_snapshot.bucket_edges)

            if bucket_index < len(metric_snapshot.bucket_win_rates):
                bucket_win_rate = metric_snapshot.bucket_win_rates[bucket_index]
                bucket_average_pnl = metric_snapshot.bucket_average_pnl[bucket_index] if bucket_index < len(metric_snapshot.bucket_average_pnl) else 0.0
                bucket_average_holding_time = metric_snapshot.bucket_average_holding_time[bucket_index] if bucket_index < len(metric_snapshot.bucket_average_holding_time) else 0.0
                bucket_capital_velocity = metric_snapshot.bucket_capital_velocity[bucket_index] if bucket_index < len(metric_snapshot.bucket_capital_velocity) else 0.0
                bucket_outlier_hit_rate = metric_snapshot.bucket_outlier_hit_rates[bucket_index] if bucket_index < len(metric_snapshot.bucket_outlier_hit_rates) else 0.0
                bucket_sample_count = metric_snapshot.bucket_sample_counts[bucket_index] if bucket_index < len(metric_snapshot.bucket_sample_counts) else 0

                is_toxic = metric_snapshot.bucket_is_toxic[bucket_index] if bucket_index < len(metric_snapshot.bucket_is_toxic) else False
                is_golden = metric_snapshot.bucket_is_golden[bucket_index] if bucket_index < len(metric_snapshot.bucket_is_golden) else False

                if is_toxic:
                    toxic_metric_count += 1
                    candidate.shadow_diagnostics.toxic_metric_keys.append(metric_snapshot.metric_key)

                evaluated_metrics_snapshot.append(ShadowIntelligenceSnapshotMetricPayload(
                    metric_key=metric_snapshot.metric_key,
                    candidate_value=candidate_value,
                    bucket_index=bucket_index,
                    bucket_win_rate=bucket_win_rate,
                    bucket_average_pnl=bucket_average_pnl,
                    bucket_average_holding_time=bucket_average_holding_time,
                    bucket_capital_velocity=bucket_capital_velocity,
                    bucket_outlier_hit_rate=bucket_outlier_hit_rate,
                    bucket_sample_count=bucket_sample_count,
                    is_toxic=is_toxic,
                    is_golden=is_golden,
                ))

        candidate.shadow_diagnostics.intelligence_snapshot.evaluated_metrics = evaluated_metrics_snapshot

        candidate.shadow_diagnostics.toxic_metric_count = toxic_metric_count
        candidate.shadow_diagnostics.total_metrics_evaluated = total_metrics_evaluated

        if toxic_metric_count > maximum_toxic_exposure:
            formatted_reasons = []
            master_metric_keys = sorted([m.metric_key for m in snapshot.metric_snapshots])
            evaluated_lookup = {m.metric_key: m for m in evaluated_metrics_snapshot}
            grey = console_color_codes["GREY"]
            red = console_color_codes["RED"]
            green = console_color_codes["GREEN"]
            reset = console_color_codes["RESET"]
            for key in master_metric_keys:
                metric_data = evaluated_lookup.get(key)
                padded_key = key
                if metric_data:
                    if metric_data.is_golden:
                        key_color = green
                        content_color = green
                    elif metric_data.is_toxic:
                        key_color = red
                        content_color = grey
                    else:
                        key_color = grey
                        content_color = grey

                    v_str = f"{metric_data.candidate_value:>12.2f}"

                    wr_color = red if metric_data.bucket_win_rate < toxic_win_rate_threshold else content_color
                    wr_str = f"{metric_data.bucket_win_rate * 100:>5.1f}%"

                    pnl_color = red if metric_data.bucket_average_pnl < toxic_max_average_pnl else content_color
                    pnl_str = f"{metric_data.bucket_average_pnl:>7.2f}%"

                    hold_color = red if metric_data.bucket_average_holding_time > toxic_max_holding_time_minutes else content_color
                    hold_str = f"{metric_data.bucket_average_holding_time / 60.0:>5.1f}h"

                    vel_color = red if metric_data.bucket_capital_velocity < toxic_min_capital_velocity else content_color
                    vel_str = f"{metric_data.bucket_capital_velocity:>6.2f}"

                    ohr_color = content_color
                    ohr_str = f"{metric_data.bucket_outlier_hit_rate * 100:>5.1f}%"

                    trades_color = content_color
                    trades_str = f"{metric_data.bucket_sample_count:>5}"

                    formatted_reasons.append(
                        f"{key_color}{padded_key}{content_color} (V:{v_str}{content_color}, {wr_color}WR:{wr_str}{content_color}, "
                        f"{pnl_color}PnL:{pnl_str}{content_color}, {ohr_color}OHR:{ohr_str}{content_color}, {hold_color}H:{hold_str}{content_color}, {vel_color}Vel:{vel_str}{content_color}, {trades_color}T:{trades_str}{content_color}){reset}"
                    )
                else:
                    v = f"{'—':>12}"
                    wr = f"{'—':>5}%"
                    pnl = f"{'—':>7}%"
                    hold = f"{'—':>5}h"
                    vel = f"{'—':>6}"
                    ohr = f"{'—':>5}%"
                    trades = f"{'—':>5}"
                    formatted_reasons.append(f"{grey}{padded_key}{grey} (V:{v}, WR:{wr}, PnL:{pnl}, OHR:{ohr}, H:{hold}, Vel:{vel}, T:{trades}){reset}")

            top_reasons = " |   ".join(formatted_reasons)

            prefix = f"{candidate.token.symbol} rejected (toxic {toxic_metric_count}/{total_metrics_evaluated})"
            visual_len = get_visual_width(prefix)
            padding = " " * max(0, 40 - visual_len)

            logger.debug(
                "[TRADING][EVALUATOR][SHADOW_EXPOSURE] %s%s Reasons: %s",
                prefix, padding, top_reasons
            )
        else:
            retained.append(candidate)

    if len(retained) < len(candidates):
        logger.info("[TRADING][EVALUATOR][SHADOW_EXPOSURE] Retained %d / %d candidates", len(retained), len(candidates))
    else:
        logger.debug("[TRADING][EVALUATOR][SHADOW_EXPOSURE] All %d candidates passed", len(candidates))

    return retained
