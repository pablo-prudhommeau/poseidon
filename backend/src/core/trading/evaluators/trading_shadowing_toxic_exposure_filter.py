from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.trading.shadowing.trading_shadowing_intelligence_service import (
    evaluate_candidate_shadow_intelligence,
)
from src.core.trading.shadowing.trading_shadowing_structures import (
    TradingShadowingIntelligenceSnapshot,
    TradingShadowingPhase,
    TradingShadowingIntelligenceMetric,
)
from src.core.trading.trading_structures import TradingCandidate
from src.core.utils.log_utils import get_visual_width
from src.logging.logger import get_application_logger, console_color_codes

logger = get_application_logger(__name__)


def apply_shadowing_toxic_exposure_filter(
        candidates: list[TradingCandidate],
        snapshot: TradingShadowingIntelligenceSnapshot,
) -> list[TradingCandidate]:
    if snapshot.summary.phase == TradingShadowingPhase.DISABLED:
        logger.debug("[TRADING][EVALUATOR][SHADOW_EXPOSURE] Shadow intelligence phase is %s, bypassing filter completely", snapshot.summary.phase.value)
        return candidates

    is_active: bool = snapshot.summary.phase == TradingShadowingPhase.ACTIVE

    meta_win_rate: float = snapshot.summary.meta_win_rate or 0.0
    meta_average_pnl: float = snapshot.summary.meta_average_pnl or 0.0
    meta_capital_velocity: float = snapshot.summary.meta_capital_velocity or 0.0
    meta_average_holding_time_hours: float = snapshot.summary.meta_average_holding_time_hours or 0.0

    toxic_win_rate_threshold: float = meta_win_rate + settings.TRADING_SHADOWING_TOXIC_WIN_RATE_OFFSET
    toxic_max_average_pnl: float = (meta_average_pnl + settings.TRADING_SHADOWING_TOXIC_AVERAGE_PNL_OFFSET * 100.0)
    toxic_min_capital_velocity: float = meta_capital_velocity + settings.TRADING_SHADOWING_TOXIC_CAPITAL_VELOCITY_OFFSET
    toxic_max_holding_time_minutes: float = (meta_average_holding_time_hours + settings.TRADING_SHADOWING_TOXIC_HOLDING_TIME_OFFSET) * 60.0
    maximum_toxic_exposure: int = settings.TRADING_SHADOWING_TOXIC_MAX_EXPOSURE

    retained: list[TradingCandidate] = []
    rejected: list[TradingCandidate] = []

    for candidate in candidates:
        if candidate.token.symbol == "RUNNER":
            logger.info("[TRADING][EVALUATOR][SHADOW_EXPOSURE] Shunting toxicity for %s", candidate.token.symbol)
            candidate.shadow_diagnostics.intelligence_snapshot = TradingShadowingIntelligenceSnapshot(
                summary=snapshot.summary,
            )
            retained.append(candidate)
            continue

        diagnostics = evaluate_candidate_shadow_intelligence(candidate, snapshot)
        candidate.shadow_diagnostics = diagnostics

        if not is_active:
            retained.append(candidate)
            continue

        if settings.TRADING_GATE_SHADOWING_ENABLED and diagnostics.total_metrics_evaluated <= 0:
            rejected.append(candidate)
            continue

        if diagnostics.toxic_metric_count > maximum_toxic_exposure:
            rejected.append(candidate)
        else:
            retained.append(candidate)

    rejected.sort(key=lambda c: c.shadow_diagnostics.toxic_metric_count, reverse=True)

    _log_shadow_evaluation_details(
        retained=retained,
        rejected=rejected,
        snapshot=snapshot,
        toxic_win_rate_threshold=toxic_win_rate_threshold,
        toxic_max_average_pnl=toxic_max_average_pnl,
        toxic_max_holding_time_minutes=toxic_max_holding_time_minutes,
        toxic_min_capital_velocity=toxic_min_capital_velocity,
    )

    meta_summary: str = (
            "meta(WR=%.1f%%, PnL=%.2f%%, Hold=%.1fh, Vel=%.2f) → toxic(WR<%.1f%%, PnL<%.2f%%, Hold>%.1fh, Vel<%.2f)"
            % (
                meta_win_rate * 100, meta_average_pnl, meta_average_holding_time_hours, meta_capital_velocity,
                toxic_win_rate_threshold * 100, toxic_max_average_pnl, toxic_max_holding_time_minutes / 60.0, toxic_min_capital_velocity,
            )
    )

    if len(retained) < len(candidates):
        logger.info("[TRADING][EVALUATOR][SHADOW_EXPOSURE] Retained %d / %d candidates — %s", len(retained), len(candidates), meta_summary)
    else:
        logger.debug("[TRADING][EVALUATOR][SHADOW_EXPOSURE] All %d candidates passed — %s", len(candidates), meta_summary)

    return retained


def _log_shadow_evaluation_details(
        retained: list[TradingCandidate],
        rejected: list[TradingCandidate],
        snapshot: TradingShadowingIntelligenceSnapshot,
        toxic_win_rate_threshold: float,
        toxic_max_average_pnl: float,
        toxic_max_holding_time_minutes: float,
        toxic_min_capital_velocity: float,
) -> None:
    red: str = console_color_codes["RED"]
    green: str = console_color_codes["GREEN"]
    reset: str = console_color_codes["RESET"]

    for candidate in rejected:
        metrics_table: str = _format_candidate_shadow_metrics_table(
            candidate=candidate,
            snapshot=snapshot,
            toxic_win_rate_threshold=toxic_win_rate_threshold,
            toxic_max_average_pnl=toxic_max_average_pnl,
            toxic_max_holding_time_minutes=toxic_max_holding_time_minutes,
            toxic_min_capital_velocity=toxic_min_capital_velocity,
        )

        toxic_count: int = candidate.shadow_diagnostics.toxic_metric_count
        total_count: int = candidate.shadow_diagnostics.total_metrics_evaluated
        prefix: str = f"{candidate.token.symbol} {red}rejected{reset} (toxic {toxic_count}/{total_count})"
        visual_length: int = get_visual_width(prefix)
        padding: str = " " * max(0, 45 - visual_length)

        logger.debug("[TRADING][EVALUATOR][SHADOW_EXPOSURE] %s%s Reasons: %s", prefix, padding, metrics_table)

    for candidate in retained:
        if not candidate.shadow_diagnostics.intelligence_snapshot:
            continue

        metrics_table: str = _format_candidate_shadow_metrics_table(
            candidate=candidate,
            snapshot=snapshot,
            toxic_win_rate_threshold=toxic_win_rate_threshold,
            toxic_max_average_pnl=toxic_max_average_pnl,
            toxic_max_holding_time_minutes=toxic_max_holding_time_minutes,
            toxic_min_capital_velocity=toxic_min_capital_velocity,
        )

        prefix: str = f"{candidate.token.symbol} {green}retained{reset}"
        visual_length: int = get_visual_width(prefix)
        padding: str = " " * max(0, 45 - visual_length)

        logger.debug("[TRADING][EVALUATOR][SHADOW_EXPOSURE] %s%s Reasons: %s", prefix, padding, metrics_table)


def _format_candidate_shadow_metrics_table(
        candidate: TradingCandidate,
        snapshot: TradingShadowingIntelligenceSnapshot,
        toxic_win_rate_threshold: float,
        toxic_max_average_pnl: float,
        toxic_max_holding_time_minutes: float,
        toxic_min_capital_velocity: float,
) -> str:
    if not candidate.shadow_diagnostics.intelligence_snapshot:
        return ""

    evaluated_metrics: list[TradingShadowingIntelligenceMetric] = candidate.shadow_diagnostics.intelligence_snapshot.metrics
    master_metric_keys: list[str] = sorted([m.metric_key for m in snapshot.metric_snapshots])
    evaluated_lookup: dict[str, TradingShadowingIntelligenceMetric] = {m.metric_key: m for m in evaluated_metrics}

    grey: str = console_color_codes["GREY"]
    red: str = console_color_codes["RED"]
    green: str = console_color_codes["GREEN"]
    reset: str = console_color_codes["RESET"]

    formatted_reasons: list[str] = []
    for key in master_metric_keys:
        metric_data: Optional[TradingShadowingIntelligenceMetric] = evaluated_lookup.get(key)
        if metric_data:
            key_color: str = grey
            content_color: str = grey

            if metric_data.is_golden:
                key_color = green
                content_color = green
            elif metric_data.is_toxic:
                key_color = red
                content_color = grey

            v_str: str = f"{metric_data.candidate_value:>12.2f}"

            wr_color: str = red if metric_data.bucket_win_rate < toxic_win_rate_threshold else content_color
            wr_str: str = f"{metric_data.bucket_win_rate * 100:>5.1f}%"

            pnl_color: str = red if metric_data.bucket_average_pnl < toxic_max_average_pnl else content_color
            pnl_str: str = f"{metric_data.bucket_average_pnl:>7.2f}%"

            hold_color: str = red if metric_data.bucket_average_holding_time > toxic_max_holding_time_minutes else content_color
            hold_str: str = f"{metric_data.bucket_average_holding_time / 60.0:>5.1f}h"

            vel_color: str = red if metric_data.bucket_capital_velocity < toxic_min_capital_velocity else content_color
            vel_str: str = f"{metric_data.bucket_capital_velocity:>6.2f}"

            ohr_color: str = content_color
            ohr_str: str = f"{metric_data.bucket_outlier_hit_rate * 100:>5.1f}%"

            trades_color: str = content_color
            trades_str: str = f"{metric_data.bucket_sample_count:>5}"

            formatted_reasons.append(
                f"{key_color}{key}{content_color} (V:{v_str}{content_color}, {wr_color}WR:{wr_str}{content_color}, "
                f"{pnl_color}PnL:{pnl_str}{content_color}, {ohr_color}OHR:{ohr_str}{content_color}, {hold_color}H:{hold_str}{content_color}, {vel_color}Vel:{vel_str}{content_color}, {trades_color}T:{trades_str}{content_color}){reset}"
            )
        else:
            v_placeholder: str = f"{'—':>12}"
            wr_placeholder: str = f"{'—':>5}%"
            pnl_placeholder: str = f"{'—':>7}%"
            hold_placeholder: str = f"{'—':>5}h"
            vel_placeholder: str = f"{'—':>6}"
            ohr_placeholder: str = f"{'—':>5}%"
            trades_placeholder: str = f"{'—':>5}"
            formatted_reasons.append(f"{grey}{key}{grey} (V:{v_placeholder}, WR:{wr_placeholder}, PnL:{pnl_placeholder}, OHR:{ohr_placeholder}, H:{hold_placeholder}, Vel:{vel_placeholder}, T:{trades_placeholder}){reset}")

    return " |   ".join(formatted_reasons)
