from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import TOKEN_AMOUNT_DUST_EPSILON
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetSnapshot,
    AaveSentinelReserveAsset,
    AaveSentinelReserveIndexSnapshot,
    AaveSentinelReserveInterestBreakdown,
    AaveSentinelReserveRegistry,
    AaveSentinelReserveScaledBalanceState,
    AaveSentinelUniversalLedger,
    AaveSentinelUniversalLedgerEntry,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_index_accrued_interest_token_amount,
    convert_scaled_balance_to_token_amount,
    convert_token_amount_to_scaled_balance,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    resolve_reserve_asset_for_underlying,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_wallet_balance_helpers import (
    resolve_asset_price_usd,
)


def _resolve_interest_breakdown_by_symbol(
        interest_breakdowns: list[AaveSentinelReserveInterestBreakdown],
        asset_symbol: str,
) -> Optional[AaveSentinelReserveInterestBreakdown]:
    for interest_breakdown in interest_breakdowns:
        if interest_breakdown.asset_symbol == asset_symbol:
            return interest_breakdown
    return None


def resolve_reserve_asset_for_a_token_address(
        reserve_registry: AaveSentinelReserveRegistry,
        contract_address: str,
) -> Optional[AaveSentinelReserveAsset]:
    normalized_contract_address: str = contract_address.lower()
    for reserve_asset in reserve_registry.reserve_assets:
        if reserve_asset.a_token_address == normalized_contract_address:
            return reserve_asset
    return None


def resolve_reserve_asset_for_variable_debt_token_address(
        reserve_registry: AaveSentinelReserveRegistry,
        contract_address: str,
) -> Optional[AaveSentinelReserveAsset]:
    normalized_contract_address: str = contract_address.lower()
    for reserve_asset in reserve_registry.reserve_assets:
        if reserve_asset.variable_debt_token_address == normalized_contract_address:
            return reserve_asset
    return None


def find_scaled_balance_state(
        scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        underlying_address: str,
) -> Optional[AaveSentinelReserveScaledBalanceState]:
    normalized_underlying_address: str = underlying_address.lower()
    for scaled_balance_state in scaled_balances:
        if scaled_balance_state.underlying_address == normalized_underlying_address:
            return scaled_balance_state
    return None


def resolve_scaled_balance_state(
        scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        underlying_address: str,
) -> AaveSentinelReserveScaledBalanceState:
    normalized_underlying_address: str = underlying_address.lower()
    for scaled_balance_state in scaled_balances:
        if scaled_balance_state.underlying_address == normalized_underlying_address:
            return scaled_balance_state
    new_scaled_balance_state = AaveSentinelReserveScaledBalanceState(
        underlying_address=normalized_underlying_address,
    )
    scaled_balances.append(new_scaled_balance_state)
    return new_scaled_balance_state


def resolve_reserve_index_snapshot(
        reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
        underlying_address: str,
) -> Optional[AaveSentinelReserveIndexSnapshot]:
    normalized_underlying_address: str = underlying_address.lower()
    for reserve_index_snapshot in reserve_index_snapshots:
        if reserve_index_snapshot.underlying_address == normalized_underlying_address:
            return reserve_index_snapshot
    return None


def ledger_entry_touches_aave_protocol_position(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        reserve_registry: AaveSentinelReserveRegistry,
) -> bool:
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if resolve_reserve_asset_for_a_token_address(
                reserve_registry=reserve_registry,
                contract_address=transfer_flow_record.contract_address,
        ) is not None:
            return True
        if resolve_reserve_asset_for_variable_debt_token_address(
                reserve_registry=reserve_registry,
                contract_address=transfer_flow_record.contract_address,
        ) is not None:
            return True
    return False


def collect_sorted_aave_position_ledger_entries(
        universal_ledger: AaveSentinelUniversalLedger,
        reserve_registry: AaveSentinelReserveRegistry,
) -> list[AaveSentinelUniversalLedgerEntry]:
    matching_ledger_entries: list[AaveSentinelUniversalLedgerEntry] = [
        ledger_entry
        for ledger_entry in universal_ledger.entries
        if ledger_entry_touches_aave_protocol_position(
            ledger_entry=ledger_entry,
            reserve_registry=reserve_registry,
        )
    ]
    matching_ledger_entries.sort(
        key=lambda ledger_entry: (ledger_entry.block_number, ledger_entry.timestamp_seconds, ledger_entry.transaction_hash),
    )
    return matching_ledger_entries


def apply_protocol_token_transfers_to_scaled_balances(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        reserve_registry: AaveSentinelReserveRegistry,
        scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
) -> None:
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        net_transfer_amount: float = (
                transfer_flow_record.transfer_flow.incoming_amount
                - transfer_flow_record.transfer_flow.outgoing_amount
        )
        if abs(net_transfer_amount) < TOKEN_AMOUNT_DUST_EPSILON:
            continue

        a_token_reserve_asset = resolve_reserve_asset_for_a_token_address(
            reserve_registry=reserve_registry,
            contract_address=transfer_flow_record.contract_address,
        )
        if a_token_reserve_asset is not None:
            reserve_index_snapshot = resolve_reserve_index_snapshot(
                reserve_index_snapshots=reserve_index_snapshots,
                underlying_address=a_token_reserve_asset.underlying_address,
            )
            if reserve_index_snapshot is None or reserve_index_snapshot.liquidity_index <= 0:
                continue
            scaled_balance_state = resolve_scaled_balance_state(
                scaled_balances=scaled_balances,
                underlying_address=a_token_reserve_asset.underlying_address,
            )
            scaled_balance_state.scaled_supply_balance += convert_token_amount_to_scaled_balance(
                token_amount=net_transfer_amount,
                reserve_index=reserve_index_snapshot.liquidity_index,
            )
            continue

        debt_token_reserve_asset = resolve_reserve_asset_for_variable_debt_token_address(
            reserve_registry=reserve_registry,
            contract_address=transfer_flow_record.contract_address,
        )
        if debt_token_reserve_asset is None:
            continue
        reserve_index_snapshot = resolve_reserve_index_snapshot(
            reserve_index_snapshots=reserve_index_snapshots,
            underlying_address=debt_token_reserve_asset.underlying_address,
        )
        if reserve_index_snapshot is None or reserve_index_snapshot.variable_borrow_index <= 0:
            continue
        scaled_balance_state = resolve_scaled_balance_state(
            scaled_balances=scaled_balances,
            underlying_address=debt_token_reserve_asset.underlying_address,
        )
        scaled_balance_state.scaled_debt_balance += convert_token_amount_to_scaled_balance(
            token_amount=net_transfer_amount,
            reserve_index=reserve_index_snapshot.variable_borrow_index,
        )


def accrue_interest_between_indices(
        previous_scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        previous_reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
        next_reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
        asset_price_usd_by_underlying: dict[str, float],
        reserve_registry: AaveSentinelReserveRegistry,
) -> tuple[float, float, list[AaveSentinelReserveInterestBreakdown]]:
    supply_interest_usd: float = 0.0
    borrow_interest_usd: float = 0.0
    interest_breakdowns: list[AaveSentinelReserveInterestBreakdown] = []

    for previous_scaled_balance in previous_scaled_balances:
        reserve_asset = resolve_reserve_asset_for_underlying(
            reserve_registry=reserve_registry,
            underlying_address=previous_scaled_balance.underlying_address,
        )
        if reserve_asset is None:
            continue

        previous_index_snapshot = resolve_reserve_index_snapshot(
            reserve_index_snapshots=previous_reserve_index_snapshots,
            underlying_address=previous_scaled_balance.underlying_address,
        )
        next_index_snapshot = resolve_reserve_index_snapshot(
            reserve_index_snapshots=next_reserve_index_snapshots,
            underlying_address=previous_scaled_balance.underlying_address,
        )
        asset_price_usd = resolve_asset_price_usd(
            asset_price_usd_by_underlying=asset_price_usd_by_underlying,
            underlying_address=previous_scaled_balance.underlying_address,
        )
        if previous_index_snapshot is None or next_index_snapshot is None or asset_price_usd is None:
            continue

        supply_interest_token_amount = compute_index_accrued_interest_token_amount(
            scaled_balance=previous_scaled_balance.scaled_supply_balance,
            previous_reserve_index=previous_index_snapshot.liquidity_index,
            next_reserve_index=next_index_snapshot.liquidity_index,
        )
        borrow_interest_token_amount = compute_index_accrued_interest_token_amount(
            scaled_balance=previous_scaled_balance.scaled_debt_balance,
            previous_reserve_index=previous_index_snapshot.variable_borrow_index,
            next_reserve_index=next_index_snapshot.variable_borrow_index,
        )
        period_supply_interest_usd = supply_interest_token_amount * asset_price_usd
        period_borrow_interest_usd = borrow_interest_token_amount * asset_price_usd
        supply_interest_usd += period_supply_interest_usd
        borrow_interest_usd += period_borrow_interest_usd

        interest_breakdown = _resolve_interest_breakdown_by_symbol(
            interest_breakdowns=interest_breakdowns,
            asset_symbol=reserve_asset.symbol,
        )
        if interest_breakdown is None:
            interest_breakdown = AaveSentinelReserveInterestBreakdown(asset_symbol=reserve_asset.symbol)
            interest_breakdowns.append(interest_breakdown)
        interest_breakdown.supply_interest_usd += period_supply_interest_usd
        interest_breakdown.borrow_interest_usd += period_borrow_interest_usd
        interest_breakdown.net_interest_usd = (
                interest_breakdown.supply_interest_usd - interest_breakdown.borrow_interest_usd
        )

    return supply_interest_usd, borrow_interest_usd, interest_breakdowns


def build_asset_snapshots_from_scaled_balances(
        scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
        asset_price_usd_by_underlying: dict[str, float],
        reserve_registry: AaveSentinelReserveRegistry,
) -> list[AaveSentinelAssetSnapshot]:
    asset_snapshots: list[AaveSentinelAssetSnapshot] = []
    for scaled_balance_state in scaled_balances:
        reserve_asset = resolve_reserve_asset_for_underlying(
            reserve_registry=reserve_registry,
            underlying_address=scaled_balance_state.underlying_address,
        )
        if reserve_asset is None:
            continue
        reserve_index_snapshot = resolve_reserve_index_snapshot(
            reserve_index_snapshots=reserve_index_snapshots,
            underlying_address=scaled_balance_state.underlying_address,
        )
        asset_price_usd = resolve_asset_price_usd(
            asset_price_usd_by_underlying=asset_price_usd_by_underlying,
            underlying_address=scaled_balance_state.underlying_address,
        )
        if reserve_index_snapshot is None or asset_price_usd is None:
            continue

        supply_amount = convert_scaled_balance_to_token_amount(
            scaled_balance=scaled_balance_state.scaled_supply_balance,
            reserve_index=reserve_index_snapshot.liquidity_index,
        )
        debt_amount = convert_scaled_balance_to_token_amount(
            scaled_balance=scaled_balance_state.scaled_debt_balance,
            reserve_index=reserve_index_snapshot.variable_borrow_index,
        )
        if abs(supply_amount) < TOKEN_AMOUNT_DUST_EPSILON and abs(debt_amount) < TOKEN_AMOUNT_DUST_EPSILON:
            continue

        asset_snapshots.append(
            AaveSentinelAssetSnapshot(
                symbol=reserve_asset.symbol,
                underlying_address=reserve_asset.underlying_address,
                supply_amount=supply_amount,
                debt_amount=debt_amount,
                wallet_amount=0.0,
                supply_value_usd=supply_amount * asset_price_usd,
                debt_value_usd=debt_amount * asset_price_usd,
                wallet_value_usd=0.0,
                supply_annual_percentage_yield=0.0,
                borrow_annual_percentage_yield=0.0,
            )
        )
    return asset_snapshots


def clone_scaled_balances(
        scaled_balances: list[AaveSentinelReserveScaledBalanceState],
) -> list[AaveSentinelReserveScaledBalanceState]:
    return [
        AaveSentinelReserveScaledBalanceState(
            underlying_address=scaled_balance.underlying_address,
            scaled_supply_balance=scaled_balance.scaled_supply_balance,
            scaled_debt_balance=scaled_balance.scaled_debt_balance,
        )
        for scaled_balance in scaled_balances
    ]


def clone_reserve_index_snapshots(
        reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot],
) -> list[AaveSentinelReserveIndexSnapshot]:
    return [
        AaveSentinelReserveIndexSnapshot(
            underlying_address=reserve_index_snapshot.underlying_address,
            liquidity_index=reserve_index_snapshot.liquidity_index,
            variable_borrow_index=reserve_index_snapshot.variable_borrow_index,
        )
        for reserve_index_snapshot in reserve_index_snapshots
    ]


def collect_underlying_addresses_for_index_lookup(
        scaled_balances: list[AaveSentinelReserveScaledBalanceState],
        ledger_entry: Optional[AaveSentinelUniversalLedgerEntry],
        reserve_registry: AaveSentinelReserveRegistry,
) -> list[str]:
    underlying_addresses: set[str] = {
        scaled_balance.underlying_address
        for scaled_balance in scaled_balances
        if abs(scaled_balance.scaled_supply_balance) >= TOKEN_AMOUNT_DUST_EPSILON
           or abs(scaled_balance.scaled_debt_balance) >= TOKEN_AMOUNT_DUST_EPSILON
    }
    if ledger_entry is not None:
        for transfer_flow_record in ledger_entry.erc20_transfer_flows:
            a_token_reserve_asset = resolve_reserve_asset_for_a_token_address(
                reserve_registry=reserve_registry,
                contract_address=transfer_flow_record.contract_address,
            )
            if a_token_reserve_asset is not None:
                underlying_addresses.add(a_token_reserve_asset.underlying_address)
            debt_token_reserve_asset = resolve_reserve_asset_for_variable_debt_token_address(
                reserve_registry=reserve_registry,
                contract_address=transfer_flow_record.contract_address,
            )
            if debt_token_reserve_asset is not None:
                underlying_addresses.add(debt_token_reserve_asset.underlying_address)
    return sorted(underlying_addresses)
