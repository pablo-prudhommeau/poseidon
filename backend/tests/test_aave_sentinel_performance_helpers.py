from __future__ import annotations

import pytest

from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    filter_oracle_priceable_capital_flow_events,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_forensic_helpers import (
    allocate_signed_component_into_residual,
    build_unallocated_wealth_movements_from_checkpoints,
    coalesce_adjacent_interest_accrual_movements,
    compute_holdings_oracle_price_delta_usd,
    compute_ledger_entry_conversion_pnl_usd,
    ledger_entry_is_token_conversion_candidate,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_scaled_balance_helpers import (
    accrue_interest_between_indices,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_checkpoint_helpers import (
    compute_checkpoint_wallet_boundary_pnl_usd,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_cycle_pnl_helpers import (
    compute_strategy_capital_deltas_usd,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_strategy_cycle_helpers import (
    aggregate_performance_summary,
    build_strategy_cycles_from_checkpoints,
)
from src.core.aavesentinel.position.aave_sentinel_position_strategy_helpers import (
    resolve_active_strategies,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_wallet_balance_helpers import (
    apply_reserve_underlying_wallet_transfers,
    build_asset_prices_usd,
    compute_wallet_equity_usd,
    resolve_asset_price_usd_for_symbol,
)
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetPriceUsd,
    AaveSentinelAssetSnapshot,
    AaveSentinelCapitalFlowDirection,
    AaveSentinelClassifiedCapitalFlow,
    AaveSentinelErc20TransferFlow,
    AaveSentinelErc20TransferFlowRecord,
    AaveSentinelIntervalForensicBreakdown,
    AaveSentinelPositionCheckpoint,
    AaveSentinelRawCapitalFlowEvent,
    AaveSentinelReserveAsset,
    AaveSentinelReserveIndexSnapshot,
    AaveSentinelReserveInterestBreakdown,
    AaveSentinelReserveRegistry,
    AaveSentinelReserveScaledBalanceState,
    AaveSentinelNonTradingMovementSource,
    AaveSentinelStrategyKind,
    AaveSentinelUnallocatedWealthMovement,
    AaveSentinelUniversalLedgerEntry,
    AaveSentinelWalletTokenBalance,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_cycle_gross_pnl_usd,
    compute_index_accrued_interest_token_amount,
    compute_long_liquidation_price_usd,
    compute_short_liquidation_price_usd,
    compute_strategy_leverage,
    compute_trading_pnl_usd,
    convert_token_amount_to_scaled_balance,
    decode_aave_reserve_liquidation_threshold,
)
from src.integrations.aave.aave_abis import RAY_UNITS


USDC_CONTRACT_ADDRESS = "0xusdc"
BTC_CONTRACT_ADDRESS = "0xbtc"
EURC_CONTRACT_ADDRESS = "0xeurc"
UNKNOWN_ERC20_CONTRACT_ADDRESS = "0x5b9192"


def build_test_reserve_registry() -> AaveSentinelReserveRegistry:
    return AaveSentinelReserveRegistry(
        reserve_assets=(
            AaveSentinelReserveAsset(
                underlying_address=USDC_CONTRACT_ADDRESS,
                symbol="USDC",
                decimal_count=6,
                requires_euro_conversion=False,
                a_token_address="0ausdc",
                stable_debt_token_address="0susdc",
                variable_debt_token_address="0vusdc",
            ),
            AaveSentinelReserveAsset(
                underlying_address=BTC_CONTRACT_ADDRESS,
                symbol="BTC.b",
                decimal_count=8,
                requires_euro_conversion=False,
                a_token_address="0abtc",
                stable_debt_token_address="0sbtc",
                variable_debt_token_address="0vbtc",
            ),
            AaveSentinelReserveAsset(
                underlying_address=EURC_CONTRACT_ADDRESS,
                symbol="EURC",
                decimal_count=6,
                requires_euro_conversion=True,
                a_token_address="0aeurc",
                stable_debt_token_address="0seurc",
                variable_debt_token_address="0veurc",
            ),
        ),
    )


def test_filter_oracle_priceable_capital_flow_events_excludes_unknown_erc20() -> None:
    priceable_flow_events, excluded_flow_events = filter_oracle_priceable_capital_flow_events(
        raw_flow_events=[
            AaveSentinelRawCapitalFlowEvent(
                transaction_hash="0x1",
                block_number=1,
                timestamp_seconds=1,
                direction=AaveSentinelCapitalFlowDirection.INFLOW,
                asset_symbol="USDC",
                contract_address=USDC_CONTRACT_ADDRESS,
                token_amount=100.0,
                requires_euro_conversion=False,
            ),
            AaveSentinelRawCapitalFlowEvent(
                transaction_hash="0x2",
                block_number=2,
                timestamp_seconds=2,
                direction=AaveSentinelCapitalFlowDirection.INFLOW,
                asset_symbol="UNKNOWN",
                contract_address=UNKNOWN_ERC20_CONTRACT_ADDRESS,
                token_amount=1.0,
                requires_euro_conversion=False,
            ),
        ],
        reserve_registry=build_test_reserve_registry(),
    )
    assert len(priceable_flow_events) == 1
    assert priceable_flow_events[0].contract_address == USDC_CONTRACT_ADDRESS
    assert len(excluded_flow_events) == 1


def test_short_liquidation_price_is_invariant_to_spot_price() -> None:
    liquidation_price_at_low_spot = compute_short_liquidation_price_usd(
        stable_collateral_usd=10_000.0,
        weighted_stable_collateral_liquidation_threshold=0.80,
        volatile_debt_token_amount=0.10,
    )
    liquidation_price_at_high_spot = compute_short_liquidation_price_usd(
        stable_collateral_usd=10_000.0,
        weighted_stable_collateral_liquidation_threshold=0.80,
        volatile_debt_token_amount=0.10,
    )
    assert liquidation_price_at_low_spot == pytest.approx(80_000.0)
    assert liquidation_price_at_high_spot == pytest.approx(liquidation_price_at_low_spot)


def test_long_liquidation_price_and_strategy_leverage() -> None:
    liquidation_price_usd = compute_long_liquidation_price_usd(
        stable_debt_usd=8_000.0,
        volatile_collateral_token_amount=0.20,
        volatile_collateral_liquidation_threshold=0.70,
    )
    assert liquidation_price_usd == pytest.approx(8_000.0 / (0.20 * 0.70))
    assert compute_strategy_leverage(collateral_usd=10_000.0, debt_usd=5_000.0) == pytest.approx(2.0)


def test_decode_aave_reserve_liquidation_threshold() -> None:
    configuration_bitmap = 8000 << 16
    assert decode_aave_reserve_liquidation_threshold(configuration_bitmap) == pytest.approx(0.80)


def test_resolve_active_strategies_returns_short_only() -> None:
    strategies = resolve_active_strategies(
        detected_assets=[
            AaveSentinelAssetSnapshot(
                symbol="USDC",
                underlying_address=USDC_CONTRACT_ADDRESS,
                supply_amount=10_000.0,
                debt_amount=0.0,
                wallet_amount=0.0,
                supply_value_usd=10_000.0,
                debt_value_usd=0.0,
                wallet_value_usd=0.0,
                supply_annual_percentage_yield=0.0,
                borrow_annual_percentage_yield=0.0,
                liquidation_threshold=0.80,
            ),
            AaveSentinelAssetSnapshot(
                symbol="BTC.b",
                underlying_address=BTC_CONTRACT_ADDRESS,
                supply_amount=0.0,
                debt_amount=0.10,
                wallet_amount=0.0,
                supply_value_usd=0.0,
                debt_value_usd=7_000.0,
                wallet_value_usd=0.0,
                supply_annual_percentage_yield=0.0,
                borrow_annual_percentage_yield=0.0,
                liquidation_threshold=0.70,
            ),
        ],
        reserve_registry=build_test_reserve_registry(),
    )
    assert len(strategies) == 1
    assert strategies[0].kind == AaveSentinelStrategyKind.SHORT
    assert strategies[0].main_asset_symbol == "BTC.b"
    assert strategies[0].liquidation_price_usd == pytest.approx(80_000.0)
    assert strategies[0].leverage == pytest.approx(10_000.0 / 3_000.0)


def test_resolve_active_strategies_returns_unlevered_long_at_one_x() -> None:
    strategies = resolve_active_strategies(
        detected_assets=[
            AaveSentinelAssetSnapshot(
                symbol="USDC",
                underlying_address=USDC_CONTRACT_ADDRESS,
                supply_amount=5_000.0,
                debt_amount=0.0,
                wallet_amount=0.0,
                supply_value_usd=5_000.0,
                debt_value_usd=0.0,
                wallet_value_usd=0.0,
                supply_annual_percentage_yield=0.0,
                borrow_annual_percentage_yield=0.0,
                liquidation_threshold=0.80,
            ),
            AaveSentinelAssetSnapshot(
                symbol="BTC.b",
                underlying_address=BTC_CONTRACT_ADDRESS,
                supply_amount=0.05,
                debt_amount=0.0,
                wallet_amount=0.0,
                supply_value_usd=4_000.0,
                debt_value_usd=0.0,
                wallet_value_usd=0.0,
                supply_annual_percentage_yield=0.0,
                borrow_annual_percentage_yield=0.0,
                liquidation_threshold=0.70,
            ),
        ],
        reserve_registry=build_test_reserve_registry(),
    )
    assert len(strategies) == 1
    assert strategies[0].kind == AaveSentinelStrategyKind.LONG
    assert strategies[0].main_asset_symbol == "BTC.b"
    assert strategies[0].leverage == pytest.approx(1.0)
    assert strategies[0].debt_usd == pytest.approx(0.0)
    assert strategies[0].liquidation_price_usd == pytest.approx(0.0)


def test_resolve_active_strategies_returns_short_and_long_concurrently() -> None:
    strategies = resolve_active_strategies(
        detected_assets=[
            AaveSentinelAssetSnapshot(
                symbol="USDC",
                underlying_address=USDC_CONTRACT_ADDRESS,
                supply_amount=5_000.0,
                debt_amount=2_000.0,
                wallet_amount=0.0,
                supply_value_usd=5_000.0,
                debt_value_usd=2_000.0,
                wallet_value_usd=0.0,
                supply_annual_percentage_yield=0.0,
                borrow_annual_percentage_yield=0.0,
                liquidation_threshold=0.80,
            ),
            AaveSentinelAssetSnapshot(
                symbol="BTC.b",
                underlying_address=BTC_CONTRACT_ADDRESS,
                supply_amount=0.05,
                debt_amount=0.04,
                wallet_amount=0.0,
                supply_value_usd=4_000.0,
                debt_value_usd=3_200.0,
                wallet_value_usd=0.0,
                supply_annual_percentage_yield=0.0,
                borrow_annual_percentage_yield=0.0,
                liquidation_threshold=0.70,
            ),
        ],
        reserve_registry=build_test_reserve_registry(),
    )
    strategy_kinds = {strategy.kind for strategy in strategies}
    assert strategy_kinds == {AaveSentinelStrategyKind.SHORT, AaveSentinelStrategyKind.LONG}


def test_index_accrual_and_trading_pnl_formula() -> None:
    ray_units = float(RAY_UNITS)
    previous_index = ray_units
    next_index = ray_units * 1.01
    scaled_balance = convert_token_amount_to_scaled_balance(
        token_amount=1000.0,
        reserve_index=previous_index,
    )
    interest_token_amount = compute_index_accrued_interest_token_amount(
        scaled_balance=scaled_balance,
        previous_reserve_index=previous_index,
        next_reserve_index=next_index,
    )
    assert interest_token_amount == pytest.approx(10.0)
    gross_pnl_usd = compute_cycle_gross_pnl_usd(
        opening_equity_usd=1000.0,
        closing_equity_usd=1300.0,
        net_external_capital_usd=50.0,
    )
    assert compute_trading_pnl_usd(gross_pnl_usd=gross_pnl_usd, interest_usd=30.0) == pytest.approx(220.0)


def test_accrue_interest_between_indices_values_supply_and_borrow() -> None:
    ray_units = float(RAY_UNITS)
    previous_scaled_balances = [
        AaveSentinelReserveScaledBalanceState(
            underlying_address=USDC_CONTRACT_ADDRESS,
            scaled_supply_balance=convert_token_amount_to_scaled_balance(1000.0, ray_units),
            scaled_debt_balance=convert_token_amount_to_scaled_balance(200.0, ray_units),
        ),
    ]
    previous_indices = [
        AaveSentinelReserveIndexSnapshot(
            underlying_address=USDC_CONTRACT_ADDRESS,
            liquidity_index=ray_units,
            variable_borrow_index=ray_units,
        ),
    ]
    next_indices = [
        AaveSentinelReserveIndexSnapshot(
            underlying_address=USDC_CONTRACT_ADDRESS,
            liquidity_index=ray_units * 1.02,
            variable_borrow_index=ray_units * 1.05,
        ),
    ]

    supply_interest_usd, borrow_interest_usd, interest_breakdowns = accrue_interest_between_indices(
        previous_scaled_balances=previous_scaled_balances,
        previous_reserve_index_snapshots=previous_indices,
        next_reserve_index_snapshots=next_indices,
        asset_price_usd_by_underlying={USDC_CONTRACT_ADDRESS: 1.0},
        reserve_registry=build_test_reserve_registry(),
    )

    assert supply_interest_usd == pytest.approx(20.0)
    assert borrow_interest_usd == pytest.approx(10.0)
    assert interest_breakdowns[0].net_interest_usd == pytest.approx(10.0)


def test_compute_strategy_capital_deltas_tracks_internal_aave_quantity_changes() -> None:
    ray_units = float(RAY_UNITS)
    previous_scaled_balances = [
        AaveSentinelReserveScaledBalanceState(
            underlying_address=USDC_CONTRACT_ADDRESS,
            scaled_supply_balance=convert_token_amount_to_scaled_balance(1_000.0, ray_units),
            scaled_debt_balance=0.0,
        ),
        AaveSentinelReserveScaledBalanceState(
            underlying_address=BTC_CONTRACT_ADDRESS,
            scaled_supply_balance=0.0,
            scaled_debt_balance=convert_token_amount_to_scaled_balance(0.10, ray_units),
        ),
    ]
    next_scaled_balances = [
        AaveSentinelReserveScaledBalanceState(
            underlying_address=USDC_CONTRACT_ADDRESS,
            scaled_supply_balance=convert_token_amount_to_scaled_balance(1_500.0, ray_units),
            scaled_debt_balance=0.0,
        ),
        AaveSentinelReserveScaledBalanceState(
            underlying_address=BTC_CONTRACT_ADDRESS,
            scaled_supply_balance=0.0,
            scaled_debt_balance=convert_token_amount_to_scaled_balance(0.12, ray_units),
        ),
    ]
    reserve_index_snapshots = [
        AaveSentinelReserveIndexSnapshot(
            underlying_address=USDC_CONTRACT_ADDRESS,
            liquidity_index=ray_units,
            variable_borrow_index=ray_units,
        ),
        AaveSentinelReserveIndexSnapshot(
            underlying_address=BTC_CONTRACT_ADDRESS,
            liquidity_index=ray_units,
            variable_borrow_index=ray_units,
        ),
    ]

    short_strategy_capital_delta_usd, long_strategy_capital_delta_usd = (
        compute_strategy_capital_deltas_usd(
            previous_scaled_balances=previous_scaled_balances,
            next_scaled_balances=next_scaled_balances,
            previous_reserve_index_snapshots=reserve_index_snapshots,
            next_reserve_index_snapshots=reserve_index_snapshots,
            asset_price_usd_by_underlying={
                USDC_CONTRACT_ADDRESS: 1.0,
                BTC_CONTRACT_ADDRESS: 100_000.0,
            },
            reserve_registry=build_test_reserve_registry(),
        )
    )

    assert short_strategy_capital_delta_usd == pytest.approx(500.0 - 2_000.0)
    assert long_strategy_capital_delta_usd == pytest.approx(0.0)


def test_wallet_token_balances_track_reserve_underlying_transfers() -> None:
    wallet_token_balances: list[AaveSentinelWalletTokenBalance] = []
    apply_reserve_underlying_wallet_transfers(
        ledger_entry=AaveSentinelUniversalLedgerEntry(
            transaction_hash="0xwallet",
            block_number=1,
            timestamp_seconds=100,
            erc20_transfer_flows=[
                AaveSentinelErc20TransferFlowRecord(
                    contract_address=USDC_CONTRACT_ADDRESS,
                    transfer_flow=AaveSentinelErc20TransferFlow(
                        incoming_amount=250.0,
                        outgoing_amount=0.0,
                    ),
                ),
            ],
        ),
        reserve_registry=build_test_reserve_registry(),
        wallet_token_balances=wallet_token_balances,
    )
    wallet_equity_usd = compute_wallet_equity_usd(
        wallet_token_balances=wallet_token_balances,
        asset_prices_usd=build_asset_prices_usd(
            asset_price_usd_by_underlying={USDC_CONTRACT_ADDRESS: 1.0},
        ),
        reserve_registry=build_test_reserve_registry(),
    )
    assert len(wallet_token_balances) == 1
    assert wallet_token_balances[0].token_amount == pytest.approx(250.0)
    assert wallet_equity_usd == pytest.approx(250.0)


def test_strategy_cycle_pnl_deducts_fresh_wallet_outflow_during_strategy() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1000.0,
            wallet_equity_usd=500.0,
            cumulative_external_capital_usd=1500.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1949.0,
            cumulative_short_strategy_capital_usd=900.0,
            equity_usd=1949.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[],
            before_transfer_short_strategy_equity_usd=1949.0,
            cumulative_short_strategy_capital_usd=900.0,
            equity_usd=0.0,
            wallet_equity_usd=1949.0,
            cumulative_external_capital_usd=1000.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    short_cycle = strategy_cycles[0]
    assert short_cycle.gross_pnl_usd == pytest.approx(949.0)
    assert short_cycle.closed_at_timestamp_seconds == 300


def test_strategy_cycle_pnl_includes_wallet_boundary_while_strategy_stays_open() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1000.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1250.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1250.0,
            wallet_equity_usd=50.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[],
            before_transfer_short_strategy_equity_usd=1250.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=0.0,
            wallet_equity_usd=1300.0,
            cumulative_external_capital_usd=1000.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    short_cycle = strategy_cycles[0]
    assert short_cycle.gross_pnl_usd == pytest.approx(300.0)


def test_long_cycle_pnl_is_position_only_and_ignores_portfolio_noise() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=2000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=2000.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT, AaveSentinelStrategyKind.LONG],
            short_main_asset_symbol="BTC.b",
            long_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=200.0,
            long_strategy_equity_usd=300.0,
            cumulative_short_strategy_capital_usd=1000.0,
            cumulative_long_strategy_capital_usd=500.0,
            equity_usd=500.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1500.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=400.0,
            before_transfer_long_strategy_equity_usd=300.0,
            cumulative_short_strategy_capital_usd=1000.0,
            cumulative_long_strategy_capital_usd=0.0,
            equity_usd=400.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    short_cycle = next(
        strategy_cycle
        for strategy_cycle in strategy_cycles
        if strategy_cycle.kind == AaveSentinelStrategyKind.SHORT
    )
    long_cycle = next(
        strategy_cycle
        for strategy_cycle in strategy_cycles
        if strategy_cycle.kind == AaveSentinelStrategyKind.LONG
    )
    assert long_cycle.gross_pnl_usd == pytest.approx(0.0)
    assert short_cycle.is_open is True


def test_parallel_short_and_long_use_each_position_equity() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=1000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1000.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT, AaveSentinelStrategyKind.LONG],
            short_main_asset_symbol="BTC.b",
            long_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=1000.0,
            long_strategy_equity_usd=500.0,
            cumulative_short_strategy_capital_usd=1000.0,
            cumulative_long_strategy_capital_usd=500.0,
            equity_usd=1500.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1500.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=1100.0,
            before_transfer_long_strategy_equity_usd=500.0,
            cumulative_short_strategy_capital_usd=1000.0,
            cumulative_long_strategy_capital_usd=0.0,
            equity_usd=1100.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    short_cycle = next(
        strategy_cycle
        for strategy_cycle in strategy_cycles
        if strategy_cycle.kind == AaveSentinelStrategyKind.SHORT
    )
    long_cycle = next(
        strategy_cycle
        for strategy_cycle in strategy_cycles
        if strategy_cycle.kind == AaveSentinelStrategyKind.LONG
    )
    assert long_cycle.gross_pnl_usd == pytest.approx(0.0)
    assert short_cycle.gross_pnl_usd == pytest.approx(100.0)
    assert short_cycle.is_open is True


def test_aggregate_performance_summary_tracks_legs_separately_from_global() -> None:
    strategy_cycles = build_strategy_cycles_from_checkpoints(
        position_checkpoints=[
            AaveSentinelPositionCheckpoint(
                block_number=1,
                timestamp_seconds=100,
                active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
                long_main_asset_symbol="BTC.b",
                long_strategy_equity_usd=1000.0,
                cumulative_long_strategy_capital_usd=1000.0,
                equity_usd=1000.0,
                wallet_equity_usd=0.0,
                cumulative_external_capital_usd=1000.0,
            ),
            AaveSentinelPositionCheckpoint(
                block_number=2,
                timestamp_seconds=200,
                active_strategy_kinds=[],
                before_transfer_long_strategy_equity_usd=1300.0,
                cumulative_long_strategy_capital_usd=1000.0,
                equity_usd=0.0,
                wallet_equity_usd=1300.0,
                cumulative_external_capital_usd=1000.0,
            ),
            AaveSentinelPositionCheckpoint(
                block_number=3,
                timestamp_seconds=300,
                active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
                short_main_asset_symbol="BTC.b",
                short_strategy_equity_usd=1300.0,
                cumulative_short_strategy_capital_usd=1300.0,
                equity_usd=1300.0,
                wallet_equity_usd=0.0,
                cumulative_external_capital_usd=1000.0,
            ),
            AaveSentinelPositionCheckpoint(
                block_number=4,
                timestamp_seconds=400,
                active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
                short_main_asset_symbol="BTC.b",
                short_strategy_equity_usd=1400.0,
                cumulative_short_strategy_capital_usd=1300.0,
                equity_usd=1400.0,
                wallet_equity_usd=0.0,
                cumulative_external_capital_usd=1000.0,
            ),
        ],
    )
    performance_summary = aggregate_performance_summary(
        strategy_cycles=strategy_cycles,
        interest_breakdowns=[
            AaveSentinelReserveInterestBreakdown(
                asset_symbol="USDC",
                supply_interest_usd=50.0,
                borrow_interest_usd=10.0,
                net_interest_usd=40.0,
            ),
        ],
        total_equity_usd=1400.0,
        net_capital_deployed_usd=1000.0,
    )

    assert performance_summary.global_pnl_usd == pytest.approx(400.0)
    assert performance_summary.strategy_legs_pnl_usd == pytest.approx(400.0)
    assert performance_summary.pnl_reconciliation_gap_usd == pytest.approx(0.0)
    assert performance_summary.cumulative_net_interest_usd == pytest.approx(40.0)
    assert performance_summary.total_trading_pnl_usd == pytest.approx(360.0)
    long_cycle = next(
        strategy_cycle
        for strategy_cycle in performance_summary.strategy_cycles
        if strategy_cycle.kind == AaveSentinelStrategyKind.LONG
    )
    short_cycle = next(
        strategy_cycle
        for strategy_cycle in performance_summary.strategy_cycles
        if strategy_cycle.kind == AaveSentinelStrategyKind.SHORT
    )
    assert long_cycle.gross_pnl_usd == pytest.approx(300.0)
    assert short_cycle.gross_pnl_usd == pytest.approx(100.0)
    assert short_cycle.is_open is True


def test_strategy_cycle_captures_entry_and_exit_main_asset_prices() -> None:
    reserve_registry = build_test_reserve_registry()
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=1000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1000.0,
            cumulative_external_capital_usd=1000.0,
            asset_prices_usd=[
                AaveSentinelAssetPriceUsd(
                    underlying_address=BTC_CONTRACT_ADDRESS,
                    price_usd=63000.0,
                ),
            ],
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[],
            before_transfer_short_strategy_equity_usd=1100.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=0.0,
            wallet_equity_usd=1100.0,
            cumulative_external_capital_usd=1000.0,
            asset_prices_usd=[
                AaveSentinelAssetPriceUsd(
                    underlying_address=BTC_CONTRACT_ADDRESS,
                    price_usd=64800.0,
                ),
            ],
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(
        position_checkpoints=checkpoints,
        reserve_registry=reserve_registry,
    )
    short_cycle = next(
        strategy_cycle
        for strategy_cycle in strategy_cycles
        if strategy_cycle.kind == AaveSentinelStrategyKind.SHORT
    )
    assert short_cycle.entry_main_asset_price_usd == pytest.approx(63000.0)
    assert short_cycle.exit_main_asset_price_usd == pytest.approx(64800.0)
    assert resolve_asset_price_usd_for_symbol(
        asset_prices_usd=checkpoints[0].asset_prices_usd,
        asset_symbol="BTC.b",
        reserve_registry=reserve_registry,
    ) == pytest.approx(63000.0)


def test_flat_wavax_long_ignores_matched_wallet_external_outflow() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="WAVAX",
            long_leverage=1.0,
            long_strategy_equity_usd=3.5,
            cumulative_long_strategy_capital_usd=3.5,
            equity_usd=1003.5,
            wallet_equity_usd=500.0,
            cumulative_external_capital_usd=1500.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="WAVAX",
            long_leverage=1.0,
            long_strategy_equity_usd=3.5,
            cumulative_long_strategy_capital_usd=3.5,
            equity_usd=1003.5,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[],
            before_transfer_long_strategy_equity_usd=3.5,
            cumulative_long_strategy_capital_usd=3.5,
            equity_usd=1000.0,
            wallet_equity_usd=3.5,
            cumulative_external_capital_usd=1000.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    long_cycle = strategy_cycles[0]
    assert long_cycle.kind == AaveSentinelStrategyKind.LONG
    assert long_cycle.main_asset_symbol == "WAVAX"
    assert long_cycle.gross_pnl_usd == pytest.approx(0.0)


def test_unallocated_wealth_movements_peel_explained_sources_only() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[],
            equity_usd=5894.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=5900.0,
            cumulative_net_interest_usd=2.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[],
            equity_usd=6800.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=6900.0,
            cumulative_net_interest_usd=12.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=2000.0,
            cumulative_short_strategy_capital_usd=2000.0,
            equity_usd=2000.0,
            wallet_equity_usd=4800.0,
            cumulative_external_capital_usd=6900.0,
            cumulative_net_interest_usd=12.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=4,
            timestamp_seconds=400,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=2100.0,
            cumulative_short_strategy_capital_usd=2000.0,
            equity_usd=2100.0,
            wallet_equity_usd=4800.0,
            cumulative_external_capital_usd=6900.0,
            cumulative_net_interest_usd=12.0,
        ),
    ]
    unallocated_wealth_movements = build_unallocated_wealth_movements_from_checkpoints(
        position_checkpoints=checkpoints,
        interval_forensic_breakdowns=[
            AaveSentinelIntervalForensicBreakdown(
                window_start_timestamp_seconds=0,
                window_end_timestamp_seconds=100,
                gas_fee_usd=2.0,
                conversion_pnl_usd=-3.0,
            ),
            AaveSentinelIntervalForensicBreakdown(
                window_start_timestamp_seconds=100,
                window_end_timestamp_seconds=200,
                gas_fee_usd=4.0,
                conversion_pnl_usd=-50.0,
            ),
        ],
    )
    interest_accrual_pnl_usd = sum(
        wealth_movement.pnl_usd
        for wealth_movement in unallocated_wealth_movements
        if wealth_movement.source == AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL
    )
    gas_fees_pnl_usd = sum(
        wealth_movement.pnl_usd
        for wealth_movement in unallocated_wealth_movements
        if wealth_movement.source == AaveSentinelNonTradingMovementSource.GAS_FEES
    )
    slippage_pnl_usd = sum(
        wealth_movement.pnl_usd
        for wealth_movement in unallocated_wealth_movements
        if wealth_movement.source == AaveSentinelNonTradingMovementSource.SLIPPAGE
    )
    oracle_price_gap_pnl_usd = sum(
        wealth_movement.pnl_usd
        for wealth_movement in unallocated_wealth_movements
        if wealth_movement.source == AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP
    )
    assert interest_accrual_pnl_usd == pytest.approx(12.0)
    assert gas_fees_pnl_usd == pytest.approx(-6.0)
    assert slippage_pnl_usd == pytest.approx(-53.0)
    assert oracle_price_gap_pnl_usd == pytest.approx(0.0)
    assert sum(wealth_movement.pnl_usd for wealth_movement in unallocated_wealth_movements) == pytest.approx(-47.0)

    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    performance_summary = aggregate_performance_summary(
        strategy_cycles=strategy_cycles,
        interest_breakdowns=[],
        total_equity_usd=6900.0,
        net_capital_deployed_usd=6900.0,
        unallocated_wealth_movements=unallocated_wealth_movements,
    )
    assert performance_summary.strategy_legs_pnl_usd == pytest.approx(100.0)
    assert performance_summary.unallocated_wealth_pnl_usd == pytest.approx(-47.0)
    assert performance_summary.pnl_reconciliation_gap_usd == pytest.approx(-53.0)


def test_compute_holdings_oracle_price_delta_from_previous_amounts() -> None:
    ray_units = float(RAY_UNITS)
    previous_checkpoint = AaveSentinelPositionCheckpoint(
        block_number=1,
        timestamp_seconds=100,
        scaled_balances=[
            AaveSentinelReserveScaledBalanceState(
                underlying_address=BTC_CONTRACT_ADDRESS,
                scaled_supply_balance=2.0,
                scaled_debt_balance=0.0,
            ),
        ],
        reserve_index_snapshots=[
            AaveSentinelReserveIndexSnapshot(
                underlying_address=BTC_CONTRACT_ADDRESS,
                liquidity_index=ray_units,
                variable_borrow_index=ray_units,
            ),
        ],
        asset_prices_usd=[
            AaveSentinelAssetPriceUsd(
                underlying_address=BTC_CONTRACT_ADDRESS,
                price_usd=100.0,
            ),
            AaveSentinelAssetPriceUsd(
                underlying_address=USDC_CONTRACT_ADDRESS,
                price_usd=1.0,
            ),
        ],
        wallet_token_balances=[
            AaveSentinelWalletTokenBalance(
                underlying_address=USDC_CONTRACT_ADDRESS,
                token_amount=50.0,
            ),
        ],
    )
    current_checkpoint = AaveSentinelPositionCheckpoint(
        block_number=2,
        timestamp_seconds=200,
        asset_prices_usd=[
            AaveSentinelAssetPriceUsd(
                underlying_address=BTC_CONTRACT_ADDRESS,
                price_usd=110.0,
            ),
            AaveSentinelAssetPriceUsd(
                underlying_address=USDC_CONTRACT_ADDRESS,
                price_usd=1.0,
            ),
        ],
    )
    oracle_price_delta_usd = compute_holdings_oracle_price_delta_usd(
        previous_checkpoint=previous_checkpoint,
        current_checkpoint=current_checkpoint,
    )
    assert oracle_price_delta_usd == pytest.approx(20.0)


def test_unallocated_peels_computed_oracle_price_gap() -> None:
    ray_units = float(RAY_UNITS)
    previous_checkpoint = AaveSentinelPositionCheckpoint(
        block_number=1,
        timestamp_seconds=100,
        active_strategy_kinds=[],
        equity_usd=200.0,
        wallet_equity_usd=0.0,
        cumulative_external_capital_usd=200.0,
        cumulative_net_interest_usd=0.0,
        scaled_balances=[
            AaveSentinelReserveScaledBalanceState(
                underlying_address=BTC_CONTRACT_ADDRESS,
                scaled_supply_balance=2.0,
                scaled_debt_balance=0.0,
            ),
        ],
        reserve_index_snapshots=[
            AaveSentinelReserveIndexSnapshot(
                underlying_address=BTC_CONTRACT_ADDRESS,
                liquidity_index=ray_units,
                variable_borrow_index=ray_units,
            ),
        ],
        asset_prices_usd=[
            AaveSentinelAssetPriceUsd(
                underlying_address=BTC_CONTRACT_ADDRESS,
                price_usd=100.0,
            ),
        ],
    )
    current_checkpoint = AaveSentinelPositionCheckpoint(
        block_number=2,
        timestamp_seconds=200,
        active_strategy_kinds=[],
        equity_usd=230.0,
        wallet_equity_usd=0.0,
        cumulative_external_capital_usd=200.0,
        cumulative_net_interest_usd=0.0,
        scaled_balances=[
            AaveSentinelReserveScaledBalanceState(
                underlying_address=BTC_CONTRACT_ADDRESS,
                scaled_supply_balance=2.0,
                scaled_debt_balance=0.0,
            ),
        ],
        reserve_index_snapshots=[
            AaveSentinelReserveIndexSnapshot(
                underlying_address=BTC_CONTRACT_ADDRESS,
                liquidity_index=ray_units,
                variable_borrow_index=ray_units,
            ),
        ],
        asset_prices_usd=[
            AaveSentinelAssetPriceUsd(
                underlying_address=BTC_CONTRACT_ADDRESS,
                price_usd=110.0,
            ),
        ],
    )
    unallocated_wealth_movements = build_unallocated_wealth_movements_from_checkpoints(
        position_checkpoints=[previous_checkpoint, current_checkpoint],
        interval_forensic_breakdowns=[],
    )
    oracle_movements = [
        wealth_movement
        for wealth_movement in unallocated_wealth_movements
        if wealth_movement.source == AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP
    ]
    assert len(oracle_movements) == 1
    assert oracle_movements[0].pnl_usd == pytest.approx(20.0)
    assert sum(wealth_movement.pnl_usd for wealth_movement in unallocated_wealth_movements) == pytest.approx(20.0)


def test_allocate_signed_component_into_residual_same_sign_only() -> None:
    allocated_usd, remaining_usd = allocate_signed_component_into_residual(
        residual_usd=-58.0,
        component_usd=-3.4,
    )
    assert allocated_usd == pytest.approx(-3.4)
    assert remaining_usd == pytest.approx(-54.6)
    allocated_opposite_usd, remaining_opposite_usd = allocate_signed_component_into_residual(
        residual_usd=-58.0,
        component_usd=10.0,
    )
    assert allocated_opposite_usd == pytest.approx(0.0)
    assert remaining_opposite_usd == pytest.approx(-58.0)


def test_ledger_entry_conversion_candidate_and_pnl() -> None:
    protocol_token_addresses = frozenset({"0aatoken", "0vdebt"})
    conversion_ledger_entry = AaveSentinelUniversalLedgerEntry(
        transaction_hash="0xconv",
        erc20_transfer_flows=[
            AaveSentinelErc20TransferFlowRecord(
                contract_address="0usdc",
                transfer_flow=AaveSentinelErc20TransferFlow(outgoing_amount=100.0),
            ),
            AaveSentinelErc20TransferFlowRecord(
                contract_address="0usdt",
                transfer_flow=AaveSentinelErc20TransferFlow(incoming_amount=97.0),
            ),
        ],
    )
    assert ledger_entry_is_token_conversion_candidate(
        ledger_entry=conversion_ledger_entry,
        aave_protocol_token_addresses=protocol_token_addresses,
    )
    assert compute_ledger_entry_conversion_pnl_usd(
        ledger_entry=conversion_ledger_entry,
        asset_price_usd_by_contract={"0usdc": 1.0, "0usdt": 1.0},
        aave_protocol_token_addresses=protocol_token_addresses,
    ) == pytest.approx(-3.0)


def test_coalesce_adjacent_interest_accrual_movements() -> None:
    coalesced_movements = coalesce_adjacent_interest_accrual_movements(
        unallocated_wealth_movements=[
            AaveSentinelUnallocatedWealthMovement(
                source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
                started_at_timestamp_seconds=100,
                ended_at_timestamp_seconds=200,
                pnl_usd=0.93,
            ),
            AaveSentinelUnallocatedWealthMovement(
                source=AaveSentinelNonTradingMovementSource.GAS_FEES,
                started_at_timestamp_seconds=150,
                ended_at_timestamp_seconds=200,
                pnl_usd=-1.0,
            ),
            AaveSentinelUnallocatedWealthMovement(
                source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
                started_at_timestamp_seconds=210,
                ended_at_timestamp_seconds=300,
                pnl_usd=1.38,
            ),
        ],
    )
    interest_movements = [
        wealth_movement
        for wealth_movement in coalesced_movements
        if wealth_movement.source == AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL
    ]
    assert len(interest_movements) == 1
    assert interest_movements[0].pnl_usd == pytest.approx(2.31)


def test_micro_long_keeps_portfolio_boundary_residual_unallocated() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="WAVAX",
            long_leverage=1.0,
            long_strategy_equity_usd=3.5,
            cumulative_long_strategy_capital_usd=3.5,
            equity_usd=10003.5,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=10000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="WAVAX",
            long_leverage=1.0,
            long_strategy_equity_usd=3.5,
            cumulative_long_strategy_capital_usd=3.5,
            equity_usd=10023.5,
            wallet_equity_usd=1.0,
            cumulative_external_capital_usd=10001.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[],
            before_transfer_long_strategy_equity_usd=3.5,
            cumulative_long_strategy_capital_usd=3.5,
            equity_usd=10020.0,
            wallet_equity_usd=1.0,
            cumulative_external_capital_usd=10001.5,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    long_cycle = strategy_cycles[0]
    unallocated_wealth_movements = build_unallocated_wealth_movements_from_checkpoints(
        position_checkpoints=checkpoints,
        interval_forensic_breakdowns=[],
        strategy_cycles=strategy_cycles,
    )
    assert long_cycle.gross_pnl_usd == pytest.approx(0.0)
    assert sum(
        wealth_movement.pnl_usd for wealth_movement in unallocated_wealth_movements
    ) == pytest.approx(16.0)


def test_sole_long_with_residual_aave_equity_ignores_dca_notional_as_pnl() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="BTC.b",
            long_leverage=1.0,
            long_strategy_equity_usd=5.0,
            cumulative_long_strategy_capital_usd=5.0,
            equity_usd=15.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=15.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="BTC.b",
            long_leverage=1.0,
            long_strategy_equity_usd=5.0,
            cumulative_long_strategy_capital_usd=5.0,
            equity_usd=13.59,
            wallet_equity_usd=1.41,
            cumulative_external_capital_usd=15.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="BTC.b",
            long_leverage=1.0,
            long_strategy_equity_usd=6.41,
            cumulative_long_strategy_capital_usd=6.41,
            equity_usd=14.41,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=15.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=4,
            timestamp_seconds=400,
            active_strategy_kinds=[],
            before_transfer_long_strategy_equity_usd=6.41,
            cumulative_long_strategy_capital_usd=6.41,
            equity_usd=8.0,
            wallet_equity_usd=6.41,
            cumulative_external_capital_usd=15.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    long_cycle = strategy_cycles[0]
    assert long_cycle.kind == AaveSentinelStrategyKind.LONG
    assert long_cycle.gross_pnl_usd == pytest.approx(0.0)


def test_sole_long_full_cover_mark_to_market_remains_on_cycle() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="BTC.b",
            long_leverage=1.0,
            long_strategy_equity_usd=1000.0,
            cumulative_long_strategy_capital_usd=1000.0,
            equity_usd=1000.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.LONG],
            long_main_asset_symbol="BTC.b",
            long_leverage=1.0,
            long_strategy_equity_usd=1045.85,
            cumulative_long_strategy_capital_usd=1000.0,
            equity_usd=1045.85,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[],
            before_transfer_long_strategy_equity_usd=1045.85,
            cumulative_long_strategy_capital_usd=1000.0,
            equity_usd=0.0,
            wallet_equity_usd=1045.85,
            cumulative_external_capital_usd=1000.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    long_cycle = strategy_cycles[0]
    assert long_cycle.kind == AaveSentinelStrategyKind.LONG
    assert long_cycle.gross_pnl_usd == pytest.approx(45.85)


def test_sole_short_with_residual_aave_equity_uses_position_only_pnl() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1500.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1500.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1100.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1600.0,
            wallet_equity_usd=50.0,
            cumulative_external_capital_usd=1500.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[],
            before_transfer_short_strategy_equity_usd=1100.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=500.0,
            wallet_equity_usd=1100.0,
            cumulative_external_capital_usd=1500.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    short_cycle = strategy_cycles[0]
    assert short_cycle.gross_pnl_usd == pytest.approx(100.0)


def test_active_strategy_interval_absorbs_interest_delta_as_dont_breakdown() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1000.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
            cumulative_net_interest_usd=10.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1050.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1050.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
            cumulative_net_interest_usd=14.5,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    short_cycle = strategy_cycles[0]
    build_unallocated_wealth_movements_from_checkpoints(
        position_checkpoints=checkpoints,
        interval_forensic_breakdowns=[],
        strategy_cycles=strategy_cycles,
    )
    interest_absorbed_usd: float = sum(
        source_breakdown.pnl_usd
        for source_breakdown in short_cycle.absorbed_source_breakdowns
        if source_breakdown.source == AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL
    )
    assert interest_absorbed_usd == pytest.approx(4.5)
    assert short_cycle.gross_pnl_usd == pytest.approx(50.0)


def test_sole_strategy_close_absorbs_wallet_boundary_conversion_residual() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_leverage=2.0,
            short_strategy_equity_usd=1000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=1000.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[],
            before_transfer_short_strategy_equity_usd=1000.0,
            cumulative_short_strategy_capital_usd=1000.0,
            equity_usd=0.0,
            wallet_equity_usd=999.07,
            cumulative_external_capital_usd=1000.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    assert len(strategy_cycles) == 1
    short_cycle = strategy_cycles[0]

    unallocated_wealth_movements = build_unallocated_wealth_movements_from_checkpoints(
        position_checkpoints=checkpoints,
        interval_forensic_breakdowns=[
            AaveSentinelIntervalForensicBreakdown(
                window_start_timestamp_seconds=100,
                window_end_timestamp_seconds=200,
                gas_fee_usd=0.0,
                conversion_pnl_usd=-0.93,
            ),
        ],
        strategy_cycles=strategy_cycles,
        reserve_registry=build_test_reserve_registry(),
    )
    assert short_cycle.gross_pnl_usd == pytest.approx(-0.93)
    assert unallocated_wealth_movements == []
    slippage_absorbed_usd = sum(
        source_breakdown.pnl_usd
        for source_breakdown in short_cycle.absorbed_source_breakdowns
        if source_breakdown.source == AaveSentinelNonTradingMovementSource.SLIPPAGE
    )
    assert slippage_absorbed_usd == pytest.approx(-0.93)

    performance_summary = aggregate_performance_summary(
        strategy_cycles=strategy_cycles,
        interest_breakdowns=[],
        total_equity_usd=999.07,
        net_capital_deployed_usd=1000.0,
        unallocated_wealth_movements=unallocated_wealth_movements,
    )
    assert performance_summary.pnl_reconciliation_gap_usd == pytest.approx(0.0)


def test_idle_eurc_oracle_gap_sets_dominant_asset_symbol() -> None:
    ray_units = float(RAY_UNITS)
    previous_checkpoint = AaveSentinelPositionCheckpoint(
        block_number=1,
        timestamp_seconds=100,
        active_strategy_kinds=[],
        equity_usd=5894.0,
        wallet_equity_usd=0.0,
        cumulative_external_capital_usd=5894.0,
        cumulative_net_interest_usd=0.0,
        scaled_balances=[
            AaveSentinelReserveScaledBalanceState(
                underlying_address=EURC_CONTRACT_ADDRESS,
                scaled_supply_balance=5060.0,
                scaled_debt_balance=0.0,
            ),
        ],
        reserve_index_snapshots=[
            AaveSentinelReserveIndexSnapshot(
                underlying_address=EURC_CONTRACT_ADDRESS,
                liquidity_index=ray_units,
                variable_borrow_index=ray_units,
            ),
        ],
        asset_prices_usd=[
            AaveSentinelAssetPriceUsd(
                underlying_address=EURC_CONTRACT_ADDRESS,
                price_usd=1.1648,
            ),
        ],
    )
    current_checkpoint = AaveSentinelPositionCheckpoint(
        block_number=2,
        timestamp_seconds=200,
        active_strategy_kinds=[],
        equity_usd=5826.0,
        wallet_equity_usd=0.0,
        cumulative_external_capital_usd=5894.0,
        cumulative_net_interest_usd=0.0,
        scaled_balances=[
            AaveSentinelReserveScaledBalanceState(
                underlying_address=EURC_CONTRACT_ADDRESS,
                scaled_supply_balance=5060.0,
                scaled_debt_balance=0.0,
            ),
        ],
        reserve_index_snapshots=[
            AaveSentinelReserveIndexSnapshot(
                underlying_address=EURC_CONTRACT_ADDRESS,
                liquidity_index=ray_units,
                variable_borrow_index=ray_units,
            ),
        ],
        asset_prices_usd=[
            AaveSentinelAssetPriceUsd(
                underlying_address=EURC_CONTRACT_ADDRESS,
                price_usd=1.1514,
            ),
        ],
    )
    unallocated_wealth_movements = build_unallocated_wealth_movements_from_checkpoints(
        position_checkpoints=[previous_checkpoint, current_checkpoint],
        interval_forensic_breakdowns=[],
        reserve_registry=build_test_reserve_registry(),
    )
    oracle_movements = [
        wealth_movement
        for wealth_movement in unallocated_wealth_movements
        if wealth_movement.source == AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP
    ]
    assert len(oracle_movements) == 1
    assert oracle_movements[0].dominant_asset_symbol == "EURC"
    assert oracle_movements[0].pnl_usd == pytest.approx(5060.0 * (1.1514 - 1.1648))


def test_idle_then_short_keeps_unallocated_outside_strategy_window() -> None:
    checkpoints = [
        AaveSentinelPositionCheckpoint(
            block_number=1,
            timestamp_seconds=100,
            active_strategy_kinds=[],
            equity_usd=1000.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
            cumulative_net_interest_usd=0.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=2,
            timestamp_seconds=200,
            active_strategy_kinds=[],
            equity_usd=1005.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
            cumulative_net_interest_usd=5.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=3,
            timestamp_seconds=300,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=1005.0,
            cumulative_short_strategy_capital_usd=1005.0,
            equity_usd=1005.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
            cumulative_net_interest_usd=5.0,
        ),
        AaveSentinelPositionCheckpoint(
            block_number=4,
            timestamp_seconds=400,
            active_strategy_kinds=[AaveSentinelStrategyKind.SHORT],
            short_main_asset_symbol="BTC.b",
            short_strategy_equity_usd=1105.0,
            cumulative_short_strategy_capital_usd=1005.0,
            equity_usd=1105.0,
            wallet_equity_usd=0.0,
            cumulative_external_capital_usd=1000.0,
            cumulative_net_interest_usd=5.0,
        ),
    ]
    strategy_cycles = build_strategy_cycles_from_checkpoints(position_checkpoints=checkpoints)
    unallocated_wealth_movements = build_unallocated_wealth_movements_from_checkpoints(
        position_checkpoints=checkpoints,
        interval_forensic_breakdowns=[],
        strategy_cycles=strategy_cycles,
    )
    assert strategy_cycles[0].gross_pnl_usd == pytest.approx(100.0)
    for wealth_movement in unallocated_wealth_movements:
        assert wealth_movement.ended_at_timestamp_seconds <= strategy_cycles[0].opened_at_timestamp_seconds
    performance_summary = aggregate_performance_summary(
        strategy_cycles=strategy_cycles,
        interest_breakdowns=[],
        total_equity_usd=1105.0,
        net_capital_deployed_usd=1000.0,
        unallocated_wealth_movements=unallocated_wealth_movements,
    )
    assert performance_summary.pnl_reconciliation_gap_usd == pytest.approx(0.0)
