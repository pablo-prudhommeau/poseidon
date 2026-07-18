from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import TOKEN_AMOUNT_DUST_EPSILON
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetSnapshot,
    AaveSentinelPositionCheckpoint,
    AaveSentinelReserveIndexSnapshot,
    AaveSentinelReserveRegistry,
    AaveSentinelReserveScaledBalanceState,
    AaveSentinelStrategy,
    AaveSentinelStrategyCycleSummary,
    AaveSentinelStrategyKind,
)
from src.core.aavesentinel.aave_sentinel_utils import convert_scaled_balance_to_token_amount
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    resolve_reserve_asset_for_underlying,
    resolve_stablecoin_symbols,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_checkpoint_helpers import (
    compute_checkpoint_wallet_boundary_pnl_usd,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_constants import (
    UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_scaled_balance_helpers import (
    build_asset_snapshots_from_scaled_balances,
    find_scaled_balance_state,
    resolve_reserve_index_snapshot,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_wallet_balance_helpers import (
    resolve_asset_price_usd,
)
from src.core.aavesentinel.position.aave_sentinel_position_strategy_helpers import (
    resolve_active_strategies,
)


def compute_strategy_capital_deltas_usd(
        previous_scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        next_scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        previous_reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
        next_reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
        asset_price_usd_by_underlying: dict[str, float],
        reserve_registry: AaveSentinelReserveRegistry,
) -> tuple[float, float]:
    stablecoin_symbols = resolve_stablecoin_symbols(reserve_registry=reserve_registry)
    underlying_addresses: set[str] = {
        scaled_balance.underlying_address
        for scaled_balance in previous_scaled_balances
    }
    underlying_addresses.update(
        scaled_balance.underlying_address
        for scaled_balance in next_scaled_balances
    )

    short_strategy_capital_delta_usd: float = 0.0
    long_strategy_capital_delta_usd: float = 0.0

    for underlying_address in underlying_addresses:
        reserve_asset = resolve_reserve_asset_for_underlying(
            reserve_registry=reserve_registry,
            underlying_address=underlying_address,
        )
        if reserve_asset is None:
            continue

        previous_index_snapshot = resolve_reserve_index_snapshot(
            reserve_index_snapshots=previous_reserve_index_snapshots,
            underlying_address=underlying_address,
        )
        next_index_snapshot = resolve_reserve_index_snapshot(
            reserve_index_snapshots=next_reserve_index_snapshots,
            underlying_address=underlying_address,
        )
        asset_price_usd = resolve_asset_price_usd(
            asset_price_usd_by_underlying=asset_price_usd_by_underlying,
            underlying_address=underlying_address,
        )
        if previous_index_snapshot is None or next_index_snapshot is None or asset_price_usd is None:
            continue
        if previous_index_snapshot.liquidity_index <= 0 or next_index_snapshot.liquidity_index <= 0:
            continue
        if previous_index_snapshot.variable_borrow_index <= 0 or next_index_snapshot.variable_borrow_index <= 0:
            continue

        previous_scaled_balance = find_scaled_balance_state(
            scaled_balances=previous_scaled_balances,
            underlying_address=underlying_address,
        )
        next_scaled_balance = find_scaled_balance_state(
            scaled_balances=next_scaled_balances,
            underlying_address=underlying_address,
        )
        previous_scaled_supply_balance = (
            0.0 if previous_scaled_balance is None else previous_scaled_balance.scaled_supply_balance
        )
        previous_scaled_debt_balance = (
            0.0 if previous_scaled_balance is None else previous_scaled_balance.scaled_debt_balance
        )
        next_scaled_supply_balance = (
            0.0 if next_scaled_balance is None else next_scaled_balance.scaled_supply_balance
        )
        next_scaled_debt_balance = (
            0.0 if next_scaled_balance is None else next_scaled_balance.scaled_debt_balance
        )

        accrued_supply_token_amount = convert_scaled_balance_to_token_amount(
            scaled_balance=previous_scaled_supply_balance,
            reserve_index=next_index_snapshot.liquidity_index,
        )
        next_supply_token_amount = convert_scaled_balance_to_token_amount(
            scaled_balance=next_scaled_supply_balance,
            reserve_index=next_index_snapshot.liquidity_index,
        )
        supply_quantity_change = next_supply_token_amount - accrued_supply_token_amount
        supply_capital_usd = supply_quantity_change * asset_price_usd

        accrued_debt_token_amount = convert_scaled_balance_to_token_amount(
            scaled_balance=previous_scaled_debt_balance,
            reserve_index=next_index_snapshot.variable_borrow_index,
        )
        next_debt_token_amount = convert_scaled_balance_to_token_amount(
            scaled_balance=next_scaled_debt_balance,
            reserve_index=next_index_snapshot.variable_borrow_index,
        )
        debt_quantity_change = next_debt_token_amount - accrued_debt_token_amount
        debt_capital_usd = debt_quantity_change * asset_price_usd

        is_stablecoin = reserve_asset.symbol in stablecoin_symbols
        if is_stablecoin:
            short_strategy_capital_delta_usd += supply_capital_usd
            long_strategy_capital_delta_usd -= debt_capital_usd
        else:
            long_strategy_capital_delta_usd += supply_capital_usd
            short_strategy_capital_delta_usd -= debt_capital_usd

    return short_strategy_capital_delta_usd, long_strategy_capital_delta_usd


def resolve_strategy_equities_usd_from_scaled_balances(
        scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
        asset_price_usd_by_underlying: dict[str, float],
        reserve_registry: AaveSentinelReserveRegistry,
) -> tuple[float, float]:
    asset_snapshots: list[AaveSentinelAssetSnapshot] = build_asset_snapshots_from_scaled_balances(
        scaled_balances=scaled_balances,
        reserve_index_snapshots=reserve_index_snapshots,
        asset_price_usd_by_underlying=asset_price_usd_by_underlying,
        reserve_registry=reserve_registry,
    )
    active_strategies: list[AaveSentinelStrategy] = resolve_active_strategies(
        detected_assets=asset_snapshots,
        reserve_registry=reserve_registry,
    )
    short_strategy_equity_usd: float = 0.0
    long_strategy_equity_usd: float = 0.0
    for active_strategy in active_strategies:
        strategy_equity_usd = active_strategy.collateral_usd - active_strategy.debt_usd
        if active_strategy.kind == AaveSentinelStrategyKind.SHORT:
            short_strategy_equity_usd = strategy_equity_usd
        if active_strategy.kind == AaveSentinelStrategyKind.LONG:
            long_strategy_equity_usd = strategy_equity_usd
    return short_strategy_equity_usd, long_strategy_equity_usd


def resolve_strategy_cycle_overlapping_timestamp_window(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
        strategy_kind: AaveSentinelStrategyKind,
        window_start_timestamp_seconds: int,
        window_end_timestamp_seconds: int,
) -> Optional[AaveSentinelStrategyCycleSummary]:
    for strategy_cycle in strategy_cycles:
        if strategy_cycle.kind != strategy_kind:
            continue
        if strategy_cycle.opened_at_timestamp_seconds > window_end_timestamp_seconds:
            continue
        if (
                strategy_cycle.closed_at_timestamp_seconds is not None
                and strategy_cycle.closed_at_timestamp_seconds < window_start_timestamp_seconds
        ):
            continue
        return strategy_cycle
    return None


def _resolve_strategy_equity_usd_at_interval_end(
        previous_checkpoint: AaveSentinelPositionCheckpoint,
        current_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    strategy_still_active = strategy_kind in current_checkpoint.active_strategy_kinds
    if strategy_kind == AaveSentinelStrategyKind.SHORT:
        if strategy_still_active:
            return current_checkpoint.short_strategy_equity_usd
        before_transfer_strategy_equity_usd = current_checkpoint.before_transfer_short_strategy_equity_usd
        if abs(before_transfer_strategy_equity_usd) >= TOKEN_AMOUNT_DUST_EPSILON:
            return before_transfer_strategy_equity_usd
        return previous_checkpoint.short_strategy_equity_usd
    if strategy_still_active:
        return current_checkpoint.long_strategy_equity_usd
    before_transfer_strategy_equity_usd = current_checkpoint.before_transfer_long_strategy_equity_usd
    if abs(before_transfer_strategy_equity_usd) >= TOKEN_AMOUNT_DUST_EPSILON:
        return before_transfer_strategy_equity_usd
    return previous_checkpoint.long_strategy_equity_usd


def _resolve_opening_strategy_equity_usd(
        position_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    if strategy_kind == AaveSentinelStrategyKind.SHORT:
        return position_checkpoint.short_strategy_equity_usd
    return position_checkpoint.long_strategy_equity_usd


def _compute_strategy_equity_delta_usd(
        previous_checkpoint: AaveSentinelPositionCheckpoint,
        current_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    opening_strategy_equity_usd = _resolve_opening_strategy_equity_usd(
        position_checkpoint=previous_checkpoint,
        strategy_kind=strategy_kind,
    )
    closing_strategy_equity_usd = _resolve_strategy_equity_usd_at_interval_end(
        previous_checkpoint=previous_checkpoint,
        current_checkpoint=current_checkpoint,
        strategy_kind=strategy_kind,
    )
    return closing_strategy_equity_usd - opening_strategy_equity_usd


def _resolve_cumulative_strategy_capital_usd(
        position_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    if strategy_kind == AaveSentinelStrategyKind.SHORT:
        return position_checkpoint.cumulative_short_strategy_capital_usd
    return position_checkpoint.cumulative_long_strategy_capital_usd


def _compute_strategy_capital_delta_usd(
        previous_checkpoint: AaveSentinelPositionCheckpoint,
        current_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    return (
            _resolve_cumulative_strategy_capital_usd(
                position_checkpoint=current_checkpoint,
                strategy_kind=strategy_kind,
            )
            - _resolve_cumulative_strategy_capital_usd(
                position_checkpoint=previous_checkpoint,
                strategy_kind=strategy_kind,
            )
    )


def _is_strategy_covering_aave_position_equity(
        position_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> bool:
    strategy_equity_usd: float = _resolve_opening_strategy_equity_usd(
        position_checkpoint=position_checkpoint,
        strategy_kind=strategy_kind,
    )
    residual_aave_equity_usd: float = abs(
        position_checkpoint.equity_usd - strategy_equity_usd
    )
    return residual_aave_equity_usd < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD


def _compute_position_only_strategy_pnl_usd(
        previous_checkpoint: AaveSentinelPositionCheckpoint,
        current_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    strategy_equity_delta_usd: float = _compute_strategy_equity_delta_usd(
        previous_checkpoint=previous_checkpoint,
        current_checkpoint=current_checkpoint,
        strategy_kind=strategy_kind,
    )
    strategy_capital_delta_usd: float = _compute_strategy_capital_delta_usd(
        previous_checkpoint=previous_checkpoint,
        current_checkpoint=current_checkpoint,
        strategy_kind=strategy_kind,
    )
    return strategy_equity_delta_usd - strategy_capital_delta_usd


def compute_interval_fresh_capital_adjusted_strategy_pnl_usd(
        previous_checkpoint: AaveSentinelPositionCheckpoint,
        current_checkpoint: AaveSentinelPositionCheckpoint,
        strategy_kind: AaveSentinelStrategyKind,
) -> float:
    strategy_equity_delta_usd: float = _compute_strategy_equity_delta_usd(
        previous_checkpoint=previous_checkpoint,
        current_checkpoint=current_checkpoint,
        strategy_kind=strategy_kind,
    )
    previous_active_strategy_kinds: list[AaveSentinelStrategyKind] = list(
        previous_checkpoint.active_strategy_kinds,
    )
    current_active_strategy_kinds: list[AaveSentinelStrategyKind] = list(
        current_checkpoint.active_strategy_kinds,
    )
    wallet_boundary_delta_usd: float = (
            compute_checkpoint_wallet_boundary_pnl_usd(current_checkpoint)
            - compute_checkpoint_wallet_boundary_pnl_usd(previous_checkpoint)
    )
    wallet_equity_delta_usd: float = (
            current_checkpoint.wallet_equity_usd - previous_checkpoint.wallet_equity_usd
    )
    external_capital_delta_usd: float = (
            current_checkpoint.cumulative_external_capital_usd
            - previous_checkpoint.cumulative_external_capital_usd
    )
    is_stable_sole_strategy_interval: bool = (
            previous_active_strategy_kinds == [strategy_kind]
            and current_active_strategy_kinds == [strategy_kind]
    )
    is_sole_strategy_close_interval: bool = (
            previous_active_strategy_kinds == [strategy_kind]
            and strategy_kind not in current_active_strategy_kinds
    )
    if is_stable_sole_strategy_interval:
        strategy_covers_aave_position_equity: bool = (
                _is_strategy_covering_aave_position_equity(
                    position_checkpoint=previous_checkpoint,
                    strategy_kind=strategy_kind,
                )
                and _is_strategy_covering_aave_position_equity(
                    position_checkpoint=current_checkpoint,
                    strategy_kind=strategy_kind,
                )
        )
        if strategy_covers_aave_position_equity:
            return (
                    strategy_equity_delta_usd
                    + wallet_equity_delta_usd
                    - external_capital_delta_usd
            )
        return _compute_position_only_strategy_pnl_usd(
            previous_checkpoint=previous_checkpoint,
            current_checkpoint=current_checkpoint,
            strategy_kind=strategy_kind,
        )
    if is_sole_strategy_close_interval:
        return strategy_equity_delta_usd

    closing_strategy_kinds: list[AaveSentinelStrategyKind] = [
        active_strategy_kind
        for active_strategy_kind in previous_active_strategy_kinds
        if active_strategy_kind not in current_active_strategy_kinds
    ]
    continuing_strategy_kinds: list[AaveSentinelStrategyKind] = [
        active_strategy_kind
        for active_strategy_kind in previous_active_strategy_kinds
        if active_strategy_kind in current_active_strategy_kinds
    ]
    if strategy_kind in closing_strategy_kinds:
        return strategy_equity_delta_usd
    if strategy_kind in continuing_strategy_kinds and closing_strategy_kinds:
        closed_legs_pnl_usd: float = sum(
            _compute_strategy_equity_delta_usd(
                previous_checkpoint=previous_checkpoint,
                current_checkpoint=current_checkpoint,
                strategy_kind=closed_strategy_kind,
            )
            for closed_strategy_kind in closing_strategy_kinds
        )
        remaining_wallet_boundary_delta_usd: float = (
                wallet_boundary_delta_usd - closed_legs_pnl_usd
        )
        if len(continuing_strategy_kinds) == 1:
            return remaining_wallet_boundary_delta_usd
        return strategy_equity_delta_usd
    return strategy_equity_delta_usd


def apply_fresh_capital_adjusted_pnl_to_strategy_cycles(
        position_checkpoints: list[AaveSentinelPositionCheckpoint],
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
) -> None:
    if not position_checkpoints or not strategy_cycles:
        return

    for strategy_cycle in strategy_cycles:
        strategy_cycle.gross_pnl_usd = 0.0
        strategy_cycle.trading_pnl_usd = 0.0
        strategy_cycle.net_external_capital_usd = 0.0

    for checkpoint_index in range(1, len(position_checkpoints)):
        previous_checkpoint: AaveSentinelPositionCheckpoint = position_checkpoints[
            checkpoint_index - 1
        ]
        current_checkpoint: AaveSentinelPositionCheckpoint = position_checkpoints[
            checkpoint_index
        ]
        active_strategy_kinds: list[AaveSentinelStrategyKind] = list(
            previous_checkpoint.active_strategy_kinds,
        )
        for strategy_kind in active_strategy_kinds:
            strategy_cycle = resolve_strategy_cycle_overlapping_timestamp_window(
                strategy_cycles=strategy_cycles,
                strategy_kind=strategy_kind,
                window_start_timestamp_seconds=previous_checkpoint.timestamp_seconds,
                window_end_timestamp_seconds=current_checkpoint.timestamp_seconds,
            )
            if strategy_cycle is None:
                continue
            interval_pnl_usd: float = compute_interval_fresh_capital_adjusted_strategy_pnl_usd(
                previous_checkpoint=previous_checkpoint,
                current_checkpoint=current_checkpoint,
                strategy_kind=strategy_kind,
            )
            strategy_cycle.gross_pnl_usd += interval_pnl_usd
            strategy_cycle.trading_pnl_usd = strategy_cycle.gross_pnl_usd
            if previous_checkpoint.active_strategy_kinds == [strategy_kind]:
                strategy_cycle.net_external_capital_usd += (
                        current_checkpoint.cumulative_external_capital_usd
                        - previous_checkpoint.cumulative_external_capital_usd
                )
