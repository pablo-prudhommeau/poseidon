from __future__ import annotations

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetFlowTotals,
    AaveSentinelErc20TransferFlow,
    AaveSentinelErc20TransferFlowRecord,
    AaveSentinelUniversalLedger,
    AaveSentinelUniversalLedgerEntry,
)
from src.integrations.routescan.routescan_structures import (
    RoutescanInternalTransactionRecord,
    RoutescanNormalTransactionRecord,
    RoutescanTokenTransactionRecord,
)


def resolve_ledger_entry_for_transaction_hash(
        universal_ledger: AaveSentinelUniversalLedger,
        transaction_hash: str,
) -> AaveSentinelUniversalLedgerEntry | None:
    normalized_transaction_hash: str = transaction_hash.lower()
    for ledger_entry in universal_ledger.entries:
        if ledger_entry.transaction_hash == normalized_transaction_hash:
            return ledger_entry
    return None


def ensure_asset_flow_totals_for_symbol(
        asset_flow_totals: list[AaveSentinelAssetFlowTotals],
        asset_symbol: str,
) -> AaveSentinelAssetFlowTotals:
    for asset_flow_total in asset_flow_totals:
        if asset_flow_total.asset_symbol == asset_symbol:
            return asset_flow_total

    new_asset_flow_total = AaveSentinelAssetFlowTotals(asset_symbol=asset_symbol)
    asset_flow_totals.append(new_asset_flow_total)
    return new_asset_flow_total


def ensure_ledger_entry_for_transaction_hash(
        universal_ledger: AaveSentinelUniversalLedger,
        transaction_hash: str,
) -> AaveSentinelUniversalLedgerEntry:
    existing_ledger_entry = resolve_ledger_entry_for_transaction_hash(
        universal_ledger=universal_ledger,
        transaction_hash=transaction_hash,
    )
    if existing_ledger_entry is not None:
        return existing_ledger_entry

    normalized_transaction_hash: str = transaction_hash.lower()
    ledger_entry = AaveSentinelUniversalLedgerEntry(transaction_hash=normalized_transaction_hash)
    universal_ledger.entries.append(ledger_entry)
    return ledger_entry


def ensure_ledger_transfer_flow_for_contract(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        contract_address: str,
) -> AaveSentinelErc20TransferFlow:
    normalized_contract_address: str = contract_address.lower()
    for transfer_flow_record in ledger_entry.erc20_transfer_flows:
        if transfer_flow_record.contract_address == normalized_contract_address:
            return transfer_flow_record.transfer_flow

    transfer_flow_record = AaveSentinelErc20TransferFlowRecord(
        contract_address=normalized_contract_address,
    )
    ledger_entry.erc20_transfer_flows.append(transfer_flow_record)
    return transfer_flow_record.transfer_flow


def apply_ledger_entry_block_metadata(
        ledger_entry: AaveSentinelUniversalLedgerEntry,
        block_number: int,
        timestamp_seconds: int,
) -> None:
    if block_number > 0 and ledger_entry.block_number == 0:
        ledger_entry.block_number = block_number
    if timestamp_seconds > 0 and ledger_entry.timestamp_seconds == 0:
        ledger_entry.timestamp_seconds = timestamp_seconds


def build_universal_ledger(
        wallet_address: str,
        normal_transactions: list[RoutescanNormalTransactionRecord],
        internal_transactions: list[RoutescanInternalTransactionRecord],
        token_transactions: list[RoutescanTokenTransactionRecord],
) -> AaveSentinelUniversalLedger:
    normalized_wallet_address: str = wallet_address.lower()
    universal_ledger = AaveSentinelUniversalLedger()

    for normal_transaction in normal_transactions:
        transaction_hash: str = normal_transaction.transaction_hash.lower()
        if not transaction_hash:
            continue

        ledger_entry = ensure_ledger_entry_for_transaction_hash(
            universal_ledger=universal_ledger,
            transaction_hash=transaction_hash,
        )
        apply_ledger_entry_block_metadata(
            ledger_entry=ledger_entry,
            block_number=int(normal_transaction.block_number),
            timestamp_seconds=int(normal_transaction.timestamp_seconds),
        )

        native_amount: float = int(normal_transaction.native_value_wei) / (10 ** 18)
        if normal_transaction.sender_address.lower() == normalized_wallet_address:
            ledger_entry.native_sent_amount += native_amount
            gas_used_amount: int = int(normal_transaction.gas_used or "0")
            gas_price_wei_amount: int = int(normal_transaction.gas_price_wei or "0")
            if gas_used_amount > 0 and gas_price_wei_amount > 0:
                ledger_entry.gas_fee_native_amount += (
                        gas_used_amount * gas_price_wei_amount / (10 ** 18)
                )
        if normal_transaction.recipient_address.lower() == normalized_wallet_address:
            ledger_entry.native_received_amount += native_amount

    for internal_transaction in internal_transactions:
        transaction_hash = internal_transaction.transaction_hash.lower()
        if not transaction_hash:
            continue

        ledger_entry = ensure_ledger_entry_for_transaction_hash(
            universal_ledger=universal_ledger,
            transaction_hash=transaction_hash,
        )
        apply_ledger_entry_block_metadata(
            ledger_entry=ledger_entry,
            block_number=int(internal_transaction.block_number),
            timestamp_seconds=int(internal_transaction.timestamp_seconds),
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

        ledger_entry = ensure_ledger_entry_for_transaction_hash(
            universal_ledger=universal_ledger,
            transaction_hash=transaction_hash,
        )
        apply_ledger_entry_block_metadata(
            ledger_entry=ledger_entry,
            block_number=int(token_transaction.block_number),
            timestamp_seconds=int(token_transaction.timestamp_seconds),
        )

        contract_address: str = token_transaction.contract_address.lower()
        decimal_count: int = int(token_transaction.token_decimal_count)
        token_amount: float = int(token_transaction.token_value_raw) / (10 ** decimal_count)

        transfer_flow = ensure_ledger_transfer_flow_for_contract(
            ledger_entry=ledger_entry,
            contract_address=contract_address,
        )

        if token_transaction.recipient_address.lower() == normalized_wallet_address:
            transfer_flow.incoming_amount += token_amount
        if token_transaction.sender_address.lower() == normalized_wallet_address:
            transfer_flow.outgoing_amount += token_amount

    return universal_ledger
