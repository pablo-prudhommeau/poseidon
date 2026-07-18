from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import TOKEN_AMOUNT_DUST_EPSILON
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelPerformanceSummary,
    AaveSentinelPositionCheckpoint,
    AaveSentinelReserveInterestBreakdown,
    AaveSentinelReserveRegistry,
    AaveSentinelStrategyCycleSummary,
    AaveSentinelStrategyKind,
    AaveSentinelUnallocatedWealthMovement,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_cycle_gross_pnl_usd,
    compute_latent_profit_and_loss_usd,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_cycle_pnl_helpers import (
    apply_fresh_capital_adjusted_pnl_to_strategy_cycles,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_scaled_balance_helpers import (
    _resolve_interest_breakdown_by_symbol,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_wallet_balance_helpers import (
    resolve_asset_price_usd_for_symbol,
)
from src.core.utils.date_utils import get_current_local_datetime


def build_strategy_cycles_from_checkpoints(
        position_checkpoints: list[AaveSentinelPositionCheckpoint],
        reserve_registry: Optional[AaveSentinelReserveRegistry] = None,
) -> list[AaveSentinelStrategyCycleSummary]:
    if not position_checkpoints:
        return []

    short_cycles = _build_parallel_strategy_cycles_for_kind(
        position_checkpoints=position_checkpoints,
        strategy_kind=AaveSentinelStrategyKind.SHORT,
        reserve_registry=reserve_registry,
    )
    long_cycles = _build_parallel_strategy_cycles_for_kind(
        position_checkpoints=position_checkpoints,
        strategy_kind=AaveSentinelStrategyKind.LONG,
        reserve_registry=reserve_registry,
    )
    combined_cycles = short_cycles + long_cycles
    combined_cycles.sort(
        key=lambda strategy_cycle: (
            strategy_cycle.opened_at_timestamp_seconds,
            strategy_cycle.kind.value,
        ),
    )
    apply_fresh_capital_adjusted_pnl_to_strategy_cycles(
        position_checkpoints=position_checkpoints,
        strategy_cycles=combined_cycles,
    )
    return combined_cycles


def _build_parallel_strategy_cycles_for_kind(
        position_checkpoints: list[AaveSentinelPositionCheckpoint],
        strategy_kind: AaveSentinelStrategyKind,
        reserve_registry: Optional[AaveSentinelReserveRegistry],
) -> list[AaveSentinelStrategyCycleSummary]:
    strategy_cycles: list[AaveSentinelStrategyCycleSummary] = []
    open_cycle_opening_checkpoint: Optional[AaveSentinelPositionCheckpoint] = None
    last_active_checkpoint: Optional[AaveSentinelPositionCheckpoint] = None

    for position_checkpoint in position_checkpoints:
        kind_is_active = strategy_kind in position_checkpoint.active_strategy_kinds
        if kind_is_active:
            if open_cycle_opening_checkpoint is None:
                open_cycle_opening_checkpoint = position_checkpoint
            last_active_checkpoint = position_checkpoint
            continue

        if open_cycle_opening_checkpoint is not None and last_active_checkpoint is not None:
            strategy_cycles.append(
                _build_strategy_cycle_summary(
                    opening_checkpoint=open_cycle_opening_checkpoint,
                    equity_closing_checkpoint=last_active_checkpoint,
                    period_end_checkpoint=position_checkpoint,
                    strategy_kind=strategy_kind,
                    is_open=False,
                    reserve_registry=reserve_registry,
                )
            )
            open_cycle_opening_checkpoint = None
            last_active_checkpoint = None

    if open_cycle_opening_checkpoint is not None and last_active_checkpoint is not None:
        strategy_cycles.append(
            _build_strategy_cycle_summary(
                opening_checkpoint=open_cycle_opening_checkpoint,
                equity_closing_checkpoint=last_active_checkpoint,
                period_end_checkpoint=last_active_checkpoint,
                strategy_kind=strategy_kind,
                is_open=True,
                reserve_registry=reserve_registry,
            )
        )
    return strategy_cycles


def merge_interest_breakdowns(
        interest_breakdown_batches: list[list[AaveSentinelReserveInterestBreakdown]],
) -> list[AaveSentinelReserveInterestBreakdown]:
    merged_interest_breakdowns: list[AaveSentinelReserveInterestBreakdown] = []
    for interest_breakdown_batch in interest_breakdown_batches:
        for interest_breakdown in interest_breakdown_batch:
            existing_breakdown = _resolve_interest_breakdown_by_symbol(
                interest_breakdowns=merged_interest_breakdowns,
                asset_symbol=interest_breakdown.asset_symbol,
            )
            if existing_breakdown is None:
                merged_interest_breakdowns.append(
                    AaveSentinelReserveInterestBreakdown(
                        asset_symbol=interest_breakdown.asset_symbol,
                        supply_interest_usd=interest_breakdown.supply_interest_usd,
                        borrow_interest_usd=interest_breakdown.borrow_interest_usd,
                        net_interest_usd=interest_breakdown.net_interest_usd,
                    )
                )
                continue
            existing_breakdown.supply_interest_usd += interest_breakdown.supply_interest_usd
            existing_breakdown.borrow_interest_usd += interest_breakdown.borrow_interest_usd
            existing_breakdown.net_interest_usd = (
                    existing_breakdown.supply_interest_usd - existing_breakdown.borrow_interest_usd
            )
    return merged_interest_breakdowns


def aggregate_performance_summary(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
        interest_breakdowns: list[AaveSentinelReserveInterestBreakdown],
        total_equity_usd: float,
        net_capital_deployed_usd: float,
        unallocated_wealth_movements: Optional[list[AaveSentinelUnallocatedWealthMovement]] = None,
) -> AaveSentinelPerformanceSummary:
    resolved_unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement] = (
        [] if unallocated_wealth_movements is None else unallocated_wealth_movements
    )
    cumulative_supply_interest_usd = sum(
        interest_breakdown.supply_interest_usd for interest_breakdown in interest_breakdowns
    )
    cumulative_borrow_interest_usd = sum(
        interest_breakdown.borrow_interest_usd for interest_breakdown in interest_breakdowns
    )
    cumulative_net_interest_usd = cumulative_supply_interest_usd - cumulative_borrow_interest_usd
    global_pnl_usd = compute_latent_profit_and_loss_usd(
        total_equity_usd=total_equity_usd,
        net_capital_deployed_usd=net_capital_deployed_usd,
    )
    total_trading_pnl_usd = global_pnl_usd - cumulative_net_interest_usd

    strategy_legs_pnl_usd: float = 0.0
    latent_trading_pnl_usd: float = 0.0
    for strategy_cycle in strategy_cycles:
        strategy_legs_pnl_usd += strategy_cycle.gross_pnl_usd
        if strategy_cycle.is_open:
            latent_trading_pnl_usd += strategy_cycle.gross_pnl_usd
    realized_trading_pnl_usd = total_trading_pnl_usd - latent_trading_pnl_usd
    unallocated_wealth_pnl_usd = sum(
        unallocated_wealth_movement.pnl_usd
        for unallocated_wealth_movement in resolved_unallocated_wealth_movements
    )

    return AaveSentinelPerformanceSummary(
        global_pnl_usd=global_pnl_usd,
        realized_trading_pnl_usd=realized_trading_pnl_usd,
        latent_trading_pnl_usd=latent_trading_pnl_usd,
        total_trading_pnl_usd=total_trading_pnl_usd,
        strategy_legs_pnl_usd=strategy_legs_pnl_usd,
        unallocated_wealth_pnl_usd=unallocated_wealth_pnl_usd,
        pnl_reconciliation_gap_usd=(
                global_pnl_usd - strategy_legs_pnl_usd - unallocated_wealth_pnl_usd
        ),
        cumulative_supply_interest_usd=cumulative_supply_interest_usd,
        cumulative_borrow_interest_usd=cumulative_borrow_interest_usd,
        cumulative_net_interest_usd=cumulative_net_interest_usd,
        interest_breakdowns=interest_breakdowns,
        strategy_cycles=strategy_cycles,
        unallocated_wealth_movements=resolved_unallocated_wealth_movements,
        is_available=True,
        refreshed_at=get_current_local_datetime(),
    )


def _resolve_strategy_equity_usd(
        position_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    if strategy_kind == AaveSentinelStrategyKind.SHORT:
        return position_checkpoint.short_strategy_equity_usd
    return position_checkpoint.long_strategy_equity_usd


def _resolve_cumulative_strategy_capital_usd(
        position_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    if strategy_kind == AaveSentinelStrategyKind.SHORT:
        return position_checkpoint.cumulative_short_strategy_capital_usd
    return position_checkpoint.cumulative_long_strategy_capital_usd


def _resolve_closed_strategy_mark_equity_usd(
        equity_closing_checkpoint: AaveSentinelPositionCheckpoint,
        period_end_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    if strategy_kind == AaveSentinelStrategyKind.SHORT:
        before_transfer_strategy_equity_usd = period_end_checkpoint.before_transfer_short_strategy_equity_usd
        if abs(before_transfer_strategy_equity_usd) >= TOKEN_AMOUNT_DUST_EPSILON:
            return before_transfer_strategy_equity_usd
        return equity_closing_checkpoint.short_strategy_equity_usd

    before_transfer_strategy_equity_usd = period_end_checkpoint.before_transfer_long_strategy_equity_usd
    if abs(before_transfer_strategy_equity_usd) >= TOKEN_AMOUNT_DUST_EPSILON:
        return before_transfer_strategy_equity_usd
    return equity_closing_checkpoint.long_strategy_equity_usd


def _build_strategy_cycle_summary(
        opening_checkpoint: AaveSentinelPositionCheckpoint,
        equity_closing_checkpoint: AaveSentinelPositionCheckpoint,
        period_end_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
        is_open: bool,
        reserve_registry: Optional[AaveSentinelReserveRegistry],
) -> AaveSentinelStrategyCycleSummary:
    opening_strategy_equity_usd = _resolve_strategy_equity_usd(
        position_checkpoint=opening_checkpoint,
        strategy_kind=strategy_kind,
    )
    if is_open:
        closing_strategy_equity_usd = _resolve_strategy_equity_usd(
            position_checkpoint=equity_closing_checkpoint,
            strategy_kind=strategy_kind,
        )
        capital_closing_checkpoint = equity_closing_checkpoint
        silent_mark_to_market_usd = 0.0
    else:
        event_closing_strategy_equity_usd = _resolve_strategy_equity_usd(
            position_checkpoint=equity_closing_checkpoint,
            strategy_kind=strategy_kind,
        )
        marked_closing_strategy_equity_usd = _resolve_closed_strategy_mark_equity_usd(
            equity_closing_checkpoint=equity_closing_checkpoint,
            period_end_checkpoint=period_end_checkpoint,
            strategy_kind=strategy_kind,
        )
        closing_strategy_equity_usd = marked_closing_strategy_equity_usd
        capital_closing_checkpoint = equity_closing_checkpoint
        silent_mark_to_market_usd = (
                marked_closing_strategy_equity_usd - event_closing_strategy_equity_usd
        )

    net_strategy_capital_usd = (
            _resolve_cumulative_strategy_capital_usd(
                position_checkpoint=capital_closing_checkpoint,
                strategy_kind=strategy_kind,
            )
            - _resolve_cumulative_strategy_capital_usd(
        position_checkpoint=opening_checkpoint,
        strategy_kind=strategy_kind,
    )
    )
    gross_pnl_usd = compute_cycle_gross_pnl_usd(
        opening_equity_usd=opening_strategy_equity_usd,
        closing_equity_usd=closing_strategy_equity_usd,
        net_external_capital_usd=net_strategy_capital_usd,
    )
    main_asset_symbol = (
        opening_checkpoint.short_main_asset_symbol
        if strategy_kind == AaveSentinelStrategyKind.SHORT
        else opening_checkpoint.long_main_asset_symbol
    )
    opening_leverage = (
        opening_checkpoint.short_leverage
        if strategy_kind == AaveSentinelStrategyKind.SHORT
        else opening_checkpoint.long_leverage
    )
    entry_main_asset_price_usd = resolve_asset_price_usd_for_symbol(
        asset_prices_usd=opening_checkpoint.asset_prices_usd,
        asset_symbol=main_asset_symbol,
        reserve_registry=reserve_registry,
    )
    exit_main_asset_price_usd: Optional[float] = None
    if not is_open:
        resolved_exit_main_asset_price_usd = resolve_asset_price_usd_for_symbol(
            asset_prices_usd=period_end_checkpoint.asset_prices_usd,
            asset_symbol=main_asset_symbol,
            reserve_registry=reserve_registry,
        )
        if resolved_exit_main_asset_price_usd > 0:
            exit_main_asset_price_usd = resolved_exit_main_asset_price_usd
    return AaveSentinelStrategyCycleSummary(
        kind=strategy_kind,
        main_asset_symbol=main_asset_symbol,
        leverage=opening_leverage,
        opened_at_timestamp_seconds=opening_checkpoint.timestamp_seconds,
        closed_at_timestamp_seconds=None if is_open else period_end_checkpoint.timestamp_seconds,
        is_open=is_open,
        opening_block_number=opening_checkpoint.block_number,
        closing_block_number=None if is_open else period_end_checkpoint.block_number,
        opening_equity_usd=opening_strategy_equity_usd,
        closing_equity_usd=closing_strategy_equity_usd,
        net_external_capital_usd=0.0,
        net_strategy_capital_usd=net_strategy_capital_usd,
        gross_pnl_usd=gross_pnl_usd,
        silent_mark_to_market_usd=silent_mark_to_market_usd,
        interest_usd=0.0,
        trading_pnl_usd=gross_pnl_usd,
        entry_main_asset_price_usd=entry_main_asset_price_usd,
        exit_main_asset_price_usd=exit_main_asset_price_usd,
    )
