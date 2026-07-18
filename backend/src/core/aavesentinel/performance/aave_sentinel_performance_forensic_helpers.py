from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import TOKEN_AMOUNT_DUST_EPSILON
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelIntervalForensicBreakdown,
    AaveSentinelNonTradingMovementSource,
    AaveSentinelNonTradingPeriodSourceBreakdown,
    AaveSentinelOraclePriceGapAssetContribution,
    AaveSentinelPositionCheckpoint,
    AaveSentinelReserveRegistry,
    AaveSentinelStrategyCycleSummary,
    AaveSentinelUnallocatedWealthMovement,
    AaveSentinelUniversalLedgerEntry,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    convert_scaled_balance_to_token_amount,
    is_aave_protocol_token_contract,
    is_pure_capital_inflow_transaction,
    is_pure_capital_outflow_transaction,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    resolve_reserve_asset_for_underlying,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_checkpoint_helpers import (
    compute_checkpoint_wallet_boundary_pnl_usd,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_constants import (
    INTEREST_ACCRUAL_COALESCE_MAX_GAP_SECONDS,
    ORACLE_PRICE_GAP_DOMINANT_ASSET_SHARE_THRESHOLD,
    UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_cycle_pnl_helpers import (
    compute_interval_fresh_capital_adjusted_strategy_pnl_usd,
    resolve_strategy_cycle_overlapping_timestamp_window,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_scaled_balance_helpers import (
    resolve_reserve_index_snapshot,
    resolve_scaled_balance_state,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_wallet_balance_helpers import (
    find_wallet_token_balance,
    resolve_asset_price_usd_from_prices,
)


def allocate_signed_component_into_residual(
        residual_usd: float,
        component_usd: float,
) -> tuple[float, float]:
    if abs(residual_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
        return 0.0, residual_usd
    if abs(component_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
        return 0.0, residual_usd
    if residual_usd > 0.0 and component_usd > 0.0:
        allocated_usd = min(residual_usd, component_usd)
        return allocated_usd, residual_usd - allocated_usd
    if residual_usd < 0.0 and component_usd < 0.0:
        allocated_usd = -min(abs(residual_usd), abs(component_usd))
        return allocated_usd, residual_usd - allocated_usd
    return 0.0, residual_usd


def ledger_entry_is_token_conversion_candidate(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        aave_protocol_token_addresses: frozenset[str],
) -> bool:
    if is_pure_capital_inflow_transaction(ledger_entry):
        return False
    if is_pure_capital_outflow_transaction(ledger_entry):
        return False
    has_non_protocol_incoming_transfer = False
    has_non_protocol_outgoing_transfer = False
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if is_aave_protocol_token_contract(
                contract_address=transfer_flow_record.contract_address,
                aave_protocol_token_addresses=aave_protocol_token_addresses,
        ):
            continue
        if transfer_flow_record.transfer_flow.incoming_amount > TOKEN_AMOUNT_DUST_EPSILON:
            has_non_protocol_incoming_transfer = True
        if transfer_flow_record.transfer_flow.outgoing_amount > TOKEN_AMOUNT_DUST_EPSILON:
            has_non_protocol_outgoing_transfer = True
    return has_non_protocol_incoming_transfer and has_non_protocol_outgoing_transfer


def compute_ledger_entry_conversion_pnl_usd(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        asset_price_usd_by_contract: dict[str, float],
        aave_protocol_token_addresses: frozenset[str],
) -> float:
    if not ledger_entry_is_token_conversion_candidate(
            ledger_entry=ledger_entry,
            aave_protocol_token_addresses=aave_protocol_token_addresses,
    ):
        return 0.0
    incoming_value_usd: float = 0.0
    outgoing_value_usd: float = 0.0
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if is_aave_protocol_token_contract(
                contract_address=transfer_flow_record.contract_address,
                aave_protocol_token_addresses=aave_protocol_token_addresses,
        ):
            continue
        asset_price_usd = asset_price_usd_by_contract.get(
            transfer_flow_record.contract_address.lower(),
        )
        if asset_price_usd is None:
            continue
        incoming_value_usd += transfer_flow_record.transfer_flow.incoming_amount * asset_price_usd
        outgoing_value_usd += transfer_flow_record.transfer_flow.outgoing_amount * asset_price_usd
    if (
            abs(incoming_value_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD
            and abs(outgoing_value_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD
    ):
        return 0.0
    return incoming_value_usd - outgoing_value_usd


def collect_conversion_contract_addresses_from_ledger_entry(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        aave_protocol_token_addresses: frozenset[str],
) -> list[str]:
    contract_addresses: list[str] = []
    if not ledger_entry_is_token_conversion_candidate(
            ledger_entry=ledger_entry,
            aave_protocol_token_addresses=aave_protocol_token_addresses,
    ):
        return contract_addresses
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if is_aave_protocol_token_contract(
                contract_address=transfer_flow_record.contract_address,
                aave_protocol_token_addresses=aave_protocol_token_addresses,
        ):
            continue
        if (
                abs(transfer_flow_record.transfer_flow.incoming_amount) < TOKEN_AMOUNT_DUST_EPSILON
                and abs(transfer_flow_record.transfer_flow.outgoing_amount) < TOKEN_AMOUNT_DUST_EPSILON
        ):
            continue
        contract_addresses.append(transfer_flow_record.contract_address.lower())
    return contract_addresses


def resolve_dominant_asset_symbol_from_oracle_contributions(
        oracle_price_gap_asset_contributions: list[AaveSentinelOraclePriceGapAssetContribution],
) -> Optional[str]:
    absolute_contribution_total_usd: float = sum(
        abs(asset_contribution.pnl_usd)
        for asset_contribution in oracle_price_gap_asset_contributions
    )
    if absolute_contribution_total_usd < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
        return None
    dominant_asset_contribution: Optional[AaveSentinelOraclePriceGapAssetContribution] = None
    for asset_contribution in oracle_price_gap_asset_contributions:
        if dominant_asset_contribution is None:
            dominant_asset_contribution = asset_contribution
            continue
        if abs(asset_contribution.pnl_usd) > abs(dominant_asset_contribution.pnl_usd):
            dominant_asset_contribution = asset_contribution
    if dominant_asset_contribution is None:
        return None
    dominant_share: float = (
            abs(dominant_asset_contribution.pnl_usd) / absolute_contribution_total_usd
    )
    if dominant_share < ORACLE_PRICE_GAP_DOMINANT_ASSET_SHARE_THRESHOLD:
        return None
    return dominant_asset_contribution.asset_symbol


def _append_non_trading_movement_if_material(
        unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement],
        source: AaveSentinelNonTradingMovementSource,
        started_at_timestamp_seconds: int,
        ended_at_timestamp_seconds: int,
        pnl_usd: float,
        dominant_asset_symbol: Optional[str] = None,
) -> None:
    if abs(pnl_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
        return
    unallocated_wealth_movements.append(
        AaveSentinelUnallocatedWealthMovement(
            source=source,
            started_at_timestamp_seconds=started_at_timestamp_seconds,
            ended_at_timestamp_seconds=ended_at_timestamp_seconds,
            pnl_usd=pnl_usd,
            dominant_asset_symbol=dominant_asset_symbol,
        )
    )


def _peel_forensic_components_from_residual(
        residual_usd: float,
        interest_component_usd: float,
        gas_fee_usd: float,
        conversion_pnl_usd: float,
        oracle_price_delta_usd: float,
        started_at_timestamp_seconds: int,
        ended_at_timestamp_seconds: int,
        oracle_price_gap_asset_contributions: Optional[
            list[AaveSentinelOraclePriceGapAssetContribution]
        ] = None,
) -> list[AaveSentinelUnallocatedWealthMovement]:
    resolved_oracle_price_gap_asset_contributions: list[
        AaveSentinelOraclePriceGapAssetContribution
    ] = (
        []
        if oracle_price_gap_asset_contributions is None
        else oracle_price_gap_asset_contributions
    )
    peeled_movements: list[AaveSentinelUnallocatedWealthMovement] = []
    interest_allocated_usd: float = 0.0
    if abs(interest_component_usd) >= UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
        interest_allocated_usd = interest_component_usd
        _append_non_trading_movement_if_material(
            unallocated_wealth_movements=peeled_movements,
            source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
            started_at_timestamp_seconds=started_at_timestamp_seconds,
            ended_at_timestamp_seconds=ended_at_timestamp_seconds,
            pnl_usd=interest_allocated_usd,
        )
    remaining_residual_usd: float = residual_usd - interest_allocated_usd

    gas_component_usd: float = -abs(gas_fee_usd) if gas_fee_usd > 0 else 0.0
    gas_allocated_usd, remaining_residual_usd = allocate_signed_component_into_residual(
        residual_usd=remaining_residual_usd,
        component_usd=gas_component_usd,
    )
    _append_non_trading_movement_if_material(
        unallocated_wealth_movements=peeled_movements,
        source=AaveSentinelNonTradingMovementSource.GAS_FEES,
        started_at_timestamp_seconds=started_at_timestamp_seconds,
        ended_at_timestamp_seconds=ended_at_timestamp_seconds,
        pnl_usd=gas_allocated_usd,
    )

    conversion_allocated_usd, remaining_residual_usd = allocate_signed_component_into_residual(
        residual_usd=remaining_residual_usd,
        component_usd=conversion_pnl_usd,
    )
    _append_non_trading_movement_if_material(
        unallocated_wealth_movements=peeled_movements,
        source=AaveSentinelNonTradingMovementSource.SLIPPAGE,
        started_at_timestamp_seconds=started_at_timestamp_seconds,
        ended_at_timestamp_seconds=ended_at_timestamp_seconds,
        pnl_usd=conversion_allocated_usd,
    )

    oracle_price_allocated_usd, remaining_unexplained_residual_usd = (
        allocate_signed_component_into_residual(
            residual_usd=remaining_residual_usd,
            component_usd=oracle_price_delta_usd,
        )
    )
    dominant_asset_symbol: Optional[str] = None
    if abs(oracle_price_allocated_usd) >= UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
        dominant_asset_symbol = resolve_dominant_asset_symbol_from_oracle_contributions(
            oracle_price_gap_asset_contributions=resolved_oracle_price_gap_asset_contributions,
        )
    _append_non_trading_movement_if_material(
        unallocated_wealth_movements=peeled_movements,
        source=AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP,
        started_at_timestamp_seconds=started_at_timestamp_seconds,
        ended_at_timestamp_seconds=ended_at_timestamp_seconds,
        pnl_usd=oracle_price_allocated_usd,
        dominant_asset_symbol=dominant_asset_symbol,
    )
    forensic_components_allocated_usd: float = (
            abs(gas_allocated_usd)
            + abs(conversion_allocated_usd)
            + abs(oracle_price_allocated_usd)
    )
    if (
            abs(remaining_unexplained_residual_usd) >= UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD
            and forensic_components_allocated_usd < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD
    ):
        _append_non_trading_movement_if_material(
            unallocated_wealth_movements=peeled_movements,
            source=AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP,
            started_at_timestamp_seconds=started_at_timestamp_seconds,
            ended_at_timestamp_seconds=ended_at_timestamp_seconds,
            pnl_usd=remaining_unexplained_residual_usd,
        )
    return peeled_movements


def _merge_absorbed_source_breakdown_into_cycle(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        source: AaveSentinelNonTradingMovementSource,
        pnl_usd: float,
        dominant_asset_symbol: Optional[str] = None,
) -> None:
    if abs(pnl_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
        return
    for source_breakdown in strategy_cycle.absorbed_source_breakdowns:
        if source_breakdown.source != source:
            continue
        source_breakdown.pnl_usd += pnl_usd
        if (
                source_breakdown.dominant_asset_symbol is not None
                and dominant_asset_symbol is not None
                and source_breakdown.dominant_asset_symbol != dominant_asset_symbol
        ):
            source_breakdown.dominant_asset_symbol = None
        elif source_breakdown.dominant_asset_symbol is None and dominant_asset_symbol is not None:
            source_breakdown.dominant_asset_symbol = dominant_asset_symbol
        return
    strategy_cycle.absorbed_source_breakdowns.append(
        AaveSentinelNonTradingPeriodSourceBreakdown(
            source=source,
            pnl_usd=pnl_usd,
            dominant_asset_symbol=dominant_asset_symbol,
        )
    )


def _resolve_primary_strategy_cycle_for_interval(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
        previous_checkpoint: AaveSentinelPositionCheckpoint,
        current_checkpoint: AaveSentinelPositionCheckpoint,
) -> Optional[AaveSentinelStrategyCycleSummary]:
    for strategy_kind in previous_checkpoint.active_strategy_kinds:
        strategy_cycle = resolve_strategy_cycle_overlapping_timestamp_window(
            strategy_cycles=strategy_cycles,
            strategy_kind=strategy_kind,
            window_start_timestamp_seconds=previous_checkpoint.timestamp_seconds,
            window_end_timestamp_seconds=current_checkpoint.timestamp_seconds,
        )
        if strategy_cycle is not None:
            return strategy_cycle
    return None


def _accumulate_absorbed_forensic_components_into_strategy_cycle(
        strategy_cycle: AaveSentinelStrategyCycleSummary,
        interest_delta_usd: float,
        gas_fee_usd: float,
        conversion_pnl_usd: float,
        oracle_price_gap_asset_contributions: list[AaveSentinelOraclePriceGapAssetContribution],
) -> None:
    _merge_absorbed_source_breakdown_into_cycle(
        strategy_cycle=strategy_cycle,
        source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
        pnl_usd=interest_delta_usd,
    )
    gas_component_usd: float = -abs(gas_fee_usd) if gas_fee_usd > 0 else 0.0
    _merge_absorbed_source_breakdown_into_cycle(
        strategy_cycle=strategy_cycle,
        source=AaveSentinelNonTradingMovementSource.GAS_FEES,
        pnl_usd=gas_component_usd,
    )
    _merge_absorbed_source_breakdown_into_cycle(
        strategy_cycle=strategy_cycle,
        source=AaveSentinelNonTradingMovementSource.SLIPPAGE,
        pnl_usd=conversion_pnl_usd,
    )
    excluded_main_asset_symbols: set[str] = set()
    if strategy_cycle.main_asset_symbol is not None:
        excluded_main_asset_symbols.add(strategy_cycle.main_asset_symbol)
    non_main_asset_contributions: list[AaveSentinelOraclePriceGapAssetContribution] = [
        asset_contribution
        for asset_contribution in oracle_price_gap_asset_contributions
        if (
                asset_contribution.asset_symbol is None
                or asset_contribution.asset_symbol not in excluded_main_asset_symbols
        )
    ]
    non_main_oracle_price_delta_usd: float = sum(
        asset_contribution.pnl_usd for asset_contribution in non_main_asset_contributions
    )
    dominant_asset_symbol = resolve_dominant_asset_symbol_from_oracle_contributions(
        oracle_price_gap_asset_contributions=non_main_asset_contributions,
    )
    _merge_absorbed_source_breakdown_into_cycle(
        strategy_cycle=strategy_cycle,
        source=AaveSentinelNonTradingMovementSource.ORACLE_PRICE_GAP,
        pnl_usd=non_main_oracle_price_delta_usd,
        dominant_asset_symbol=dominant_asset_symbol,
    )


def _merged_window_crosses_strategy_boundary(
        previous_movement: AaveSentinelUnallocatedWealthMovement,
        wealth_movement: AaveSentinelUnallocatedWealthMovement,
        strategy_boundary_timestamps_seconds: list[int],
) -> bool:
    merged_started_at_timestamp_seconds: int = previous_movement.started_at_timestamp_seconds
    merged_ended_at_timestamp_seconds: int = max(
        previous_movement.ended_at_timestamp_seconds,
        wealth_movement.ended_at_timestamp_seconds,
    )
    for strategy_boundary_timestamp_seconds in strategy_boundary_timestamps_seconds:
        if (
                merged_started_at_timestamp_seconds
                < strategy_boundary_timestamp_seconds
                < merged_ended_at_timestamp_seconds
        ):
            return True
        if (
                previous_movement.ended_at_timestamp_seconds
                < strategy_boundary_timestamp_seconds
                <= wealth_movement.started_at_timestamp_seconds
        ):
            return True
    return False


def _coalesce_adjacent_movements_for_source(
        unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement],
        movement_source: AaveSentinelNonTradingMovementSource,
        strategy_boundary_timestamps_seconds: Optional[list[int]] = None,
) -> list[AaveSentinelUnallocatedWealthMovement]:
    resolved_strategy_boundary_timestamps_seconds: list[int] = (
        []
        if strategy_boundary_timestamps_seconds is None
        else strategy_boundary_timestamps_seconds
    )
    source_movements: list[AaveSentinelUnallocatedWealthMovement] = [
        wealth_movement
        for wealth_movement in unallocated_wealth_movements
        if wealth_movement.source == movement_source
    ]
    other_movements: list[AaveSentinelUnallocatedWealthMovement] = [
        wealth_movement
        for wealth_movement in unallocated_wealth_movements
        if wealth_movement.source != movement_source
    ]
    source_movements.sort(
        key=lambda wealth_movement: (
            wealth_movement.started_at_timestamp_seconds,
            wealth_movement.ended_at_timestamp_seconds,
        ),
    )
    coalesced_source_movements: list[AaveSentinelUnallocatedWealthMovement] = []
    for wealth_movement in source_movements:
        if (
                coalesced_source_movements
                and (
                wealth_movement.started_at_timestamp_seconds
                - coalesced_source_movements[-1].ended_at_timestamp_seconds
        ) <= INTEREST_ACCRUAL_COALESCE_MAX_GAP_SECONDS
                and not _merged_window_crosses_strategy_boundary(
                    previous_movement=coalesced_source_movements[-1],
                    wealth_movement=wealth_movement,
                    strategy_boundary_timestamps_seconds=resolved_strategy_boundary_timestamps_seconds,
                )
        ):
            previous_movement: AaveSentinelUnallocatedWealthMovement = (
                coalesced_source_movements[-1]
            )
            coalesced_dominant_asset_symbol: Optional[str] = (
                previous_movement.dominant_asset_symbol
            )
            if (
                    previous_movement.dominant_asset_symbol is not None
                    and wealth_movement.dominant_asset_symbol is not None
                    and previous_movement.dominant_asset_symbol
                    != wealth_movement.dominant_asset_symbol
            ):
                coalesced_dominant_asset_symbol = None
            elif previous_movement.dominant_asset_symbol is None:
                coalesced_dominant_asset_symbol = wealth_movement.dominant_asset_symbol
            coalesced_source_movements[-1] = AaveSentinelUnallocatedWealthMovement(
                source=movement_source,
                started_at_timestamp_seconds=previous_movement.started_at_timestamp_seconds,
                ended_at_timestamp_seconds=wealth_movement.ended_at_timestamp_seconds,
                pnl_usd=previous_movement.pnl_usd + wealth_movement.pnl_usd,
                dominant_asset_symbol=coalesced_dominant_asset_symbol,
            )
            continue
        coalesced_source_movements.append(wealth_movement)
    combined_movements: list[AaveSentinelUnallocatedWealthMovement] = (
            other_movements + coalesced_source_movements
    )
    combined_movements.sort(
        key=lambda wealth_movement: (
            wealth_movement.started_at_timestamp_seconds,
            wealth_movement.source.value,
            wealth_movement.ended_at_timestamp_seconds,
        ),
    )
    return combined_movements


def _collect_strategy_boundary_timestamps_seconds(
        strategy_cycles: list[AaveSentinelStrategyCycleSummary],
) -> list[int]:
    strategy_boundary_timestamps_seconds: list[int] = []
    for strategy_cycle in strategy_cycles:
        strategy_boundary_timestamps_seconds.append(strategy_cycle.opened_at_timestamp_seconds)
        if strategy_cycle.closed_at_timestamp_seconds is not None:
            strategy_boundary_timestamps_seconds.append(
                strategy_cycle.closed_at_timestamp_seconds,
            )
    return sorted(set(strategy_boundary_timestamps_seconds))


def coalesce_adjacent_interest_accrual_movements(
        unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement],
        strategy_cycles: Optional[list[AaveSentinelStrategyCycleSummary]] = None,
) -> list[AaveSentinelUnallocatedWealthMovement]:
    if not unallocated_wealth_movements:
        return []
    resolved_strategy_cycles: list[AaveSentinelStrategyCycleSummary] = (
        [] if strategy_cycles is None else strategy_cycles
    )
    strategy_boundary_timestamps_seconds: list[int] = (
        _collect_strategy_boundary_timestamps_seconds(
            strategy_cycles=resolved_strategy_cycles,
        )
    )
    coalesced_movements: list[AaveSentinelUnallocatedWealthMovement] = (
        _coalesce_adjacent_movements_for_source(
            unallocated_wealth_movements=unallocated_wealth_movements,
            movement_source=AaveSentinelNonTradingMovementSource.INTEREST_ACCRUAL,
            strategy_boundary_timestamps_seconds=strategy_boundary_timestamps_seconds,
        )
    )
    return _coalesce_adjacent_movements_for_source(
        unallocated_wealth_movements=coalesced_movements,
        movement_source=AaveSentinelNonTradingMovementSource.GAS_FEES,
        strategy_boundary_timestamps_seconds=strategy_boundary_timestamps_seconds,
    )


def resolve_interval_forensic_breakdown(
        interval_forensic_breakdowns: list[AaveSentinelIntervalForensicBreakdown],
        window_start_timestamp_seconds: int,
        window_end_timestamp_seconds: int,
) -> AaveSentinelIntervalForensicBreakdown:
    for interval_forensic_breakdown in interval_forensic_breakdowns:
        if (
                interval_forensic_breakdown.window_start_timestamp_seconds == window_start_timestamp_seconds
                and interval_forensic_breakdown.window_end_timestamp_seconds == window_end_timestamp_seconds
        ):
            return interval_forensic_breakdown
    return AaveSentinelIntervalForensicBreakdown(
        window_start_timestamp_seconds=window_start_timestamp_seconds,
        window_end_timestamp_seconds=window_end_timestamp_seconds,
    )


def build_unallocated_wealth_movements_from_checkpoints(
        position_checkpoints: list[AaveSentinelPositionCheckpoint],
        interval_forensic_breakdowns: Optional[list[AaveSentinelIntervalForensicBreakdown]] = None,
        strategy_cycles: Optional[list[AaveSentinelStrategyCycleSummary]] = None,
        reserve_registry: Optional[AaveSentinelReserveRegistry] = None,
) -> list[AaveSentinelUnallocatedWealthMovement]:
    resolved_interval_forensic_breakdowns: list[AaveSentinelIntervalForensicBreakdown] = (
        [] if interval_forensic_breakdowns is None else interval_forensic_breakdowns
    )
    resolved_strategy_cycles: list[AaveSentinelStrategyCycleSummary] = (
        [] if strategy_cycles is None else strategy_cycles
    )
    unallocated_wealth_movements: list[AaveSentinelUnallocatedWealthMovement] = []
    if not position_checkpoints:
        return unallocated_wealth_movements

    first_position_checkpoint: AaveSentinelPositionCheckpoint = position_checkpoints[0]
    opening_wallet_boundary_pnl_usd: float = compute_checkpoint_wallet_boundary_pnl_usd(
        position_checkpoint=first_position_checkpoint,
    )
    opening_forensic_breakdown: AaveSentinelIntervalForensicBreakdown = (
        resolve_interval_forensic_breakdown(
            interval_forensic_breakdowns=resolved_interval_forensic_breakdowns,
            window_start_timestamp_seconds=0,
            window_end_timestamp_seconds=first_position_checkpoint.timestamp_seconds,
        )
    )
    if (
            not first_position_checkpoint.active_strategy_kinds
            and abs(opening_wallet_boundary_pnl_usd) >= UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD
    ):
        unallocated_wealth_movements.extend(
            _peel_forensic_components_from_residual(
                residual_usd=opening_wallet_boundary_pnl_usd,
                interest_component_usd=first_position_checkpoint.cumulative_net_interest_usd,
                gas_fee_usd=opening_forensic_breakdown.gas_fee_usd,
                conversion_pnl_usd=opening_forensic_breakdown.conversion_pnl_usd,
                oracle_price_delta_usd=0.0,
                started_at_timestamp_seconds=first_position_checkpoint.timestamp_seconds,
                ended_at_timestamp_seconds=first_position_checkpoint.timestamp_seconds,
            )
        )

    for checkpoint_index in range(1, len(position_checkpoints)):
        previous_checkpoint: AaveSentinelPositionCheckpoint = position_checkpoints[
            checkpoint_index - 1
            ]
        current_checkpoint: AaveSentinelPositionCheckpoint = position_checkpoints[
            checkpoint_index
        ]
        wallet_boundary_delta_usd: float = (
                compute_checkpoint_wallet_boundary_pnl_usd(current_checkpoint)
                - compute_checkpoint_wallet_boundary_pnl_usd(previous_checkpoint)
        )
        attributed_strategy_pnl_usd: float = 0.0
        for strategy_kind in previous_checkpoint.active_strategy_kinds:
            attributed_strategy_pnl_usd += compute_interval_fresh_capital_adjusted_strategy_pnl_usd(
                previous_checkpoint=previous_checkpoint,
                current_checkpoint=current_checkpoint,
                strategy_kind=strategy_kind,
            )
        residual_usd: float = wallet_boundary_delta_usd - attributed_strategy_pnl_usd
        oracle_price_delta_usd, oracle_price_gap_asset_contributions = (
            compute_holdings_oracle_price_delta_breakdown(
                previous_checkpoint=previous_checkpoint,
                current_checkpoint=current_checkpoint,
                reserve_registry=reserve_registry,
            )
        )
        interval_forensic_breakdown: AaveSentinelIntervalForensicBreakdown = (
            resolve_interval_forensic_breakdown(
                interval_forensic_breakdowns=resolved_interval_forensic_breakdowns,
                window_start_timestamp_seconds=previous_checkpoint.timestamp_seconds,
                window_end_timestamp_seconds=current_checkpoint.timestamp_seconds,
            )
        )

        interest_delta_usd: float = (
                current_checkpoint.cumulative_net_interest_usd
                - previous_checkpoint.cumulative_net_interest_usd
        )
        primary_strategy_cycle: Optional[AaveSentinelStrategyCycleSummary] = None
        if previous_checkpoint.active_strategy_kinds:
            primary_strategy_cycle = _resolve_primary_strategy_cycle_for_interval(
                strategy_cycles=resolved_strategy_cycles,
                previous_checkpoint=previous_checkpoint,
                current_checkpoint=current_checkpoint,
            )
            if primary_strategy_cycle is not None:
                _accumulate_absorbed_forensic_components_into_strategy_cycle(
                    strategy_cycle=primary_strategy_cycle,
                    interest_delta_usd=interest_delta_usd,
                    gas_fee_usd=interval_forensic_breakdown.gas_fee_usd,
                    conversion_pnl_usd=interval_forensic_breakdown.conversion_pnl_usd,
                    oracle_price_gap_asset_contributions=oracle_price_gap_asset_contributions,
                )

        is_sole_strategy_close_interval: bool = (
                len(previous_checkpoint.active_strategy_kinds) == 1
                and previous_checkpoint.active_strategy_kinds[0]
                not in current_checkpoint.active_strategy_kinds
        )
        if (
                is_sole_strategy_close_interval
                and primary_strategy_cycle is not None
                and abs(residual_usd) >= UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD
        ):
            close_remaining_residual_usd: float = residual_usd
            gas_component_usd: float = (
                -abs(interval_forensic_breakdown.gas_fee_usd)
                if interval_forensic_breakdown.gas_fee_usd > 0
                else 0.0
            )
            gas_allocated_usd, close_remaining_residual_usd = (
                allocate_signed_component_into_residual(
                    residual_usd=close_remaining_residual_usd,
                    component_usd=gas_component_usd,
                )
            )
            conversion_allocated_usd, close_remaining_residual_usd = (
                allocate_signed_component_into_residual(
                    residual_usd=close_remaining_residual_usd,
                    component_usd=interval_forensic_breakdown.conversion_pnl_usd,
                )
            )
            close_costs_allocated_usd: float = gas_allocated_usd + conversion_allocated_usd
            if abs(close_costs_allocated_usd) >= UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
                primary_strategy_cycle.gross_pnl_usd += close_costs_allocated_usd
                primary_strategy_cycle.trading_pnl_usd = primary_strategy_cycle.gross_pnl_usd
            if abs(close_remaining_residual_usd) >= UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
                unallocated_wealth_movements.extend(
                    _peel_forensic_components_from_residual(
                        residual_usd=close_remaining_residual_usd,
                        interest_component_usd=0.0,
                        gas_fee_usd=0.0,
                        conversion_pnl_usd=0.0,
                        oracle_price_delta_usd=oracle_price_delta_usd,
                        started_at_timestamp_seconds=previous_checkpoint.timestamp_seconds,
                        ended_at_timestamp_seconds=current_checkpoint.timestamp_seconds,
                        oracle_price_gap_asset_contributions=oracle_price_gap_asset_contributions,
                    )
                )
            continue

        if abs(residual_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
            continue

        unallocated_wealth_movements.extend(
            _peel_forensic_components_from_residual(
                residual_usd=residual_usd,
                interest_component_usd=interest_delta_usd,
                gas_fee_usd=interval_forensic_breakdown.gas_fee_usd,
                conversion_pnl_usd=interval_forensic_breakdown.conversion_pnl_usd,
                oracle_price_delta_usd=oracle_price_delta_usd,
                started_at_timestamp_seconds=previous_checkpoint.timestamp_seconds,
                ended_at_timestamp_seconds=current_checkpoint.timestamp_seconds,
                oracle_price_gap_asset_contributions=oracle_price_gap_asset_contributions,
            )
        )

    return coalesce_adjacent_interest_accrual_movements(
        unallocated_wealth_movements=unallocated_wealth_movements,
        strategy_cycles=resolved_strategy_cycles,
    )


def compute_holdings_oracle_price_delta_breakdown(
        previous_checkpoint: AaveSentinelPositionCheckpoint,
        current_checkpoint: AaveSentinelPositionCheckpoint,
        reserve_registry: Optional[AaveSentinelReserveRegistry] = None,
) -> tuple[float, list[AaveSentinelOraclePriceGapAssetContribution]]:
    underlying_addresses: set[str] = set()
    for scaled_balance in previous_checkpoint.scaled_balances:
        underlying_addresses.add(scaled_balance.underlying_address.lower())
    for wallet_token_balance in previous_checkpoint.wallet_token_balances:
        underlying_addresses.add(wallet_token_balance.underlying_address.lower())

    oracle_price_gap_asset_contributions: list[AaveSentinelOraclePriceGapAssetContribution] = []
    oracle_price_delta_usd: float = 0.0
    for underlying_address in underlying_addresses:
        previous_price_usd = resolve_asset_price_usd_from_prices(
            asset_prices_usd=previous_checkpoint.asset_prices_usd,
            underlying_address=underlying_address,
        )
        current_price_usd = resolve_asset_price_usd_from_prices(
            asset_prices_usd=current_checkpoint.asset_prices_usd,
            underlying_address=underlying_address,
        )
        if previous_price_usd is None or current_price_usd is None:
            continue
        price_delta_usd: float = current_price_usd - previous_price_usd
        if abs(price_delta_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
            continue

        supply_token_amount: float = 0.0
        debt_token_amount: float = 0.0
        previous_scaled_balance = resolve_scaled_balance_state(
            scaled_balances=previous_checkpoint.scaled_balances,
            underlying_address=underlying_address,
        )
        previous_reserve_index_snapshot = resolve_reserve_index_snapshot(
            reserve_index_snapshots=previous_checkpoint.reserve_index_snapshots,
            underlying_address=underlying_address,
        )
        if previous_scaled_balance is not None and previous_reserve_index_snapshot is not None:
            supply_token_amount = convert_scaled_balance_to_token_amount(
                scaled_balance=previous_scaled_balance.scaled_supply_balance,
                reserve_index=previous_reserve_index_snapshot.liquidity_index,
            )
            debt_token_amount = convert_scaled_balance_to_token_amount(
                scaled_balance=previous_scaled_balance.scaled_debt_balance,
                reserve_index=previous_reserve_index_snapshot.variable_borrow_index,
            )

        wallet_token_amount: float = 0.0
        previous_wallet_token_balance = find_wallet_token_balance(
            wallet_token_balances=previous_checkpoint.wallet_token_balances,
            underlying_address=underlying_address,
        )
        if previous_wallet_token_balance is not None:
            wallet_token_amount = previous_wallet_token_balance.token_amount

        asset_oracle_price_delta_usd: float = (
                supply_token_amount * price_delta_usd
                - debt_token_amount * price_delta_usd
                + wallet_token_amount * price_delta_usd
        )
        if abs(asset_oracle_price_delta_usd) < UNALLOCATED_WEALTH_MOVEMENT_EPSILON_USD:
            continue
        asset_symbol: Optional[str] = None
        if reserve_registry is not None:
            reserve_asset = resolve_reserve_asset_for_underlying(
                reserve_registry=reserve_registry,
                underlying_address=underlying_address,
            )
            if reserve_asset is not None:
                asset_symbol = reserve_asset.symbol
        oracle_price_gap_asset_contributions.append(
            AaveSentinelOraclePriceGapAssetContribution(
                underlying_address=underlying_address,
                asset_symbol=asset_symbol,
                pnl_usd=asset_oracle_price_delta_usd,
            )
        )
        oracle_price_delta_usd += asset_oracle_price_delta_usd
    return oracle_price_delta_usd, oracle_price_gap_asset_contributions


def compute_holdings_oracle_price_delta_usd(
        previous_checkpoint: AaveSentinelPositionCheckpoint,
        current_checkpoint: AaveSentinelPositionCheckpoint,
        reserve_registry: Optional[AaveSentinelReserveRegistry] = None,
) -> float:
    oracle_price_delta_usd, _oracle_price_gap_asset_contributions = (
        compute_holdings_oracle_price_delta_breakdown(
            previous_checkpoint=previous_checkpoint,
            current_checkpoint=current_checkpoint,
            reserve_registry=reserve_registry,
        )
    )
    return oracle_price_delta_usd
