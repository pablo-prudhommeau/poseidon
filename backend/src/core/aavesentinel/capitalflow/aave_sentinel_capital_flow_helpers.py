from __future__ import annotations

from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import (
    EURO_STABLECOIN_SYMBOLS,
    NATIVE_AVAX_ASSET_SYMBOL,
    TOKEN_AMOUNT_DUST_EPSILON,
    USD_FIAT_STABLECOIN_SYMBOLS,
)
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetFlowTotals,
    AaveSentinelCapitalFlowDirection,
    AaveSentinelCapitalFlowSummary,
    AaveSentinelCapitalFlowValuationContext,
    AaveSentinelClassifiedCapitalFlow,
    AaveSentinelRawCapitalFlowEvent,
    AaveSentinelReserveAsset,
    AaveSentinelReserveRegistry,
    AaveSentinelUniversalLedger,
    AaveSentinelUniversalLedgerEntry,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    is_aave_protocol_token_contract,
    is_pure_capital_inflow_transaction,
    is_pure_capital_outflow_transaction,
    ledger_entry_has_outgoing_erc20_transfer,
    ledger_entry_is_aave_borrow_transaction,
    ledger_entry_is_aave_repay_transaction,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_ledger_helpers import (
    ensure_asset_flow_totals_for_symbol,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_valuation_memo_helpers import (
    AaveSentinelCapitalFlowUsdValuationResolver,
)
from src.core.utils.date_utils import get_current_local_datetime

EMPTY_AAVE_SENTINEL_RESERVE_REGISTRY = AaveSentinelReserveRegistry()


def requires_euro_conversion_for_symbol(asset_symbol: str) -> bool:
    return asset_symbol.strip().upper() in EURO_STABLECOIN_SYMBOLS


def is_fiat_stablecoin_symbol(asset_symbol: str) -> bool:
    normalized_symbol = asset_symbol.strip().upper()
    return (
            normalized_symbol in EURO_STABLECOIN_SYMBOLS
            or normalized_symbol in USD_FIAT_STABLECOIN_SYMBOLS
    )


def create_empty_capital_flow_summary() -> AaveSentinelCapitalFlowSummary:
    return AaveSentinelCapitalFlowSummary(
        is_available=False,
        refreshed_at=get_current_local_datetime(),
    )


def resolve_aave_protocol_token_addresses(reserve_registry: AaveSentinelReserveRegistry) -> frozenset[str]:
    protocol_token_addresses: set[str] = set()
    for reserve_asset in reserve_registry.reserve_assets:
        protocol_token_addresses.update({
            reserve_asset.a_token_address,
            reserve_asset.stable_debt_token_address,
            reserve_asset.variable_debt_token_address,
        })
    return frozenset(protocol_token_addresses)


def resolve_aave_debt_token_addresses(reserve_registry: AaveSentinelReserveRegistry) -> frozenset[str]:
    debt_token_addresses: set[str] = set()
    for reserve_asset in reserve_registry.reserve_assets:
        debt_token_addresses.update({
            reserve_asset.stable_debt_token_address,
            reserve_asset.variable_debt_token_address,
        })
    return frozenset(debt_token_addresses)


def resolve_stablecoin_symbols(reserve_registry: AaveSentinelReserveRegistry) -> frozenset[str]:
    return frozenset(
        reserve_asset.symbol
        for reserve_asset in reserve_registry.reserve_assets
        if is_fiat_stablecoin_symbol(reserve_asset.symbol)
    )


def resolve_reserve_asset_for_underlying(
        reserve_registry: AaveSentinelReserveRegistry,
        underlying_address: str,
) -> AaveSentinelReserveAsset | None:
    normalized_underlying_address: str = underlying_address.lower()
    for reserve_asset in reserve_registry.reserve_assets:
        if reserve_asset.underlying_address == normalized_underlying_address:
            return reserve_asset
    return None


def is_aave_oracle_priceable_capital_flow_event(
        reserve_registry: AaveSentinelReserveRegistry,
        contract_address: Optional[str],
        asset_symbol: str,
        requires_euro_conversion: bool,
) -> bool:
    if requires_euro_conversion:
        return True
    if asset_symbol == NATIVE_AVAX_ASSET_SYMBOL:
        return True
    if contract_address is None:
        return False
    return resolve_reserve_asset_for_underlying(
        reserve_registry=reserve_registry,
        underlying_address=contract_address,
    ) is not None


def filter_oracle_priceable_capital_flow_events(
        raw_flow_events: list[AaveSentinelRawCapitalFlowEvent],
        reserve_registry: AaveSentinelReserveRegistry,
) -> tuple[list[AaveSentinelRawCapitalFlowEvent], list[AaveSentinelRawCapitalFlowEvent]]:
    priceable_flow_events: list[AaveSentinelRawCapitalFlowEvent] = []
    excluded_flow_events: list[AaveSentinelRawCapitalFlowEvent] = []
    for raw_flow_event in raw_flow_events:
        if is_aave_oracle_priceable_capital_flow_event(
                reserve_registry=reserve_registry,
                contract_address=raw_flow_event.contract_address,
                asset_symbol=raw_flow_event.asset_symbol,
                requires_euro_conversion=raw_flow_event.requires_euro_conversion,
        ):
            priceable_flow_events.append(raw_flow_event)
            continue
        excluded_flow_events.append(raw_flow_event)
    return priceable_flow_events, excluded_flow_events


def resolve_asset_symbol_for_contract(
        reserve_registry: AaveSentinelReserveRegistry,
        contract_address: str,
) -> str:
    reserve_asset = resolve_reserve_asset_for_underlying(
        reserve_registry=reserve_registry,
        underlying_address=contract_address,
    )
    if reserve_asset is not None:
        return reserve_asset.symbol
    return contract_address.lower()


def collect_pure_capital_flow_events(
        universal_ledger: AaveSentinelUniversalLedger,
        reserve_registry: AaveSentinelReserveRegistry,
) -> list[AaveSentinelRawCapitalFlowEvent]:
    raw_flow_events: list[AaveSentinelRawCapitalFlowEvent] = []
    aave_protocol_token_addresses = resolve_aave_protocol_token_addresses(reserve_registry=reserve_registry)
    aave_debt_token_addresses = resolve_aave_debt_token_addresses(reserve_registry=reserve_registry)

    for ledger_entry in universal_ledger.entries:
        is_aave_borrow_transaction = ledger_entry_is_aave_borrow_transaction(
            ledger_entry=ledger_entry,
            aave_debt_token_addresses=aave_debt_token_addresses,
        )
        is_aave_repay_transaction = ledger_entry_is_aave_repay_transaction(
            ledger_entry=ledger_entry,
            aave_debt_token_addresses=aave_debt_token_addresses,
        )

        net_native_amount: float = ledger_entry.native_received_amount - ledger_entry.native_sent_amount
        if abs(net_native_amount) >= TOKEN_AMOUNT_DUST_EPSILON:
            if net_native_amount > 0 and is_pure_capital_inflow_transaction(ledger_entry):
                raw_flow_events.append(
                    _build_raw_capital_flow_event(
                        ledger_entry=ledger_entry,
                        reserve_registry=reserve_registry,
                        contract_address=None,
                        asset_symbol=NATIVE_AVAX_ASSET_SYMBOL,
                        direction=AaveSentinelCapitalFlowDirection.INFLOW,
                        token_amount=net_native_amount,
                    )
                )
            elif (
                    net_native_amount < 0
                    and is_pure_capital_outflow_transaction(ledger_entry)
                    and not ledger_entry_has_outgoing_erc20_transfer(ledger_entry)
            ):
                raw_flow_events.append(
                    _build_raw_capital_flow_event(
                        ledger_entry=ledger_entry,
                        reserve_registry=reserve_registry,
                        contract_address=None,
                        asset_symbol=NATIVE_AVAX_ASSET_SYMBOL,
                        direction=AaveSentinelCapitalFlowDirection.OUTFLOW,
                        token_amount=abs(net_native_amount),
                    )
                )

        for transfer_flow_record in ledger_entry.erc20_transfer_flows:
            contract_address = transfer_flow_record.contract_address
            if is_aave_protocol_token_contract(
                    contract_address=contract_address,
                    aave_protocol_token_addresses=aave_protocol_token_addresses,
            ):
                continue

            transfer_flow = transfer_flow_record.transfer_flow
            net_flow_amount: float = transfer_flow.incoming_amount - transfer_flow.outgoing_amount
            if abs(net_flow_amount) < TOKEN_AMOUNT_DUST_EPSILON:
                continue

            if net_flow_amount > 0:
                if not is_pure_capital_inflow_transaction(ledger_entry):
                    continue
                if is_aave_borrow_transaction:
                    continue
                asset_symbol = resolve_asset_symbol_for_contract(
                    reserve_registry=reserve_registry,
                    contract_address=contract_address,
                )
                raw_flow_events.append(
                    _build_raw_capital_flow_event(
                        ledger_entry=ledger_entry,
                        reserve_registry=reserve_registry,
                        contract_address=contract_address,
                        asset_symbol=asset_symbol,
                        direction=AaveSentinelCapitalFlowDirection.INFLOW,
                        token_amount=net_flow_amount,
                    )
                )
                continue

            if not is_pure_capital_outflow_transaction(ledger_entry):
                continue
            if is_aave_repay_transaction:
                continue

            asset_symbol = resolve_asset_symbol_for_contract(
                reserve_registry=reserve_registry,
                contract_address=contract_address,
            )
            raw_flow_events.append(
                _build_raw_capital_flow_event(
                    ledger_entry=ledger_entry,
                    reserve_registry=reserve_registry,
                    contract_address=contract_address,
                    asset_symbol=asset_symbol,
                    direction=AaveSentinelCapitalFlowDirection.OUTFLOW,
                    token_amount=abs(net_flow_amount),
                )
            )

    return raw_flow_events


def convert_raw_capital_flow_events_to_classified_flows(
        raw_flow_events: list[AaveSentinelRawCapitalFlowEvent],
        valuation_resolver: AaveSentinelCapitalFlowUsdValuationResolver,
) -> list[AaveSentinelClassifiedCapitalFlow]:
    classified_flows: list[AaveSentinelClassifiedCapitalFlow] = []

    for raw_flow_event in raw_flow_events:
        valuation_context = AaveSentinelCapitalFlowValuationContext(
            contract_address=raw_flow_event.contract_address,
            asset_symbol=raw_flow_event.asset_symbol,
            block_number=raw_flow_event.block_number,
            timestamp_seconds=raw_flow_event.timestamp_seconds,
            token_amount=raw_flow_event.token_amount,
            requires_euro_conversion=raw_flow_event.requires_euro_conversion,
        )
        amount_usd = valuation_resolver.resolve_amount_usd(valuation_context=valuation_context)

        classified_flows.append(
            AaveSentinelClassifiedCapitalFlow(
                transaction_hash=raw_flow_event.transaction_hash,
                block_number=raw_flow_event.block_number,
                timestamp_seconds=raw_flow_event.timestamp_seconds,
                asset_symbol=raw_flow_event.asset_symbol,
                contract_address=raw_flow_event.contract_address,
                direction=raw_flow_event.direction,
                token_amount=raw_flow_event.token_amount,
                amount_usd=amount_usd,
            )
        )

    return classified_flows


def aggregate_capital_flow_summary(
        classified_flows: list[AaveSentinelClassifiedCapitalFlow],
        is_available: bool,
) -> AaveSentinelCapitalFlowSummary:
    asset_flow_totals: list[AaveSentinelAssetFlowTotals] = []
    total_inflow_usd: float = 0.0
    total_outflow_usd: float = 0.0

    for classified_flow in classified_flows:
        asset_totals = ensure_asset_flow_totals_for_symbol(
            asset_flow_totals=asset_flow_totals,
            asset_symbol=classified_flow.asset_symbol,
        )

        if classified_flow.direction == AaveSentinelCapitalFlowDirection.INFLOW:
            asset_totals.total_inflow_token_amount += classified_flow.token_amount
            asset_totals.total_inflow_usd += classified_flow.amount_usd
            total_inflow_usd += classified_flow.amount_usd
            continue

        asset_totals.total_outflow_token_amount += classified_flow.token_amount
        asset_totals.total_outflow_usd += classified_flow.amount_usd
        total_outflow_usd += classified_flow.amount_usd

    return AaveSentinelCapitalFlowSummary(
        total_inflow_usd=total_inflow_usd,
        total_outflow_usd=total_outflow_usd,
        net_capital_deployed_usd=total_inflow_usd - total_outflow_usd,
        asset_flow_totals=asset_flow_totals,
        classified_flows=classified_flows,
        is_available=is_available,
    )


def _build_raw_capital_flow_event(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        reserve_registry: AaveSentinelReserveRegistry,
        contract_address: str | None,
        asset_symbol: str,
        direction: AaveSentinelCapitalFlowDirection,
        token_amount: float,
) -> AaveSentinelRawCapitalFlowEvent:
    reserve_asset: AaveSentinelReserveAsset | None = None
    if contract_address is not None:
        reserve_asset = resolve_reserve_asset_for_underlying(
            reserve_registry=reserve_registry,
            underlying_address=contract_address,
        )

    requires_euro_conversion: bool = False
    if reserve_asset is not None:
        requires_euro_conversion = reserve_asset.requires_euro_conversion

    return AaveSentinelRawCapitalFlowEvent(
        transaction_hash=ledger_entry.transaction_hash,
        block_number=ledger_entry.block_number,
        timestamp_seconds=ledger_entry.timestamp_seconds,
        contract_address=contract_address,
        asset_symbol=asset_symbol,
        direction=direction,
        token_amount=token_amount,
        requires_euro_conversion=requires_euro_conversion,
    )
