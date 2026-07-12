from __future__ import annotations

from typing import Callable

from src.core.aavesentinel.aave_sentinel_fiat_flow_structures import (
    AaveSentinelClassifiedFiatFlow,
    AaveSentinelErc20TransferFlow,
    AaveSentinelFiatFlowDirection,
    AaveSentinelFiatFlowSummary,
    AaveSentinelRawFiatFlowEvent,
    AaveSentinelStablecoinFlowTotals,
    AaveSentinelTrackedStablecoin,
    AaveSentinelUniversalLedgerEntry,
)
from src.integrations.routescan.routescan_structures import (
    RoutescanInternalTransactionRecord,
    RoutescanNormalTransactionRecord,
    RoutescanTokenTransactionRecord,
)

PURE_FLOW_AMOUNT_EPSILON: float = 0.000_001
MAX_NATIVE_RECEIVED_FOR_OUTFLOW_AVAX: float = 0.05

ResolveEuroToUsdExchangeRate = Callable[[int, int], float]


def build_universal_ledger(
        wallet_address: str,
        normal_transactions: list[RoutescanNormalTransactionRecord],
        internal_transactions: list[RoutescanInternalTransactionRecord],
        token_transactions: list[RoutescanTokenTransactionRecord],
) -> dict[str, AaveSentinelUniversalLedgerEntry]:
    normalized_wallet_address: str = wallet_address.lower()
    ledger_by_transaction_hash: dict[str, AaveSentinelUniversalLedgerEntry] = {}

    for normal_transaction in normal_transactions:
        transaction_hash: str = normal_transaction.transaction_hash.lower()
        if not transaction_hash:
            continue

        ledger_entry = _ensure_ledger_entry(
            ledger_by_transaction_hash=ledger_by_transaction_hash,
            transaction_hash=transaction_hash,
        )
        ledger_entry.timestamp_seconds = int(normal_transaction.timestamp_seconds)
        ledger_entry.block_number = int(normal_transaction.block_number)

        native_amount: float = int(normal_transaction.native_value_wei) / (10 ** 18)
        if normal_transaction.sender_address.lower() == normalized_wallet_address:
            ledger_entry.native_sent_amount += native_amount
        if normal_transaction.recipient_address.lower() == normalized_wallet_address:
            ledger_entry.native_received_amount += native_amount

    for internal_transaction in internal_transactions:
        transaction_hash = internal_transaction.transaction_hash.lower()
        if not transaction_hash:
            continue

        ledger_entry = _ensure_ledger_entry(
            ledger_by_transaction_hash=ledger_by_transaction_hash,
            transaction_hash=transaction_hash,
        )

        native_amount = int(internal_transaction.native_value_wei) / (10 ** 18)
        if internal_transaction.sender_address.lower() == normalized_wallet_address:
            ledger_entry.native_sent_amount += native_amount
        if internal_transaction.recipient_address.lower() == normalized_wallet_address:
            ledger_entry.native_received_amount += native_amount

    for token_transaction in token_transactions:
        transaction_hash = token_transaction.transaction_hash.lower()
        if not transaction_hash:
            continue

        ledger_entry = _ensure_ledger_entry(
            ledger_by_transaction_hash=ledger_by_transaction_hash,
            transaction_hash=transaction_hash,
        )
        ledger_entry.timestamp_seconds = int(token_transaction.timestamp_seconds)
        ledger_entry.block_number = int(token_transaction.block_number)

        contract_address: str = token_transaction.contract_address.lower()
        decimal_count: int = int(token_transaction.token_decimal_count)
        token_amount: float = int(token_transaction.token_value_raw) / (10 ** decimal_count)

        transfer_flow = ledger_entry.erc20_transfer_flows_by_contract.get(contract_address)
        if transfer_flow is None:
            transfer_flow = AaveSentinelErc20TransferFlow()
            ledger_entry.erc20_transfer_flows_by_contract[contract_address] = transfer_flow

        if token_transaction.recipient_address.lower() == normalized_wallet_address:
            transfer_flow.incoming_amount += token_amount
        if token_transaction.sender_address.lower() == normalized_wallet_address:
            transfer_flow.outgoing_amount += token_amount

    return ledger_by_transaction_hash


def collect_pure_fiat_flow_events(
        ledger_by_transaction_hash: dict[str, AaveSentinelUniversalLedgerEntry],
        tracked_stablecoins: list[AaveSentinelTrackedStablecoin],
) -> list[AaveSentinelRawFiatFlowEvent]:
    raw_flow_events: list[AaveSentinelRawFiatFlowEvent] = []

    for tracked_stablecoin in tracked_stablecoins:
        stablecoin_contract_address: str = tracked_stablecoin.contract_address.lower()

        for ledger_entry in ledger_by_transaction_hash.values():
            transfer_flow = ledger_entry.erc20_transfer_flows_by_contract.get(stablecoin_contract_address)
            if transfer_flow is None:
                continue

            net_flow_amount: float = transfer_flow.incoming_amount - transfer_flow.outgoing_amount
            if abs(net_flow_amount) < PURE_FLOW_AMOUNT_EPSILON:
                continue

            if net_flow_amount > 0:
                sent_any_erc20: bool = _ledger_entry_sent_any_erc20(ledger_entry=ledger_entry)
                if sent_any_erc20 or ledger_entry.native_sent_amount != 0:
                    continue

                raw_flow_events.append(
                    AaveSentinelRawFiatFlowEvent(
                        transaction_hash=ledger_entry.transaction_hash,
                        block_number=ledger_entry.block_number,
                        timestamp_seconds=ledger_entry.timestamp_seconds,
                        stablecoin_symbol=tracked_stablecoin.symbol,
                        direction=AaveSentinelFiatFlowDirection.INFLOW,
                        token_amount=net_flow_amount,
                        requires_euro_conversion=tracked_stablecoin.requires_euro_conversion,
                    )
                )
                continue

            received_any_other_erc20: bool = _ledger_entry_received_any_other_erc20(
                ledger_entry=ledger_entry,
                excluded_contract_address=stablecoin_contract_address,
            )
            if received_any_other_erc20 or ledger_entry.native_received_amount >= MAX_NATIVE_RECEIVED_FOR_OUTFLOW_AVAX:
                continue

            outflow_amount: float = abs(net_flow_amount)
            raw_flow_events.append(
                AaveSentinelRawFiatFlowEvent(
                    transaction_hash=ledger_entry.transaction_hash,
                    block_number=ledger_entry.block_number,
                    timestamp_seconds=ledger_entry.timestamp_seconds,
                    stablecoin_symbol=tracked_stablecoin.symbol,
                    direction=AaveSentinelFiatFlowDirection.OUTFLOW,
                    token_amount=outflow_amount,
                    requires_euro_conversion=tracked_stablecoin.requires_euro_conversion,
                )
            )

    return raw_flow_events


def convert_raw_fiat_flow_events_to_classified_flows(
        raw_flow_events: list[AaveSentinelRawFiatFlowEvent],
        resolve_euro_to_usd_exchange_rate: ResolveEuroToUsdExchangeRate,
) -> list[AaveSentinelClassifiedFiatFlow]:
    classified_flows: list[AaveSentinelClassifiedFiatFlow] = []

    for raw_flow_event in raw_flow_events:
        if raw_flow_event.requires_euro_conversion:
            exchange_rate: float = resolve_euro_to_usd_exchange_rate(
                block_number=raw_flow_event.block_number,
                timestamp_seconds=raw_flow_event.timestamp_seconds,
            )
            amount_usd = raw_flow_event.token_amount * exchange_rate
        else:
            amount_usd = raw_flow_event.token_amount

        classified_flows.append(
            AaveSentinelClassifiedFiatFlow(
                transaction_hash=raw_flow_event.transaction_hash,
                block_number=raw_flow_event.block_number,
                timestamp_seconds=raw_flow_event.timestamp_seconds,
                stablecoin_symbol=raw_flow_event.stablecoin_symbol,
                direction=raw_flow_event.direction,
                token_amount=raw_flow_event.token_amount,
                amount_usd=amount_usd,
            )
        )

    return classified_flows


def aggregate_fiat_flow_summary(
        classified_flows: list[AaveSentinelClassifiedFiatFlow],
        tracked_stablecoins: list[AaveSentinelTrackedStablecoin],
        is_available: bool,
) -> AaveSentinelFiatFlowSummary:
    stablecoin_totals_by_symbol: dict[str, AaveSentinelStablecoinFlowTotals] = {}

    for tracked_stablecoin in tracked_stablecoins:
        stablecoin_totals_by_symbol[tracked_stablecoin.symbol] = AaveSentinelStablecoinFlowTotals(
            stablecoin_symbol=tracked_stablecoin.symbol,
        )

    total_inflow_usd: float = 0.0
    total_outflow_usd: float = 0.0

    for classified_flow in classified_flows:
        stablecoin_totals = stablecoin_totals_by_symbol[classified_flow.stablecoin_symbol]

        if classified_flow.direction == AaveSentinelFiatFlowDirection.INFLOW:
            stablecoin_totals.total_inflow_token_amount += classified_flow.token_amount
            stablecoin_totals.total_inflow_usd += classified_flow.amount_usd
            total_inflow_usd += classified_flow.amount_usd
            continue

        stablecoin_totals.total_outflow_token_amount += classified_flow.token_amount
        stablecoin_totals.total_outflow_usd += classified_flow.amount_usd
        total_outflow_usd += classified_flow.amount_usd

    return AaveSentinelFiatFlowSummary(
        total_inflow_usd=total_inflow_usd,
        total_outflow_usd=total_outflow_usd,
        net_capital_deployed_usd=total_inflow_usd - total_outflow_usd,
        stablecoin_totals=list(stablecoin_totals_by_symbol.values()),
        classified_flows=classified_flows,
        is_available=is_available,
    )


def _ensure_ledger_entry(
        ledger_by_transaction_hash: dict[str, AaveSentinelUniversalLedgerEntry],
        transaction_hash: str,
) -> AaveSentinelUniversalLedgerEntry:
    ledger_entry = ledger_by_transaction_hash.get(transaction_hash)
    if ledger_entry is None:
        ledger_entry = AaveSentinelUniversalLedgerEntry(transaction_hash=transaction_hash)
        ledger_by_transaction_hash[transaction_hash] = ledger_entry
    return ledger_entry


def _ledger_entry_sent_any_erc20(ledger_entry: AaveSentinelUniversalLedgerEntry) -> bool:
    for transfer_flow in ledger_entry.erc20_transfer_flows_by_contract.values():
        if transfer_flow.outgoing_amount > PURE_FLOW_AMOUNT_EPSILON:
            return True
    return False


def _ledger_entry_received_any_other_erc20(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        excluded_contract_address: str,
) -> bool:
    for contract_address, transfer_flow in ledger_entry.erc20_transfer_flows_by_contract.items():
        if contract_address == excluded_contract_address:
            continue
        if transfer_flow.incoming_amount > PURE_FLOW_AMOUNT_EPSILON:
            return True
    return False
