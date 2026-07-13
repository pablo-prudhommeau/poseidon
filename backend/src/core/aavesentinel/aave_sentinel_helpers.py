from __future__ import annotations

from typing import Optional, Protocol

from src.core.aavesentinel.aave_sentinel_constants import (
    EURO_STABLECOIN_SYMBOLS,
    NATIVE_AVAX_ASSET_SYMBOL,
    PURE_FLOW_AMOUNT_EPSILON,
    USD_FIAT_STABLECOIN_SYMBOLS,
    WAVAX_CONTRACT_ADDRESS,
)
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAssetFlowTotals,
    AaveSentinelAssetSnapshot,
    AaveSentinelCapitalFlowDirection,
    AaveSentinelCapitalFlowSummary,
    AaveSentinelCapitalFlowValuationContext,
    AaveSentinelCapitalFlowValuationMemo,
    AaveSentinelClassifiedCapitalFlow,
    AaveSentinelBlockExchangeRateMemoEntry,
    AaveSentinelBlockTimestampMemoEntry,
    AaveSentinelDateExchangeRateMemoEntry,
    AaveSentinelErc20TransferFlow,
    AaveSentinelErc20TransferFlowRecord,
    AaveSentinelHistoricalAssetPriceLookupKey,
    AaveSentinelHistoricalAssetPriceMemoEntry,
    AaveSentinelRawCapitalFlowEvent,
    AaveSentinelReserveAsset,
    AaveSentinelReserveRegistry,
    AaveSentinelStrategyDirection,
    AaveSentinelStrategySnapshotResolution,
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
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.routescan.routescan_structures import (
    RoutescanInternalTransactionRecord,
    RoutescanNormalTransactionRecord,
    RoutescanTokenTransactionRecord,
)

EMPTY_AAVE_SENTINEL_RESERVE_REGISTRY = AaveSentinelReserveRegistry()


def requires_euro_conversion_for_symbol(asset_symbol: str) -> bool:
    return asset_symbol.strip().upper() in EURO_STABLECOIN_SYMBOLS


def is_fiat_stablecoin_symbol(asset_symbol: str) -> bool:
    normalized_symbol = asset_symbol.strip().upper()
    return (
        normalized_symbol in EURO_STABLECOIN_SYMBOLS
        or normalized_symbol in USD_FIAT_STABLECOIN_SYMBOLS
    )


class AaveSentinelCapitalFlowUsdValuationResolver(Protocol):
    def resolve_amount_usd(self, valuation_context: AaveSentinelCapitalFlowValuationContext) -> float:
        ...


def create_empty_capital_flow_summary() -> AaveSentinelCapitalFlowSummary:
    return AaveSentinelCapitalFlowSummary(
        is_available=False,
        refreshed_at=get_current_local_datetime(),
    )


def create_empty_capital_flow_valuation_memo() -> AaveSentinelCapitalFlowValuationMemo:
    return AaveSentinelCapitalFlowValuationMemo()


def resolve_valuation_memo_block_exchange_rate(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
) -> Optional[float]:
    for memo_entry in valuation_memo.block_exchange_rates:
        if memo_entry.block_number == block_number:
            return memo_entry.exchange_rate
    return None


def resolve_valuation_memo_date_exchange_rate(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        exchange_rate_date: str,
) -> Optional[float]:
    for memo_entry in valuation_memo.date_exchange_rates:
        if memo_entry.exchange_rate_date == exchange_rate_date:
            return memo_entry.exchange_rate
    return None


def resolve_valuation_memo_historical_asset_price_usd(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        lookup_key: AaveSentinelHistoricalAssetPriceLookupKey,
) -> Optional[float]:
    for memo_entry in valuation_memo.historical_asset_prices:
        if memo_entry.lookup_key == lookup_key:
            return memo_entry.asset_price_usd
    return None


def resolve_valuation_memo_block_timestamp_seconds(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
) -> Optional[int]:
    for memo_entry in valuation_memo.block_timestamps:
        if memo_entry.block_number == block_number:
            return memo_entry.timestamp_seconds
    return None


def remember_valuation_memo_block_exchange_rate(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        exchange_rate: float,
) -> None:
    if resolve_valuation_memo_block_exchange_rate(
            valuation_memo=valuation_memo,
            block_number=block_number,
    ) is not None:
        return
    valuation_memo.block_exchange_rates.append(
        AaveSentinelBlockExchangeRateMemoEntry(
            block_number=block_number,
            exchange_rate=exchange_rate,
        )
    )


def remember_valuation_memo_date_exchange_rate(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        exchange_rate_date: str,
        exchange_rate: float,
) -> None:
    if resolve_valuation_memo_date_exchange_rate(
            valuation_memo=valuation_memo,
            exchange_rate_date=exchange_rate_date,
    ) is not None:
        return
    valuation_memo.date_exchange_rates.append(
        AaveSentinelDateExchangeRateMemoEntry(
            exchange_rate_date=exchange_rate_date,
            exchange_rate=exchange_rate,
        )
    )


def remember_valuation_memo_historical_asset_price_usd(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        lookup_key: AaveSentinelHistoricalAssetPriceLookupKey,
        asset_price_usd: float,
) -> None:
    if resolve_valuation_memo_historical_asset_price_usd(
            valuation_memo=valuation_memo,
            lookup_key=lookup_key,
    ) is not None:
        return
    valuation_memo.historical_asset_prices.append(
        AaveSentinelHistoricalAssetPriceMemoEntry(
            lookup_key=lookup_key,
            asset_price_usd=asset_price_usd,
        )
    )


def remember_valuation_memo_block_timestamp_seconds(
        valuation_memo: AaveSentinelCapitalFlowValuationMemo,
        block_number: int,
        timestamp_seconds: int,
) -> None:
    if resolve_valuation_memo_block_timestamp_seconds(
            valuation_memo=valuation_memo,
            block_number=block_number,
    ) is not None:
        return
    valuation_memo.block_timestamps.append(
        AaveSentinelBlockTimestampMemoEntry(
            block_number=block_number,
            timestamp_seconds=timestamp_seconds,
        )
    )


def build_historical_asset_price_lookup_key(
        block_number: int,
        contract_address: str,
) -> AaveSentinelHistoricalAssetPriceLookupKey:
    return AaveSentinelHistoricalAssetPriceLookupKey(
        block_number=block_number,
        contract_address=contract_address.lower(),
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
        contract_address: str,
) -> AaveSentinelReserveAsset | None:
    normalized_contract_address: str = contract_address.lower()
    for reserve_asset in reserve_registry.reserve_assets:
        if reserve_asset.underlying_address == normalized_contract_address:
            return reserve_asset
    return None


def resolve_asset_symbol_for_contract(
        reserve_registry: AaveSentinelReserveRegistry,
        contract_address: str,
) -> str:
    reserve_asset = resolve_reserve_asset_for_underlying(
        reserve_registry=reserve_registry,
        contract_address=contract_address,
    )
    if reserve_asset is not None:
        return reserve_asset.symbol
    return contract_address.lower()


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
        if abs(net_native_amount) >= PURE_FLOW_AMOUNT_EPSILON:
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
            if abs(net_flow_amount) < PURE_FLOW_AMOUNT_EPSILON:
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


def resolve_strategy_snapshot_resolution(
        detected_assets: list[AaveSentinelAssetSnapshot],
        current_health_factor: float,
        reserve_registry: AaveSentinelReserveRegistry,
) -> AaveSentinelStrategySnapshotResolution:
    aggregate_supply_value_usd = sum(asset.supply_value_usd for asset in detected_assets)
    aggregate_debt_value_usd = sum(asset.debt_value_usd for asset in detected_assets)

    if aggregate_supply_value_usd == 0 or aggregate_debt_value_usd == 0:
        return AaveSentinelStrategySnapshotResolution()

    stablecoin_symbols = resolve_stablecoin_symbols(reserve_registry=reserve_registry)
    stablecoin_debt_value_usd = sum(
        asset.debt_value_usd
        for asset in detected_assets
        if asset.symbol in stablecoin_symbols
    )
    volatile_asset_debt_value_usd = aggregate_debt_value_usd - stablecoin_debt_value_usd
    is_long_biased_strategy = stablecoin_debt_value_usd > volatile_asset_debt_value_usd
    strategy_direction = (
        AaveSentinelStrategyDirection.LONG
        if is_long_biased_strategy
        else AaveSentinelStrategyDirection.SHORT
    )

    if is_long_biased_strategy:
        eligible_assets = [
            asset
            for asset in detected_assets
            if asset.symbol not in stablecoin_symbols and asset.supply_value_usd > 0
        ]
        if not eligible_assets:
            return AaveSentinelStrategySnapshotResolution()

        main_asset = max(eligible_assets, key=lambda asset_snapshot: asset_snapshot.supply_value_usd)
        if main_asset.supply_amount == 0:
            return AaveSentinelStrategySnapshotResolution(
                strategy_direction=strategy_direction,
                main_asset_symbol=main_asset.symbol,
                main_asset_price_usd=0.0,
                liquidation_price_usd=0.0,
            )

        current_price_usd = main_asset.supply_value_usd / main_asset.supply_amount
        liquidation_price_usd = current_price_usd / current_health_factor if current_health_factor > 0 else 0.0
        return AaveSentinelStrategySnapshotResolution(
            strategy_direction=strategy_direction,
            main_asset_symbol=main_asset.symbol,
            main_asset_price_usd=current_price_usd,
            liquidation_price_usd=liquidation_price_usd,
        )

    eligible_assets = [
        asset
        for asset in detected_assets
        if asset.symbol not in stablecoin_symbols and asset.debt_value_usd > 0
    ]
    if not eligible_assets:
        return AaveSentinelStrategySnapshotResolution()

    main_asset = max(eligible_assets, key=lambda asset_snapshot: asset_snapshot.debt_value_usd)
    if main_asset.debt_amount == 0:
        return AaveSentinelStrategySnapshotResolution(
            strategy_direction=strategy_direction,
            main_asset_symbol=main_asset.symbol,
            main_asset_price_usd=0.0,
            liquidation_price_usd=0.0,
        )

    current_price_usd = main_asset.debt_value_usd / main_asset.debt_amount
    liquidation_price_usd = current_price_usd * current_health_factor
    return AaveSentinelStrategySnapshotResolution(
        strategy_direction=strategy_direction,
        main_asset_symbol=main_asset.symbol,
        main_asset_price_usd=current_price_usd,
        liquidation_price_usd=liquidation_price_usd,
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
            contract_address=contract_address,
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
