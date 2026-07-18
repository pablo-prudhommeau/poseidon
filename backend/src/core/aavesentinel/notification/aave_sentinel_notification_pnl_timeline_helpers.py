from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelNonTradingMovementSource,
    AaveSentinelNonTradingPeriodSourceBreakdown,
    AaveSentinelNonTradingPeriodSummary,
    AaveSentinelPerformanceSummary,
    AaveSentinelPnlTimelineBlock,
    AaveSentinelPnlTimelineBlockKind,
    AaveSentinelPositionSnapshot,
    AaveSentinelStrategyCycleSummary,
    AaveSentinelStrategyKind,
    AaveSentinelUnallocatedWealthMovement,
)
from src.core.aavesentinel.notification.aave_sentinel_notification_constants import (
    NON_TRADING_MOVEMENT_DISPLAY_EPSILON_USD,
    PNL_DETAIL_MAX_PAGE_COUNT,
    PNL_MOVEMENT_PAGE_MAX_CHARACTERS,
    PNL_MOVEMENT_PAGE_MAX_ENTRIES,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_constants import (
    INTEREST_ACCRUAL_COALESCE_MAX_GAP_SECONDS,
)
from src.core.utils.date_utils import get_current_local_datetime
from src.core.utils.format_utils import format_currency
from src.integrations.telegram.telegram_format_utils import build_telegram_section_block


def _format_timestamp_seconds(timestamp_seconds: int) -> str:
    return datetime.fromtimestamp(timestamp_seconds).astimezone().strftime("%d/%m/%Y %H:%M")


def _format_breakdown_bullet_line(source_label: str, formatted_monetary_values: str) -> str:
    return (
        f"      • {source_label} : "
        f"<code>{formatted_monetary_values}</code>"
    )


def _resolve_visible_source_breakdowns(
        source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown],
) -> list[AaveSentinelNonTradingPeriodSourceBreakdown]:
    ordered_source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown] = (
        _order_non_trading_period_source_breakdowns(
            source_breakdowns=source_breakdowns,
        )
    )
    visible_source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown] = []
    for source_breakdown in ordered_source_breakdowns:
        if abs(source_breakdown.pnl_usd) < NON_TRADING_MOVEMENT_DISPLAY_EPSILON_USD:
            continue
        visible_source_breakdowns.append(source_breakdown)
    return visible_source_breakdowns


def _append_pnl_breakdown_bullet_lines(
        movement_lines: list[str],
        total_pnl_usd: float,
        source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown],
        format_monetary_values: Callable[[float], str],
) -> None:
    visible_source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown] = (
        _resolve_visible_source_breakdowns(
            source_breakdowns=source_breakdowns,
        )
    )
    if not visible_source_breakdowns:
        return
    visible_breakdown_pnl_usd: float = sum(
        source_breakdown.pnl_usd
        for source_breakdown in visible_source_breakdowns
    )
    brut_pnl_usd: float = total_pnl_usd - visible_breakdown_pnl_usd
    movement_lines.append(
        _format_breakdown_bullet_line(
            source_label="Brut",
            formatted_monetary_values=format_monetary_values(brut_pnl_usd),
        )
    )
    for source_breakdown in visible_source_breakdowns:
        source_label: str = _resolve_non_trading_source_display_label(
            source=source_breakdown.source,
            dominant_asset_symbol=source_breakdown.dominant_asset_symbol,
        )
        movement_lines.append(
            _format_breakdown_bullet_line(
                source_label=source_label,
                formatted_monetary_values=format_monetary_values(source_breakdown.pnl_usd),
            )
        )


def _resolve_non_trading_source_display_label(
        source: AaveSentinelNonTradingMovementSource,
        dominant_asset_symbol: Optional[str] = None,
) -> str:
    if source == AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL:
        return "Dont intérêts"
    if source == AaveSentinelNonTradingMovementSource.GAS_FEES:
        return "Dont gas"
    if source == AaveSentinelNonTradingMovementSource.SLIPPAGE:
        return "Dont conversion"
    if dominant_asset_symbol is not None and dominant_asset_symbol != "":
        return f"Dont écart valo ({dominant_asset_symbol})"
    return "Dont écart valo"


def _resolve_open_strategy_mark_price_usd(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        position_snapshot: Optional[AaveSentinelPositionSnapshot],
) -> Optional[float]:
    if position_snapshot is None:
        return None
    for strategy in position_snapshot.strategies:
        if strategy.kind != strategy_cycle.kind:
            continue
        if strategy_cycle.main_asset_symbol is None:
            continue
        if strategy.main_asset_symbol != strategy_cycle.main_asset_symbol:
            continue
        if strategy.main_asset_price_usd <= 0:
            return None
        return strategy.main_asset_price_usd
    return None


def _build_strategy_cycle_entry_exit_price_line(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        position_snapshot: Optional[AaveSentinelPositionSnapshot] = None,
) -> Optional[str]:
    if strategy_cycle.entry_main_asset_price_usd <= 0:
        return None
    entry_price_label = format_currency(strategy_cycle.entry_main_asset_price_usd)
    if strategy_cycle.exit_main_asset_price_usd is not None and strategy_cycle.exit_main_asset_price_usd > 0:
        exit_price_label = format_currency(strategy_cycle.exit_main_asset_price_usd)
        return f"    💸 Entrée → sortie : <code>{entry_price_label} → {exit_price_label}</code>"

    open_strategy_mark_price_usd = _resolve_open_strategy_mark_price_usd(
        strategy_cycle=strategy_cycle,
        position_snapshot=position_snapshot,
    )
    if open_strategy_mark_price_usd is None:
        return f"    💸 Entrée : <code>{entry_price_label}</code>"
    exit_price_label = format_currency(open_strategy_mark_price_usd)
    return f"    💸 Entrée → actuel : <code>{entry_price_label} → {exit_price_label}</code>"


def _order_non_trading_period_source_breakdowns(source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown],
                                                ) -> list[AaveSentinelNonTradingPeriodSourceBreakdown]:
    source_display_order: list[AaveSentinelNonTradingMovementSource] = [
        AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
        AaveSentinelNonTradingMovementSource.GAS_FEES,
        AaveSentinelNonTradingMovementSource.SLIPPAGE,
        AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP,
    ]
    ordered_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown] = []
    for source in source_display_order:
        matching_breakdown: Optional[AaveSentinelNonTradingPeriodSourceBreakdown] = (
            _resolve_non_trading_period_source_breakdown(
                source_breakdowns=source_breakdowns,
                source=source,
            )
        )
        if matching_breakdown is not None:
            ordered_breakdowns.append(matching_breakdown)
    return ordered_breakdowns


def _resolve_non_trading_period_source_breakdown(source_breakdowns: list[AaveSentinelNonTradingPeriodSourceBreakdown],
                                                 source: AaveSentinelNonTradingMovementSource,
                                                 ) -> Optional[AaveSentinelNonTradingPeriodSourceBreakdown]:
    for source_breakdown in source_breakdowns:
        if source_breakdown.source == source:
            return source_breakdown
    return None


def _strategy_cycle_intersects_timestamp_window(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        window_start_timestamp_seconds: int,
        window_end_timestamp_seconds: int,
) -> bool:
    strategy_closed_at_timestamp_seconds: int = (
        window_end_timestamp_seconds + 1
        if strategy_cycle.closed_at_timestamp_seconds is None
        else strategy_cycle.closed_at_timestamp_seconds
    )
    if strategy_cycle.opened_at_timestamp_seconds > window_end_timestamp_seconds:
        return False
    if strategy_closed_at_timestamp_seconds < window_start_timestamp_seconds:
        return False
    if strategy_cycle.opened_at_timestamp_seconds == window_end_timestamp_seconds:
        return False
    if strategy_closed_at_timestamp_seconds == window_start_timestamp_seconds:
        return False
    return True


def _timestamp_window_intersects_any_strategy_cycle(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
        window_start_timestamp_seconds: int,
        window_end_timestamp_seconds: int,
) -> bool:
    for strategy_cycle in strategy_cycles:
        if _strategy_cycle_intersects_timestamp_window(
                strategy_cycle=strategy_cycle,
                window_start_timestamp_seconds=window_start_timestamp_seconds,
                window_end_timestamp_seconds=window_end_timestamp_seconds,
        ):
            return True
    return False


def _can_merge_non_trading_movement_into_period(
        current_period: AaveSentinelNonTradingPeriodSummary,
        wealth_movement: AaveSentinelUnallocatedWealthMovement,
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
) -> bool:
    windows_overlap_or_touch: bool = (
            wealth_movement.started_at_timestamp_seconds
            <= current_period.ended_at_timestamp_seconds
    )
    gap_seconds: int = (
            wealth_movement.started_at_timestamp_seconds
            - current_period.ended_at_timestamp_seconds
    )
    within_coalesce_gap: bool = (
            0 < gap_seconds <= INTEREST_ACCRUAL_COALESCE_MAX_GAP_SECONDS
    )
    if not windows_overlap_or_touch and not within_coalesce_gap:
        return False
    merged_started_at_timestamp_seconds: int = current_period.started_at_timestamp_seconds
    merged_ended_at_timestamp_seconds: int = max(
        current_period.ended_at_timestamp_seconds,
        wealth_movement.ended_at_timestamp_seconds,
    )
    if _timestamp_window_intersects_any_strategy_cycle(
            strategy_cycles=strategy_cycles,
            window_start_timestamp_seconds=merged_started_at_timestamp_seconds,
            window_end_timestamp_seconds=merged_ended_at_timestamp_seconds,
    ):
        return False
    bridge_start_timestamp_seconds: int = current_period.ended_at_timestamp_seconds
    bridge_end_timestamp_seconds: int = wealth_movement.started_at_timestamp_seconds
    if bridge_end_timestamp_seconds > bridge_start_timestamp_seconds:
        if _timestamp_window_intersects_any_strategy_cycle(
                strategy_cycles=strategy_cycles,
                window_start_timestamp_seconds=bridge_start_timestamp_seconds,
                window_end_timestamp_seconds=bridge_end_timestamp_seconds,
        ):
            return False
    return True


def _merge_non_trading_movement_into_period(current_period: AaveSentinelNonTradingPeriodSummary,
                                            wealth_movement: AaveSentinelUnallocatedWealthMovement,
                                            ) -> None:
    current_period.ended_at_timestamp_seconds = max(
        current_period.ended_at_timestamp_seconds,
        wealth_movement.ended_at_timestamp_seconds,
    )
    current_period.total_pnl_usd += wealth_movement.pnl_usd
    matching_breakdown: Optional[AaveSentinelNonTradingPeriodSourceBreakdown] = (
        _resolve_non_trading_period_source_breakdown(
            source_breakdowns=current_period.source_breakdowns,
            source=wealth_movement.source,
        )
    )
    if matching_breakdown is None:
        current_period.source_breakdowns.append(
            AaveSentinelNonTradingPeriodSourceBreakdown(
                source=wealth_movement.source,
                pnl_usd=wealth_movement.pnl_usd,
                dominant_asset_symbol=wealth_movement.dominant_asset_symbol,
            )
        )
        return
    matching_breakdown.pnl_usd += wealth_movement.pnl_usd
    if (
            matching_breakdown.dominant_asset_symbol is not None
            and wealth_movement.dominant_asset_symbol is not None
            and matching_breakdown.dominant_asset_symbol != wealth_movement.dominant_asset_symbol
    ):
        matching_breakdown.dominant_asset_symbol = None
    elif (
            matching_breakdown.dominant_asset_symbol is None
            and wealth_movement.dominant_asset_symbol is not None
    ):
        matching_breakdown.dominant_asset_symbol = wealth_movement.dominant_asset_symbol


def _collect_strategy_occupied_timestamp_windows(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
        fallback_open_ended_at_timestamp_seconds: int,
) -> list[tuple[int, int]]:
    occupied_timestamp_windows: list[tuple[int, int]] = []
    for strategy_cycle in strategy_cycles:
        occupied_ended_at_timestamp_seconds: int = (
            fallback_open_ended_at_timestamp_seconds
            if strategy_cycle.closed_at_timestamp_seconds is None
            else strategy_cycle.closed_at_timestamp_seconds
        )
        occupied_timestamp_windows.append(
            (
                strategy_cycle.opened_at_timestamp_seconds,
                occupied_ended_at_timestamp_seconds,
            )
        )
    occupied_timestamp_windows.sort(key=lambda timestamp_window: timestamp_window[0])
    return occupied_timestamp_windows


def _split_wealth_movement_around_strategy_cycles(
        wealth_movement: AaveSentinelUnallocatedWealthMovement,
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
) -> list[AaveSentinelUnallocatedWealthMovement]:
    if not _timestamp_window_intersects_any_strategy_cycle(
            strategy_cycles=strategy_cycles,
            window_start_timestamp_seconds=wealth_movement.started_at_timestamp_seconds,
            window_end_timestamp_seconds=wealth_movement.ended_at_timestamp_seconds,
    ):
        return [wealth_movement]

    occupied_timestamp_windows: list[tuple[int, int]] = (
        _collect_strategy_occupied_timestamp_windows(
            strategy_cycles=strategy_cycles,
            fallback_open_ended_at_timestamp_seconds=(
                    wealth_movement.ended_at_timestamp_seconds + 1
            ),
        )
    )
    idle_segments: list[tuple[int, int]] = []
    segment_cursor_timestamp_seconds: int = wealth_movement.started_at_timestamp_seconds
    for occupied_started_at_timestamp_seconds, occupied_ended_at_timestamp_seconds in (
            occupied_timestamp_windows
    ):
        if occupied_ended_at_timestamp_seconds <= segment_cursor_timestamp_seconds:
            continue
        if occupied_started_at_timestamp_seconds >= wealth_movement.ended_at_timestamp_seconds:
            break
        if occupied_started_at_timestamp_seconds > segment_cursor_timestamp_seconds:
            idle_segments.append(
                (
                    segment_cursor_timestamp_seconds,
                    min(
                        occupied_started_at_timestamp_seconds,
                        wealth_movement.ended_at_timestamp_seconds,
                    ),
                )
            )
        segment_cursor_timestamp_seconds = max(
            segment_cursor_timestamp_seconds,
            occupied_ended_at_timestamp_seconds,
        )
    if segment_cursor_timestamp_seconds < wealth_movement.ended_at_timestamp_seconds:
        idle_segments.append(
            (
                segment_cursor_timestamp_seconds,
                wealth_movement.ended_at_timestamp_seconds,
            )
        )

    total_idle_duration_seconds: int = sum(
        max(0, idle_ended_at_timestamp_seconds - idle_started_at_timestamp_seconds)
        for idle_started_at_timestamp_seconds, idle_ended_at_timestamp_seconds in idle_segments
    )
    if total_idle_duration_seconds <= 0:
        return [wealth_movement]

    split_wealth_movements: list[AaveSentinelUnallocatedWealthMovement] = []
    for idle_started_at_timestamp_seconds, idle_ended_at_timestamp_seconds in idle_segments:
        idle_duration_seconds: int = (
                idle_ended_at_timestamp_seconds - idle_started_at_timestamp_seconds
        )
        if idle_duration_seconds <= 0:
            continue
        split_pnl_usd: float = (
                wealth_movement.pnl_usd
                * (idle_duration_seconds / total_idle_duration_seconds)
        )
        split_wealth_movements.append(
            AaveSentinelUnallocatedWealthMovement(
                source=wealth_movement.source,
                started_at_timestamp_seconds=idle_started_at_timestamp_seconds,
                ended_at_timestamp_seconds=idle_ended_at_timestamp_seconds,
                pnl_usd=split_pnl_usd,
                dominant_asset_symbol=wealth_movement.dominant_asset_symbol,
            )
        )
    return split_wealth_movements


def _cluster_non_trading_periods(unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement],
                                 strategy_cycles: list[AaveSentinelStrategyCycleSummary],
                                 ) -> list[AaveSentinelNonTradingPeriodSummary]:
    visible_movements: list[AaveSentinelUnallocatedWealthMovement] = []
    for wealth_movement in unallocated_wealth_movements:
        if abs(wealth_movement.pnl_usd) < NON_TRADING_MOVEMENT_DISPLAY_EPSILON_USD:
            continue
        visible_movements.extend(
            _split_wealth_movement_around_strategy_cycles(
                wealth_movement=wealth_movement,
                strategy_cycles=strategy_cycles,
            )
        )
    visible_movements = [
        wealth_movement
        for wealth_movement in visible_movements
        if abs(wealth_movement.pnl_usd) >= NON_TRADING_MOVEMENT_DISPLAY_EPSILON_USD
    ]
    visible_movements.sort(
        key=lambda wealth_movement: (
            wealth_movement.started_at_timestamp_seconds,
            wealth_movement.ended_at_timestamp_seconds,
            wealth_movement.source.value,
        ),
    )
    clustered_periods: list[AaveSentinelNonTradingPeriodSummary] = []
    for wealth_movement in visible_movements:
        if clustered_periods and _can_merge_non_trading_movement_into_period(
                current_period=clustered_periods[-1],
                wealth_movement=wealth_movement,
                strategy_cycles=strategy_cycles,
        ):
            _merge_non_trading_movement_into_period(
                current_period=clustered_periods[-1],
                wealth_movement=wealth_movement,
            )
            continue
        clustered_periods.append(
            AaveSentinelNonTradingPeriodSummary(
                started_at_timestamp_seconds=wealth_movement.started_at_timestamp_seconds,
                ended_at_timestamp_seconds=wealth_movement.ended_at_timestamp_seconds,
                total_pnl_usd=wealth_movement.pnl_usd,
                source_breakdowns=[
                    AaveSentinelNonTradingPeriodSourceBreakdown(
                        source=wealth_movement.source,
                        pnl_usd=wealth_movement.pnl_usd,
                        dominant_asset_symbol=wealth_movement.dominant_asset_symbol,
                    ),
                ],
            )
        )
    return clustered_periods


def _resolve_strategy_cycle_period_end_label(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        latest_aave_position_snapshot_at: datetime,
) -> str:
    if strategy_cycle.closed_at_timestamp_seconds is not None:
        return _format_timestamp_seconds(strategy_cycle.closed_at_timestamp_seconds)
    return latest_aave_position_snapshot_at.astimezone().strftime("%d/%m/%Y %H:%M")


def _build_strategy_cycle_movement_lines(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        format_monetary_values: Callable[[float], str],
        latest_aave_position_snapshot_at: datetime,
        position_snapshot: Optional[AaveSentinelPositionSnapshot],
) -> list[str]:
    asset_label: str
    if strategy_cycle.main_asset_symbol is None:
        asset_label = "inconnu"
    else:
        asset_label = strategy_cycle.main_asset_symbol
    strategy_kind_emoji: str = (
        "📈"
        if strategy_cycle.kind == AaveSentinelStrategyKind.LONG
        else "📉"
    )
    opened_at_label: str = _format_timestamp_seconds(
        strategy_cycle.opened_at_timestamp_seconds,
    )
    period_end_label: str = _resolve_strategy_cycle_period_end_label(
        strategy_cycle=strategy_cycle,
        latest_aave_position_snapshot_at=latest_aave_position_snapshot_at,
    )
    cycle_lines: list[str] = [
        f"{strategy_kind_emoji} <b>{strategy_cycle.kind.value}</b> {asset_label}",
        f"    ⚡ Levier : <code>x{strategy_cycle.leverage:.2f}</code>",
        f"    📅 {opened_at_label} → {period_end_label}",
    ]
    entry_exit_price_line: Optional[str] = _build_strategy_cycle_entry_exit_price_line(
        strategy_cycle=strategy_cycle,
        position_snapshot=position_snapshot,
    )
    if entry_exit_price_line is not None:
        cycle_lines.append(entry_exit_price_line)
    cycle_lines.append(
        f"    📊 PnL : <code>{format_monetary_values(strategy_cycle.gross_pnl_usd)}</code>",
    )
    _append_pnl_breakdown_bullet_lines(
        movement_lines=cycle_lines,
        total_pnl_usd=strategy_cycle.gross_pnl_usd,
        source_breakdowns=strategy_cycle.absorbed_source_breakdowns,
        format_monetary_values=format_monetary_values,
    )
    return cycle_lines


def _build_non_trading_period_movement_lines(non_trading_period: AaveSentinelNonTradingPeriodSummary,
                                             format_monetary_values: Callable[[float], str],
                                             ) -> list[str]:
    started_at_label: str = _format_timestamp_seconds(
        non_trading_period.started_at_timestamp_seconds,
    )
    ended_at_label: str = _format_timestamp_seconds(
        non_trading_period.ended_at_timestamp_seconds,
    )
    date_label: str
    if (
            non_trading_period.started_at_timestamp_seconds
            == non_trading_period.ended_at_timestamp_seconds
    ):
        date_label = started_at_label
    else:
        date_label = f"{started_at_label} → {ended_at_label}"
    movement_lines: list[str] = [
        "💤 <b>Hors trading</b>",
        f"    📅 {date_label}",
        f"    📊 PnL : <code>{format_monetary_values(non_trading_period.total_pnl_usd)}</code>",
    ]
    _append_pnl_breakdown_bullet_lines(
        movement_lines=movement_lines,
        total_pnl_usd=non_trading_period.total_pnl_usd,
        source_breakdowns=non_trading_period.source_breakdowns,
        format_monetary_values=format_monetary_values,
    )
    return movement_lines


def _resolve_strategy_cycle_closed_at_timestamp_seconds(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        fallback_open_ended_at_timestamp_seconds: int,
) -> int:
    if strategy_cycle.closed_at_timestamp_seconds is None:
        return fallback_open_ended_at_timestamp_seconds
    return strategy_cycle.closed_at_timestamp_seconds


_OPEN_STRATEGY_CYCLE_SPAN_SECONDS: int = 10 ** 12


def _is_wealth_movement_fully_inside_strategy_cycle(
        wealth_movement: AaveSentinelUnallocatedWealthMovement,
        strategy_cycle: AaveSentinelStrategyCycleSummary,
) -> bool:
    strategy_closed_at_timestamp_seconds: int = (
        _resolve_strategy_cycle_closed_at_timestamp_seconds(
            strategy_cycle=strategy_cycle,
            fallback_open_ended_at_timestamp_seconds=(
                    wealth_movement.ended_at_timestamp_seconds + 1
            ),
        )
    )
    if wealth_movement.started_at_timestamp_seconds < strategy_cycle.opened_at_timestamp_seconds:
        return False
    if wealth_movement.ended_at_timestamp_seconds > strategy_closed_at_timestamp_seconds:
        return False
    return True


def _resolve_strategy_cycle_span_seconds_for_fold_ranking(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
) -> int:
    if strategy_cycle.closed_at_timestamp_seconds is None:
        return _OPEN_STRATEGY_CYCLE_SPAN_SECONDS
    return max(
        0,
        strategy_cycle.closed_at_timestamp_seconds - strategy_cycle.opened_at_timestamp_seconds,
    )


def _resolve_tightest_containing_strategy_cycle(
        wealth_movement: AaveSentinelUnallocatedWealthMovement,
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
) -> Optional[AaveSentinelStrategyCycleSummary]:
    containing_strategy_cycles: list[AaveSentinelStrategyCycleSummary] = [
        strategy_cycle
        for strategy_cycle in strategy_cycles
        if _is_wealth_movement_fully_inside_strategy_cycle(
            wealth_movement=wealth_movement,
            strategy_cycle=strategy_cycle,
        )
    ]
    if not containing_strategy_cycles:
        return None
    return min(
        containing_strategy_cycles,
        key=_resolve_strategy_cycle_span_seconds_for_fold_ranking,
    )


def _merge_source_breakdown_into_strategy_cycle(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        source: AaveSentinelNonTradingMovementSource,
        pnl_usd: float,
        dominant_asset_symbol: Optional[str],
) -> None:
    matching_breakdown: Optional[AaveSentinelNonTradingPeriodSourceBreakdown] = (
        _resolve_non_trading_period_source_breakdown(
            source_breakdowns=strategy_cycle.absorbed_source_breakdowns,
            source=source,
        )
    )
    if matching_breakdown is None:
        strategy_cycle.absorbed_source_breakdowns.append(
            AaveSentinelNonTradingPeriodSourceBreakdown(
                source=source,
                pnl_usd=pnl_usd,
                dominant_asset_symbol=dominant_asset_symbol,
            )
        )
        return
    matching_breakdown.pnl_usd += pnl_usd
    if (
            matching_breakdown.dominant_asset_symbol is not None
            and dominant_asset_symbol is not None
            and matching_breakdown.dominant_asset_symbol != dominant_asset_symbol
    ):
        matching_breakdown.dominant_asset_symbol = None
    elif (
            matching_breakdown.dominant_asset_symbol is None
            and dominant_asset_symbol is not None
    ):
        matching_breakdown.dominant_asset_symbol = dominant_asset_symbol


def _fold_fully_overlapping_unallocated_into_strategy_cycles(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
        unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement],
) -> tuple[list[AaveSentinelStrategyCycleSummary], list[AaveSentinelUnallocatedWealthMovement]]:
    display_strategy_cycles: list[AaveSentinelStrategyCycleSummary] = [
        strategy_cycle.model_copy(deep=True)
        for strategy_cycle in strategy_cycles
    ]
    remaining_unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement] = []
    for wealth_movement in unallocated_wealth_movements:
        containing_strategy_cycle: Optional[AaveSentinelStrategyCycleSummary] = (
            _resolve_tightest_containing_strategy_cycle(
                wealth_movement=wealth_movement,
                strategy_cycles=display_strategy_cycles,
            )
        )
        if containing_strategy_cycle is None:
            remaining_unallocated_wealth_movements.append(wealth_movement)
            continue
        containing_strategy_cycle.gross_pnl_usd += wealth_movement.pnl_usd
        containing_strategy_cycle.trading_pnl_usd = containing_strategy_cycle.gross_pnl_usd
        _merge_source_breakdown_into_strategy_cycle(
            strategy_cycle=containing_strategy_cycle,
            source=wealth_movement.source,
            pnl_usd=wealth_movement.pnl_usd,
            dominant_asset_symbol=wealth_movement.dominant_asset_symbol,
        )
    return display_strategy_cycles, remaining_unallocated_wealth_movements


def _build_pnl_timeline_blocks(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
        unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement],
        format_monetary_values: Callable[[float], str],
        latest_aave_position_snapshot_at: datetime,
        position_snapshot: Optional[AaveSentinelPositionSnapshot],
) -> list[AaveSentinelPnlTimelineBlock]:
    display_strategy_cycles, display_unallocated_wealth_movements = (
        _fold_fully_overlapping_unallocated_into_strategy_cycles(
            strategy_cycles=strategy_cycles,
            unallocated_wealth_movements=unallocated_wealth_movements,
        )
    )
    non_trading_periods: list[AaveSentinelNonTradingPeriodSummary] = (
        _cluster_non_trading_periods(
            unallocated_wealth_movements=display_unallocated_wealth_movements,
            strategy_cycles=display_strategy_cycles,
        )
    )
    timeline_blocks: list[AaveSentinelPnlTimelineBlock] = []
    for strategy_cycle_index, strategy_cycle in enumerate(display_strategy_cycles):
        timeline_blocks.append(
            AaveSentinelPnlTimelineBlock(
                kind=AaveSentinelPnlTimelineBlockKind.STRATEGY,
                sort_timestamp_seconds=strategy_cycle.opened_at_timestamp_seconds,
                sort_index=strategy_cycle_index,
                lines=_build_strategy_cycle_movement_lines(
                    strategy_cycle=strategy_cycle,
                    format_monetary_values=format_monetary_values,
                    latest_aave_position_snapshot_at=latest_aave_position_snapshot_at,
                    position_snapshot=position_snapshot,
                ),
            )
        )
    for non_trading_period_index, non_trading_period in enumerate(non_trading_periods):
        timeline_blocks.append(
            AaveSentinelPnlTimelineBlock(
                kind=AaveSentinelPnlTimelineBlockKind.NON_TRADING_PERIOD,
                sort_timestamp_seconds=non_trading_period.started_at_timestamp_seconds,
                sort_index=non_trading_period_index,
                lines=_build_non_trading_period_movement_lines(
                    non_trading_period=non_trading_period,
                    format_monetary_values=format_monetary_values,
                ),
            )
        )
    timeline_blocks.sort(
        key=lambda timeline_block: (
            timeline_block.sort_timestamp_seconds,
            0 if timeline_block.kind == AaveSentinelPnlTimelineBlockKind.NON_TRADING_PERIOD else 1,
            timeline_block.sort_index,
        ),
    )
    return timeline_blocks


def _build_pnl_movement_detail_pages(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
        unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement],
        format_monetary_values: Callable[[float], str],
        latest_aave_position_snapshot_at: datetime,
        position_snapshot: Optional[AaveSentinelPositionSnapshot],
) -> list[list[str]]:
    timeline_blocks: list[AaveSentinelPnlTimelineBlock] = _build_pnl_timeline_blocks(
        strategy_cycles=strategy_cycles,
        unallocated_wealth_movements=unallocated_wealth_movements,
        format_monetary_values=format_monetary_values,
        latest_aave_position_snapshot_at=latest_aave_position_snapshot_at,
        position_snapshot=position_snapshot,
    )
    if not timeline_blocks:
        return [[]]

    movement_pages: list[list[str]] = []
    current_page_lines: list[str] = []
    current_page_entry_count: int = 0
    previous_block_kind: Optional[AaveSentinelPnlTimelineBlockKind] = None
    for timeline_block in timeline_blocks:
        block_lines: list[str] = list(timeline_block.lines)
        if previous_block_kind is not None:
            block_lines = [""] + block_lines
        candidate_page_lines: list[str] = current_page_lines + block_lines
        candidate_character_count: int = len("\n".join(candidate_page_lines))
        exceeds_entry_budget: bool = current_page_entry_count >= PNL_MOVEMENT_PAGE_MAX_ENTRIES
        exceeds_character_budget: bool = (
                bool(current_page_lines)
                and candidate_character_count > PNL_MOVEMENT_PAGE_MAX_CHARACTERS
        )
        if exceeds_entry_budget or exceeds_character_budget:
            movement_pages.append(current_page_lines)
            current_page_lines = list(block_lines)
            current_page_entry_count = 1
            previous_block_kind = timeline_block.kind
            if len(movement_pages) >= PNL_DETAIL_MAX_PAGE_COUNT:
                break
            continue
        current_page_lines.extend(block_lines)
        current_page_entry_count += 1
        previous_block_kind = timeline_block.kind

    if len(movement_pages) < PNL_DETAIL_MAX_PAGE_COUNT and current_page_lines:
        movement_pages.append(current_page_lines)
    elif not movement_pages:
        movement_pages.append(current_page_lines)

    packed_entry_count: int = sum(
        1
        for page_lines in movement_pages
        for page_line in page_lines
        if (
                page_line.startswith("📈 ")
                or page_line.startswith("📉 ")
                or page_line.startswith("💤 ")
        )
    )
    remaining_entry_count: int = len(timeline_blocks) - packed_entry_count
    if remaining_entry_count > 0 and movement_pages:
        movement_pages[-1].append(
            f"… {remaining_entry_count} mouvement(s) restants",
        )
    return movement_pages


def build_pnl_detail_message_pages(
        performance_summary: AaveSentinelPerformanceSummary,
        usd_eur_exchange_rate: float,
        position_snapshot: Optional[AaveSentinelPositionSnapshot] = None,
) -> list[str]:
    def format_monetary_values(amount_in_usd: float) -> str:
        amount_in_eur = amount_in_usd * usd_eur_exchange_rate
        return (
            f"{format_currency(amount_in_eur, currency='EUR')} "
            f"({format_currency(amount_in_usd)})"
        )

    if position_snapshot is not None:
        latest_aave_position_snapshot_at: datetime = position_snapshot.captured_at
    elif performance_summary.refreshed_at is not None:
        latest_aave_position_snapshot_at = performance_summary.refreshed_at
    else:
        latest_aave_position_snapshot_at = get_current_local_datetime()

    movement_pages = _build_pnl_movement_detail_pages(
        strategy_cycles=performance_summary.strategy_cycles,
        unallocated_wealth_movements=performance_summary.unallocated_wealth_movements,
        format_monetary_values=format_monetary_values,
        latest_aave_position_snapshot_at=latest_aave_position_snapshot_at,
        position_snapshot=position_snapshot,
    )
    interest_detail_lines: list[str] = [
        f"📈 APY supply : <code>{format_monetary_values(performance_summary.cumulative_supply_interest_usd)}</code>",
        f"📉 APY borrow : <code>{format_monetary_values(-performance_summary.cumulative_borrow_interest_usd)}</code>",
        f"🏦 APY net : <code>{format_monetary_values(performance_summary.cumulative_net_interest_usd)}</code>",
    ]
    for interest_breakdown in performance_summary.interest_breakdowns:
        interest_detail_lines.extend(
            [
                f"  • {interest_breakdown.asset_symbol}",
                f"    ◦ Supply : <code>{format_monetary_values(interest_breakdown.supply_interest_usd)}</code>",
                f"    ◦ Borrow : <code>{format_monetary_values(-interest_breakdown.borrow_interest_usd)}</code>",
                f"    ◦ Net : <code>{format_monetary_values(interest_breakdown.net_interest_usd)}</code>",
            ]
        )

    formatted_pages: list[str] = []
    for page_index, movement_detail_lines in enumerate(movement_pages):
        if not movement_detail_lines:
            movement_detail_lines = ["  <i>Aucun mouvement</i>"]
        if page_index == 0:
            message_sections: list[str] = [
                build_telegram_section_block("Intérêts AAVE", interest_detail_lines),
                build_telegram_section_block("Mouvements", movement_detail_lines),
            ]
            formatted_pages.append("\n".join(section for section in message_sections if section))
            continue
        formatted_pages.append("\n".join(movement_detail_lines))
    if not formatted_pages:
        formatted_pages.append(
            "\n".join(
                [
                    build_telegram_section_block("Intérêts AAVE", interest_detail_lines),
                    build_telegram_section_block("Mouvements", ["  <i>Aucun mouvement</i>"]),
                ]
            )
        )
    return formatted_pages
