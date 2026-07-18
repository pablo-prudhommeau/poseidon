from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetSnapshot,
    AaveSentinelCapitalFlowDirection,
    AaveSentinelClassifiedCapitalFlow,
    AaveSentinelPerformanceSummary,
    AaveSentinelPositionCheckpoint,
    AaveSentinelReserveIndexSnapshot,
    AaveSentinelReserveRegistry,
    AaveSentinelReserveScaledBalanceState,
    AaveSentinelStrategy,
    AaveSentinelStrategyKind,
    AaveSentinelWalletTokenBalance,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_scaled_balance_helpers import (
    build_asset_snapshots_from_scaled_balances,
    clone_reserve_index_snapshots,
    clone_scaled_balances,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_wallet_balance_helpers import (
    build_asset_prices_usd,
    clone_wallet_token_balances,
)
from src.core.aavesentinel.position.aave_sentinel_position_strategy_helpers import (
    resolve_active_strategies,
)
from src.core.utils.date_utils import get_current_local_datetime


def create_empty_performance_summary() -> AaveSentinelPerformanceSummary:
    return AaveSentinelPerformanceSummary(
        is_available=False,
        refreshed_at=get_current_local_datetime(),
    )


def compute_checkpoint_wallet_boundary_pnl_usd(
        position_checkpoint: AaveSentinelPositionCheckpoint,
) -> float:
    return (
            position_checkpoint.equity_usd
            + position_checkpoint.wallet_equity_usd
            - position_checkpoint.cumulative_external_capital_usd
    )


def build_position_checkpoint(
        block_number: int,
        timestamp_seconds: int,
        scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
        asset_price_usd_by_underlying: dict[str, float],
        reserve_registry: AaveSentinelReserveRegistry,
        cumulative_supply_interest_usd: float,
        cumulative_borrow_interest_usd: float,
        cumulative_short_strategy_capital_usd: float,
        cumulative_long_strategy_capital_usd: float,
        before_transfer_short_strategy_equity_usd: float = 0.0,
        before_transfer_long_strategy_equity_usd: float = 0.0,
        wallet_equity_usd: float = 0.0,
        cumulative_external_capital_usd: float = 0.0,
        wallet_token_balances: Optional[list[AaveSentinelWalletTokenBalance]] = None,
) -> AaveSentinelPositionCheckpoint:
    asset_snapshots: list[AaveSentinelAssetSnapshot] = build_asset_snapshots_from_scaled_balances(
        scaled_balances=scaled_balances,
        reserve_index_snapshots=reserve_index_snapshots,
        asset_price_usd_by_underlying=asset_price_usd_by_underlying,
        reserve_registry=reserve_registry,
    )
    total_supply_value_usd: float = sum(asset.supply_value_usd for asset in asset_snapshots)
    total_debt_value_usd: float = sum(asset.debt_value_usd for asset in asset_snapshots)
    active_strategies: list[AaveSentinelStrategy] = resolve_active_strategies(
        detected_assets=asset_snapshots,
        reserve_registry=reserve_registry,
    )
    short_main_asset_symbol: Optional[str] = None
    long_main_asset_symbol: Optional[str] = None
    short_leverage: float = 0.0
    long_leverage: float = 0.0
    short_strategy_equity_usd: float = 0.0
    long_strategy_equity_usd: float = 0.0
    active_strategy_kinds: list[AaveSentinelStrategyKind] = []
    for active_strategy in active_strategies:
        active_strategy_kinds.append(active_strategy.kind)
        strategy_equity_usd = active_strategy.collateral_usd - active_strategy.debt_usd
        if active_strategy.kind == AaveSentinelStrategyKind.SHORT:
            short_main_asset_symbol = active_strategy.main_asset_symbol
            short_leverage = active_strategy.leverage
            short_strategy_equity_usd = strategy_equity_usd
        if active_strategy.kind == AaveSentinelStrategyKind.LONG:
            long_main_asset_symbol = active_strategy.main_asset_symbol
            long_leverage = active_strategy.leverage
            long_strategy_equity_usd = strategy_equity_usd
    return AaveSentinelPositionCheckpoint(
        block_number=block_number,
        timestamp_seconds=timestamp_seconds,
        active_strategy_kinds=active_strategy_kinds,
        short_main_asset_symbol=short_main_asset_symbol,
        long_main_asset_symbol=long_main_asset_symbol,
        short_leverage=short_leverage,
        long_leverage=long_leverage,
        short_strategy_equity_usd=short_strategy_equity_usd,
        long_strategy_equity_usd=long_strategy_equity_usd,
        before_transfer_short_strategy_equity_usd=before_transfer_short_strategy_equity_usd,
        before_transfer_long_strategy_equity_usd=before_transfer_long_strategy_equity_usd,
        cumulative_short_strategy_capital_usd=cumulative_short_strategy_capital_usd,
        cumulative_long_strategy_capital_usd=cumulative_long_strategy_capital_usd,
        total_supply_value_usd=total_supply_value_usd,
        total_debt_value_usd=total_debt_value_usd,
        equity_usd=total_supply_value_usd - total_debt_value_usd,
        wallet_equity_usd=wallet_equity_usd,
        cumulative_external_capital_usd=cumulative_external_capital_usd,
        cumulative_supply_interest_usd=cumulative_supply_interest_usd,
        cumulative_borrow_interest_usd=cumulative_borrow_interest_usd,
        cumulative_net_interest_usd=cumulative_supply_interest_usd - cumulative_borrow_interest_usd,
        asset_prices_usd=build_asset_prices_usd(
            asset_price_usd_by_underlying=asset_price_usd_by_underlying,
        ),
        scaled_balances=clone_scaled_balances(scaled_balances),
        reserve_index_snapshots=clone_reserve_index_snapshots(reserve_index_snapshots),
        wallet_token_balances=clone_wallet_token_balances(
            [] if wallet_token_balances is None else wallet_token_balances,
        ),
    )


def sum_net_external_capital_usd_in_timestamp_window(
        classified_flows: list[AaveSentinelClassifiedCapitalFlow],
        window_start_timestamp_seconds: int,
        window_end_timestamp_seconds: int,
) -> float:
    net_external_capital_usd: float = 0.0
    for classified_flow in classified_flows:
        if classified_flow.timestamp_seconds < window_start_timestamp_seconds:
            continue
        if classified_flow.timestamp_seconds > window_end_timestamp_seconds:
            continue
        if classified_flow.direction == AaveSentinelCapitalFlowDirection.INFLOW:
            net_external_capital_usd += classified_flow.amount_usd
            continue
        net_external_capital_usd -= classified_flow.amount_usd
    return net_external_capital_usd
