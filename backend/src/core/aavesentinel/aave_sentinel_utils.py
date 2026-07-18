from __future__ import annotations

from decimal import Decimal

from src.core.aavesentinel.aave_sentinel_constants import TOKEN_AMOUNT_DUST_EPSILON
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetSnapshot,
    AaveSentinelUniversalLedgerEntry,
)
from src.integrations.aave.aave_abis import RAY_UNITS, SECONDS_PER_YEAR


def compute_latent_profit_and_loss_usd(
        total_equity_usd: float,
        net_capital_deployed_usd: float,
) -> float:
    return total_equity_usd - net_capital_deployed_usd


def compute_cycle_gross_pnl_usd(
        opening_equity_usd: float,
        closing_equity_usd: float,
        net_external_capital_usd: float,
) -> float:
    return closing_equity_usd - opening_equity_usd - net_external_capital_usd


def compute_trading_pnl_usd(
        gross_pnl_usd: float,
        interest_usd: float,
) -> float:
    return gross_pnl_usd - interest_usd


def convert_token_amount_to_scaled_balance(
        token_amount: float,
        reserve_index: float,
) -> float:
    if reserve_index <= 0:
        raise ValueError("Reserve index must be strictly positive")
    return token_amount * float(RAY_UNITS) / reserve_index


def convert_scaled_balance_to_token_amount(
        scaled_balance: float,
        reserve_index: float,
) -> float:
    return scaled_balance * reserve_index / float(RAY_UNITS)


def compute_index_accrued_interest_token_amount(
        scaled_balance: float,
        previous_reserve_index: float,
        next_reserve_index: float,
) -> float:
    return scaled_balance * (next_reserve_index - previous_reserve_index) / float(RAY_UNITS)


def compute_position_total_wallet_usd(assets: list[AaveSentinelAssetSnapshot]) -> float:
    return sum(asset.wallet_value_usd for asset in assets)


def compute_aave_net_worth_usd(total_collateral_usd: float, total_debt_usd: float) -> float:
    return total_collateral_usd - total_debt_usd


def compute_total_strategy_equity_usd(
        total_collateral_usd: float,
        total_debt_usd: float,
        assets: list[AaveSentinelAssetSnapshot],
) -> float:
    return compute_aave_net_worth_usd(
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
    ) + compute_position_total_wallet_usd(assets=assets)


def compute_position_current_leverage(
        total_collateral_usd: float,
        total_debt_usd: float,
) -> float:
    aave_net_worth_usd = compute_aave_net_worth_usd(
        total_collateral_usd=total_collateral_usd,
        total_debt_usd=total_debt_usd,
    )
    if aave_net_worth_usd <= 0:
        return 0.0
    return total_collateral_usd / aave_net_worth_usd


def compute_strategy_leverage(
        collateral_usd: float,
        debt_usd: float,
) -> float:
    strategy_equity_usd = collateral_usd - debt_usd
    if strategy_equity_usd <= 0:
        return 0.0
    return collateral_usd / strategy_equity_usd


def compute_short_liquidation_price_usd(
        stable_collateral_usd: float,
        weighted_stable_collateral_liquidation_threshold: float,
        volatile_debt_token_amount: float,
) -> float:
    if volatile_debt_token_amount <= 0 or weighted_stable_collateral_liquidation_threshold <= 0:
        return 0.0
    return (
            stable_collateral_usd * weighted_stable_collateral_liquidation_threshold
    ) / volatile_debt_token_amount


def compute_long_liquidation_price_usd(
        stable_debt_usd: float,
        volatile_collateral_token_amount: float,
        volatile_collateral_liquidation_threshold: float,
) -> float:
    if (
            volatile_collateral_token_amount <= 0
            or volatile_collateral_liquidation_threshold <= 0
    ):
        return 0.0
    return stable_debt_usd / (
            volatile_collateral_token_amount * volatile_collateral_liquidation_threshold
    )


def decode_aave_reserve_liquidation_threshold(configuration_bitmap: int) -> float:
    liquidation_threshold_basis_points = (configuration_bitmap >> 16) & 0xFFFF
    return liquidation_threshold_basis_points / 10_000


def compute_position_weighted_net_apy(assets: list[AaveSentinelAssetSnapshot]) -> float:
    total_supply_value_usd = sum(asset.supply_value_usd for asset in assets)
    total_debt_value_usd = sum(asset.debt_value_usd for asset in assets)

    if total_supply_value_usd <= 0 and total_debt_value_usd <= 0:
        return 0.0

    total_supply_income_usd = sum(
        asset.supply_value_usd * asset.supply_annual_percentage_yield
        for asset in assets
    )
    total_borrow_cost_usd = sum(
        asset.debt_value_usd * asset.borrow_annual_percentage_yield
        for asset in assets
    )
    current_equity_usd = total_supply_value_usd - total_debt_value_usd

    if current_equity_usd <= 0:
        return 0.0

    return (total_supply_income_usd - total_borrow_cost_usd) / current_equity_usd


def convert_ray_to_annual_percentage_yield(ray_value: int) -> float:
    if ray_value == 0:
        return 0.0

    interest_rate_per_second = Decimal(ray_value) / RAY_UNITS / Decimal(SECONDS_PER_YEAR)
    return float((Decimal(1) + interest_rate_per_second) ** Decimal(SECONDS_PER_YEAR) - Decimal(1))


def compute_ledger_entry_net_native_amount(ledger_entry: AaveSentinelUniversalLedgerEntry) -> float:
    return ledger_entry.native_received_amount - ledger_entry.native_sent_amount


def ledger_entry_has_outgoing_erc20_transfer(ledger_entry: AaveSentinelUniversalLedgerEntry) -> bool:
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if transfer_flow_record.transfer_flow.outgoing_amount > TOKEN_AMOUNT_DUST_EPSILON:
            return True
    return False


def ledger_entry_has_incoming_erc20_transfer(ledger_entry: AaveSentinelUniversalLedgerEntry) -> bool:
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if transfer_flow_record.transfer_flow.incoming_amount > TOKEN_AMOUNT_DUST_EPSILON:
            return True
    return False


def ledger_entry_has_net_native_receipt(ledger_entry: AaveSentinelUniversalLedgerEntry) -> bool:
    return compute_ledger_entry_net_native_amount(ledger_entry) > TOKEN_AMOUNT_DUST_EPSILON


def is_aave_protocol_token_contract(
        contract_address: str,
        aave_protocol_token_addresses: frozenset[str],
) -> bool:
    return contract_address.lower() in aave_protocol_token_addresses


def ledger_entry_is_aave_borrow_transaction(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        aave_debt_token_addresses: frozenset[str],
) -> bool:
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if not is_aave_protocol_token_contract(
                contract_address=transfer_flow_record.contract_address,
                aave_protocol_token_addresses=aave_debt_token_addresses,
        ):
            continue

        net_flow_amount = (
                transfer_flow_record.transfer_flow.incoming_amount
                - transfer_flow_record.transfer_flow.outgoing_amount
        )
        if net_flow_amount > TOKEN_AMOUNT_DUST_EPSILON:
            return True
    return False


def ledger_entry_is_aave_repay_transaction(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        aave_debt_token_addresses: frozenset[str],
) -> bool:
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if not is_aave_protocol_token_contract(
                contract_address=transfer_flow_record.contract_address,
                aave_protocol_token_addresses=aave_debt_token_addresses,
        ):
            continue

        net_flow_amount = (
                transfer_flow_record.transfer_flow.incoming_amount
                - transfer_flow_record.transfer_flow.outgoing_amount
        )
        if net_flow_amount < -TOKEN_AMOUNT_DUST_EPSILON:
            return True
    return False


def is_pure_capital_inflow_transaction(ledger_entry: AaveSentinelUniversalLedgerEntry) -> bool:
    if ledger_entry_has_outgoing_erc20_transfer(ledger_entry):
        return False
    return ledger_entry.native_sent_amount <= TOKEN_AMOUNT_DUST_EPSILON


def is_pure_capital_outflow_transaction(ledger_entry: AaveSentinelUniversalLedgerEntry) -> bool:
    if ledger_entry_has_incoming_erc20_transfer(ledger_entry):
        return False
    return not ledger_entry_has_net_native_receipt(ledger_entry)
