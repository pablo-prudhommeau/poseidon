from __future__ import annotations

import asyncio
from typing import Optional

from src.core.aavesentinel.aave_sentinel_constants import WAVAX_CONTRACT_ADDRESS
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelCapitalFlowValuationMemo,
    AaveSentinelForensicTimestampWindow,
    AaveSentinelIntervalForensicBreakdown,
    AaveSentinelPerformanceSummary,
    AaveSentinelPositionCheckpoint,
    AaveSentinelPositionSnapshot,
    AaveSentinelReserveIndexMemoEntry,
    AaveSentinelReserveIndexSnapshot,
    AaveSentinelReserveInterestBreakdown,
    AaveSentinelReserveRegistry,
    AaveSentinelReserveScaledBalanceState,
    AaveSentinelUniversalLedger,
    AaveSentinelUniversalLedgerEntry,
    AaveSentinelWalletTokenBalance,
)
from src.core.aavesentinel.aave_sentinel_utils import (
    compute_aave_net_worth_usd,
    compute_position_total_wallet_usd,
    compute_total_strategy_equity_usd,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import (
    resolve_aave_protocol_token_addresses,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_ledger_helpers import (
    build_universal_ledger,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_valuation_memo_helpers import (
    create_empty_capital_flow_valuation_memo,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_checkpoint_helpers import (
    build_position_checkpoint,
    create_empty_performance_summary,
    sum_net_external_capital_usd_in_timestamp_window,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_cycle_pnl_helpers import (
    compute_strategy_capital_deltas_usd,
    resolve_strategy_equities_usd_from_scaled_balances,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_forensic_helpers import (
    build_unallocated_wealth_movements_from_checkpoints,
    collect_conversion_contract_addresses_from_ledger_entry,
    compute_ledger_entry_conversion_pnl_usd,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_reserve_index_helpers import (
    fetch_reserve_index_snapshots,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_scaled_balance_helpers import (
    accrue_interest_between_indices,
    apply_protocol_token_transfers_to_scaled_balances,
    clone_scaled_balances,
    collect_sorted_aave_position_ledger_entries,
    collect_underlying_addresses_for_index_lookup,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_strategy_cycle_helpers import (
    aggregate_performance_summary,
    build_strategy_cycles_from_checkpoints,
    merge_interest_breakdowns,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_valuation_helpers import (
    resolve_asset_prices_usd_for_underlyings,
    resolve_forensic_asset_prices_usd,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_wallet_balance_helpers import (
    apply_reserve_underlying_wallet_transfers,
    build_asset_prices_usd,
    collect_wallet_underlying_addresses,
    compute_wallet_equity_usd,
)
from src.core.aavesentinel.position.aave_sentinel_position_reserve_registry_service import load_aave_sentinel_reserve_registry
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.aave.aave_protocol_reader import AaveProtocolReader
from src.integrations.aave.aave_structures import AaveScaledBalanceBatchRequest
from src.integrations.chainlink.chainlink_client import ChainlinkClient
from src.integrations.frankfurter.frankfurter_client import FrankfurterClient
from src.integrations.routescan.routescan_client import RoutescanClient
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelPerformanceService:
    def __init__(
            self,
            wallet_address: str,
            valuation_memo: Optional[AaveSentinelCapitalFlowValuationMemo] = None,
            aave_protocol_reader: Optional[AaveProtocolReader] = None,
    ) -> None:
        self._wallet_address: str = wallet_address.lower()
        self._routescan_client = RoutescanClient(wallet_address=self._wallet_address)
        self._aave_protocol_reader = aave_protocol_reader if aave_protocol_reader is not None else AaveProtocolReader()
        self._owns_aave_protocol_reader: bool = aave_protocol_reader is None
        self._chainlink_client = ChainlinkClient()
        self._frankfurter_client = FrankfurterClient()
        self._refresh_lock = asyncio.Lock()
        self._valuation_memo: AaveSentinelCapitalFlowValuationMemo = (
            valuation_memo if valuation_memo is not None else create_empty_capital_flow_valuation_memo()
        )
        self._reserve_registry: Optional[AaveSentinelReserveRegistry] = None
        self._reserve_index_memo_entries: list[AaveSentinelReserveIndexMemoEntry] = []

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    async def close(self) -> None:
        await self._routescan_client.close()
        if self._owns_aave_protocol_reader:
            await self._aave_protocol_reader.close()
        await self._chainlink_client.close()
        await self._frankfurter_client.close()

    async def build_performance_summary(
            self,
            capital_flow_summary: AaveSentinelCapitalFlowSummary,
            position_snapshot: Optional[AaveSentinelPositionSnapshot],
            universal_ledger: Optional[AaveSentinelUniversalLedger] = None,
    ) -> AaveSentinelPerformanceSummary:
        async with self._refresh_lock:
            return await self._build_performance_summary_without_lock(
                capital_flow_summary=capital_flow_summary,
                position_snapshot=position_snapshot,
                universal_ledger=universal_ledger,
            )

    async def _build_performance_summary_without_lock(
            self,
            capital_flow_summary: AaveSentinelCapitalFlowSummary,
            position_snapshot: Optional[AaveSentinelPositionSnapshot],
            universal_ledger: Optional[AaveSentinelUniversalLedger] = None,
    ) -> AaveSentinelPerformanceSummary:
        if not self._wallet_address:
            return create_empty_performance_summary()

        refresh_started_at = get_current_local_datetime()
        logger.debug(
            "[AAVESENTINEL][PERFORMANCE] Performance rebuild started for wallet %s",
            self._wallet_address,
        )

        if universal_ledger is None:
            normal_transactions = await self._routescan_client.fetch_all_normal_transactions()
            internal_transactions = await self._routescan_client.fetch_all_internal_transactions()
            token_transactions = await self._routescan_client.fetch_all_token_transactions()
            universal_ledger = build_universal_ledger(
                wallet_address=self._wallet_address,
                normal_transactions=normal_transactions,
                internal_transactions=internal_transactions,
                token_transactions=token_transactions,
            )
        reserve_registry = await self._resolve_reserve_registry()
        position_ledger_entries = collect_sorted_aave_position_ledger_entries(
            universal_ledger=universal_ledger,
            reserve_registry=reserve_registry,
        )

        scaled_balances: list[AaveSentinelReserveScaledBalanceState] = []
        previous_reserve_index_snapshots: list[AaveSentinelReserveIndexSnapshot] = []
        cumulative_supply_interest_usd: float = 0.0
        cumulative_borrow_interest_usd: float = 0.0
        cumulative_short_strategy_capital_usd: float = 0.0
        cumulative_long_strategy_capital_usd: float = 0.0
        interest_breakdown_batches: list[list[AaveSentinelReserveInterestBreakdown]] = []
        position_checkpoints: list[AaveSentinelPositionCheckpoint] = []
        wallet_token_balances: list[AaveSentinelWalletTokenBalance] = []
        sorted_universal_ledger_entries = sorted(
            universal_ledger.entries,
            key=lambda entry: (entry.block_number, entry.transaction_hash),
        )
        next_universal_ledger_entry_index: int = 0

        for ledger_entry in position_ledger_entries:
            while next_universal_ledger_entry_index < len(sorted_universal_ledger_entries):
                universal_ledger_entry = sorted_universal_ledger_entries[next_universal_ledger_entry_index]
                if (
                        universal_ledger_entry.block_number > ledger_entry.block_number
                        or (
                        universal_ledger_entry.block_number == ledger_entry.block_number
                        and universal_ledger_entry.transaction_hash > ledger_entry.transaction_hash
                )
                ):
                    break
                apply_reserve_underlying_wallet_transfers(
                    ledger_entry=universal_ledger_entry,
                    reserve_registry=reserve_registry,
                    wallet_token_balances=wallet_token_balances,
                )
                next_universal_ledger_entry_index += 1

            underlying_addresses = collect_underlying_addresses_for_index_lookup(
                scaled_balances=scaled_balances,
                ledger_entry=ledger_entry,
                reserve_registry=reserve_registry,
            )
            wallet_underlying_addresses = collect_wallet_underlying_addresses(
                wallet_token_balances=wallet_token_balances,
            )
            priced_underlying_addresses: list[str] = sorted(
                set(underlying_addresses) | set(wallet_underlying_addresses)
            )
            next_reserve_index_snapshots = await fetch_reserve_index_snapshots(
                aave_protocol_reader=self._aave_protocol_reader,
                reserve_index_memo_entries=self._reserve_index_memo_entries,
                block_number=ledger_entry.block_number,
                underlying_addresses=underlying_addresses,
            )
            asset_price_usd_by_underlying = await resolve_asset_prices_usd_for_underlyings(
                aave_protocol_reader=self._aave_protocol_reader,
                chainlink_client=self._chainlink_client,
                frankfurter_client=self._frankfurter_client,
                valuation_memo=self._valuation_memo,
                block_number=ledger_entry.block_number,
                timestamp_seconds=ledger_entry.timestamp_seconds,
                underlying_addresses=priced_underlying_addresses,
                reserve_registry=reserve_registry,
            )

            previous_scaled_balances_for_capital = clone_scaled_balances(scaled_balances)
            capital_previous_reserve_index_snapshots = (
                previous_reserve_index_snapshots
                if previous_reserve_index_snapshots
                else next_reserve_index_snapshots
            )

            if previous_reserve_index_snapshots:
                period_supply_interest_usd, period_borrow_interest_usd, period_interest_breakdowns = (
                    accrue_interest_between_indices(
                        previous_scaled_balances=scaled_balances,
                        previous_reserve_index_snapshots=previous_reserve_index_snapshots,
                        next_reserve_index_snapshots=next_reserve_index_snapshots,
                        asset_price_usd_by_underlying=asset_price_usd_by_underlying,
                        reserve_registry=reserve_registry,
                    )
                )
                cumulative_supply_interest_usd += period_supply_interest_usd
                cumulative_borrow_interest_usd += period_borrow_interest_usd
                interest_breakdown_batches.append(period_interest_breakdowns)

            before_transfer_short_strategy_equity_usd, before_transfer_long_strategy_equity_usd = (
                resolve_strategy_equities_usd_from_scaled_balances(
                    scaled_balances=scaled_balances,
                    reserve_index_snapshots=next_reserve_index_snapshots,
                    asset_price_usd_by_underlying=asset_price_usd_by_underlying,
                    reserve_registry=reserve_registry,
                )
            )

            apply_protocol_token_transfers_to_scaled_balances(
                ledger_entry=ledger_entry,
                reserve_registry=reserve_registry,
                scaled_balances=scaled_balances,
                reserve_index_snapshots=next_reserve_index_snapshots,
            )
            reconciled_event_scaled_balances = await self._fetch_live_scaled_balances(
                reserve_registry=reserve_registry,
                underlying_addresses=underlying_addresses,
                block_number=ledger_entry.block_number,
            )
            if reconciled_event_scaled_balances is not None:
                scaled_balances = self._replace_scaled_balances_for_underlyings(
                    existing_scaled_balances=scaled_balances,
                    reconciled_scaled_balances=reconciled_event_scaled_balances,
                    underlying_addresses=underlying_addresses,
                )

            short_strategy_capital_delta_usd, long_strategy_capital_delta_usd = (
                compute_strategy_capital_deltas_usd(
                    previous_scaled_balances=previous_scaled_balances_for_capital,
                    next_scaled_balances=scaled_balances,
                    previous_reserve_index_snapshots=capital_previous_reserve_index_snapshots,
                    next_reserve_index_snapshots=next_reserve_index_snapshots,
                    asset_price_usd_by_underlying=asset_price_usd_by_underlying,
                    reserve_registry=reserve_registry,
                )
            )
            cumulative_short_strategy_capital_usd += short_strategy_capital_delta_usd
            cumulative_long_strategy_capital_usd += long_strategy_capital_delta_usd

            wallet_equity_usd = compute_wallet_equity_usd(
                wallet_token_balances=wallet_token_balances,
                asset_prices_usd=build_asset_prices_usd(
                    asset_price_usd_by_underlying=asset_price_usd_by_underlying,
                ),
                reserve_registry=reserve_registry,
            )
            cumulative_external_capital_usd = sum_net_external_capital_usd_in_timestamp_window(
                classified_flows=capital_flow_summary.classified_flows,
                window_start_timestamp_seconds=0,
                window_end_timestamp_seconds=ledger_entry.timestamp_seconds,
            )
            position_checkpoints.append(
                build_position_checkpoint(
                    block_number=ledger_entry.block_number,
                    timestamp_seconds=ledger_entry.timestamp_seconds,
                    scaled_balances=clone_scaled_balances(scaled_balances),
                    reserve_index_snapshots=next_reserve_index_snapshots,
                    asset_price_usd_by_underlying=asset_price_usd_by_underlying,
                    reserve_registry=reserve_registry,
                    cumulative_supply_interest_usd=cumulative_supply_interest_usd,
                    cumulative_borrow_interest_usd=cumulative_borrow_interest_usd,
                    cumulative_short_strategy_capital_usd=cumulative_short_strategy_capital_usd,
                    cumulative_long_strategy_capital_usd=cumulative_long_strategy_capital_usd,
                    before_transfer_short_strategy_equity_usd=before_transfer_short_strategy_equity_usd,
                    before_transfer_long_strategy_equity_usd=before_transfer_long_strategy_equity_usd,
                    wallet_equity_usd=wallet_equity_usd,
                    cumulative_external_capital_usd=cumulative_external_capital_usd,
                    wallet_token_balances=wallet_token_balances,
                )
            )
            previous_reserve_index_snapshots = next_reserve_index_snapshots

        latest_block_number = await self._fetch_latest_block_number()
        latest_timestamp_seconds = int(get_current_local_datetime().timestamp())
        if scaled_balances or position_ledger_entries:
            while next_universal_ledger_entry_index < len(sorted_universal_ledger_entries):
                apply_reserve_underlying_wallet_transfers(
                    ledger_entry=sorted_universal_ledger_entries[next_universal_ledger_entry_index],
                    reserve_registry=reserve_registry,
                    wallet_token_balances=wallet_token_balances,
                )
                next_universal_ledger_entry_index += 1

            underlying_addresses = collect_underlying_addresses_for_index_lookup(
                scaled_balances=scaled_balances,
                ledger_entry=None,
                reserve_registry=reserve_registry,
            )
            if not underlying_addresses:
                underlying_addresses = [
                    reserve_asset.underlying_address
                    for reserve_asset in reserve_registry.reserve_assets
                ]
            wallet_underlying_addresses = collect_wallet_underlying_addresses(
                wallet_token_balances=wallet_token_balances,
            )
            priced_underlying_addresses = sorted(
                set(underlying_addresses) | set(wallet_underlying_addresses)
            )

            pre_reconciliation_scaled_balances = clone_scaled_balances(scaled_balances)
            latest_reserve_index_snapshots = await fetch_reserve_index_snapshots(
                aave_protocol_reader=self._aave_protocol_reader,
                reserve_index_memo_entries=self._reserve_index_memo_entries,
                block_number=latest_block_number,
                underlying_addresses=underlying_addresses,
            )
            latest_asset_price_usd_by_underlying = await resolve_asset_prices_usd_for_underlyings(
                aave_protocol_reader=self._aave_protocol_reader,
                chainlink_client=self._chainlink_client,
                frankfurter_client=self._frankfurter_client,
                valuation_memo=self._valuation_memo,
                block_number=latest_block_number,
                timestamp_seconds=latest_timestamp_seconds,
                underlying_addresses=priced_underlying_addresses,
                reserve_registry=reserve_registry,
            )
            if previous_reserve_index_snapshots and pre_reconciliation_scaled_balances:
                period_supply_interest_usd, period_borrow_interest_usd, period_interest_breakdowns = (
                    accrue_interest_between_indices(
                        previous_scaled_balances=pre_reconciliation_scaled_balances,
                        previous_reserve_index_snapshots=previous_reserve_index_snapshots,
                        next_reserve_index_snapshots=latest_reserve_index_snapshots,
                        asset_price_usd_by_underlying=latest_asset_price_usd_by_underlying,
                        reserve_registry=reserve_registry,
                    )
                )
                cumulative_supply_interest_usd += period_supply_interest_usd
                cumulative_borrow_interest_usd += period_borrow_interest_usd
                interest_breakdown_batches.append(period_interest_breakdowns)

            reconciled_scaled_balances = await self._fetch_live_scaled_balances(
                reserve_registry=reserve_registry,
                underlying_addresses=underlying_addresses,
                block_number=latest_block_number,
            )
            final_scaled_balances = pre_reconciliation_scaled_balances
            if reconciled_scaled_balances is not None:
                final_scaled_balances = self._replace_scaled_balances_for_underlyings(
                    existing_scaled_balances=pre_reconciliation_scaled_balances,
                    reconciled_scaled_balances=reconciled_scaled_balances,
                    underlying_addresses=underlying_addresses,
                )

            capital_previous_reserve_index_snapshots = (
                previous_reserve_index_snapshots
                if previous_reserve_index_snapshots
                else latest_reserve_index_snapshots
            )
            short_strategy_capital_delta_usd, long_strategy_capital_delta_usd = (
                compute_strategy_capital_deltas_usd(
                    previous_scaled_balances=pre_reconciliation_scaled_balances,
                    next_scaled_balances=final_scaled_balances,
                    previous_reserve_index_snapshots=capital_previous_reserve_index_snapshots,
                    next_reserve_index_snapshots=latest_reserve_index_snapshots,
                    asset_price_usd_by_underlying=latest_asset_price_usd_by_underlying,
                    reserve_registry=reserve_registry,
                )
            )
            cumulative_short_strategy_capital_usd += short_strategy_capital_delta_usd
            cumulative_long_strategy_capital_usd += long_strategy_capital_delta_usd

            latest_wallet_equity_usd = compute_wallet_equity_usd(
                wallet_token_balances=wallet_token_balances,
                asset_prices_usd=build_asset_prices_usd(
                    asset_price_usd_by_underlying=latest_asset_price_usd_by_underlying,
                ),
                reserve_registry=reserve_registry,
            )
            position_checkpoints.append(
                build_position_checkpoint(
                    block_number=latest_block_number,
                    timestamp_seconds=latest_timestamp_seconds,
                    scaled_balances=clone_scaled_balances(final_scaled_balances),
                    reserve_index_snapshots=latest_reserve_index_snapshots,
                    asset_price_usd_by_underlying=latest_asset_price_usd_by_underlying,
                    reserve_registry=reserve_registry,
                    cumulative_supply_interest_usd=cumulative_supply_interest_usd,
                    cumulative_borrow_interest_usd=cumulative_borrow_interest_usd,
                    cumulative_short_strategy_capital_usd=cumulative_short_strategy_capital_usd,
                    cumulative_long_strategy_capital_usd=cumulative_long_strategy_capital_usd,
                    wallet_equity_usd=latest_wallet_equity_usd,
                    cumulative_external_capital_usd=capital_flow_summary.net_capital_deployed_usd,
                    wallet_token_balances=wallet_token_balances,
                )
            )

        if position_snapshot is not None and position_checkpoints:
            latest_position_checkpoint = position_checkpoints[-1]
            latest_position_checkpoint.equity_usd = compute_aave_net_worth_usd(
                total_collateral_usd=position_snapshot.total_collateral_usd,
                total_debt_usd=position_snapshot.total_debt_usd,
            )
            latest_position_checkpoint.wallet_equity_usd = compute_position_total_wallet_usd(
                assets=position_snapshot.assets,
            )
            latest_position_checkpoint.cumulative_external_capital_usd = (
                capital_flow_summary.net_capital_deployed_usd
            )

        strategy_cycles = build_strategy_cycles_from_checkpoints(
            position_checkpoints=position_checkpoints,
            reserve_registry=reserve_registry,
        )
        interval_forensic_breakdowns = await self._build_interval_forensic_breakdowns(
            position_checkpoints=position_checkpoints,
            universal_ledger=universal_ledger,
            reserve_registry=reserve_registry,
        )
        unallocated_wealth_movements = build_unallocated_wealth_movements_from_checkpoints(
            position_checkpoints=position_checkpoints,
            interval_forensic_breakdowns=interval_forensic_breakdowns,
            strategy_cycles=strategy_cycles,
            reserve_registry=reserve_registry,
        )
        interest_breakdowns = merge_interest_breakdowns(
            interest_breakdown_batches=interest_breakdown_batches,
        )

        total_equity_usd = 0.0
        if position_snapshot is not None:
            total_equity_usd = compute_total_strategy_equity_usd(
                total_collateral_usd=position_snapshot.total_collateral_usd,
                total_debt_usd=position_snapshot.total_debt_usd,
                assets=position_snapshot.assets,
            )
        elif position_checkpoints:
            total_equity_usd = (
                    position_checkpoints[-1].equity_usd
                    + position_checkpoints[-1].wallet_equity_usd
            )

        performance_summary = aggregate_performance_summary(
            strategy_cycles=strategy_cycles,
            interest_breakdowns=interest_breakdowns,
            total_equity_usd=total_equity_usd,
            net_capital_deployed_usd=capital_flow_summary.net_capital_deployed_usd,
            unallocated_wealth_movements=unallocated_wealth_movements,
        )
        performance_summary.refreshed_at = refresh_started_at

        refresh_duration_seconds = (get_current_local_datetime() - refresh_started_at).total_seconds()
        logger.info(
            "[AAVESENTINEL][PERFORMANCE] Performance rebuild completed in %0.2fs "
            "realized_trading_usd=%0.2f latent_trading_usd=%0.2f net_interest_usd=%0.2f "
            "cycle_count=%d hors_trading_pnl_usd=%0.2f pnl_reconciliation_gap_usd=%0.2f "
            "checkpoint_count=%d",
            refresh_duration_seconds,
            performance_summary.realized_trading_pnl_usd,
            performance_summary.latent_trading_pnl_usd,
            performance_summary.cumulative_net_interest_usd,
            len(performance_summary.strategy_cycles),
            performance_summary.unallocated_wealth_pnl_usd,
            performance_summary.pnl_reconciliation_gap_usd,
            len(position_checkpoints),
        )
        for strategy_cycle in performance_summary.strategy_cycles:
            logger.debug(
                "[AAVESENTINEL][PERFORMANCE][CYCLE] kind=%s asset=%s opened_at=%d closed_at=%s "
                "gross_pnl_usd=%0.2f absorbed_breakdown_count=%d",
                strategy_cycle.kind.value,
                strategy_cycle.main_asset_symbol,
                strategy_cycle.opened_at_timestamp_seconds,
                strategy_cycle.closed_at_timestamp_seconds,
                strategy_cycle.gross_pnl_usd,
                len(strategy_cycle.absorbed_source_breakdowns),
            )
        for unallocated_wealth_movement in performance_summary.unallocated_wealth_movements:
            logger.debug(
                "[AAVESENTINEL][PERFORMANCE][HORS_TRADING] source=%s started_at=%d ended_at=%d "
                "pnl_usd=%0.2f dominant_asset=%s",
                unallocated_wealth_movement.source.value,
                unallocated_wealth_movement.started_at_timestamp_seconds,
                unallocated_wealth_movement.ended_at_timestamp_seconds,
                unallocated_wealth_movement.pnl_usd,
                unallocated_wealth_movement.dominant_asset_symbol,
            )
        return performance_summary

    async def _build_interval_forensic_breakdowns(
            self,
            position_checkpoints: list[AaveSentinelPositionCheckpoint],
            universal_ledger: AaveSentinelUniversalLedger,
            reserve_registry: AaveSentinelReserveRegistry,
    ) -> list[AaveSentinelIntervalForensicBreakdown]:
        if not position_checkpoints:
            return []

        aave_protocol_token_addresses = resolve_aave_protocol_token_addresses(
            reserve_registry=reserve_registry,
        )
        sorted_ledger_entries = sorted(
            universal_ledger.entries,
            key=lambda ledger_entry: (
                ledger_entry.timestamp_seconds,
                ledger_entry.block_number,
                ledger_entry.transaction_hash,
            ),
        )
        forensic_windows: list[AaveSentinelForensicTimestampWindow] = [
            AaveSentinelForensicTimestampWindow(
                started_at_timestamp_seconds=0,
                ended_at_timestamp_seconds=position_checkpoints[0].timestamp_seconds,
            ),
        ]
        for checkpoint_index in range(1, len(position_checkpoints)):
            forensic_windows.append(
                AaveSentinelForensicTimestampWindow(
                    started_at_timestamp_seconds=position_checkpoints[
                        checkpoint_index - 1
                        ].timestamp_seconds,
                    ended_at_timestamp_seconds=position_checkpoints[
                        checkpoint_index
                    ].timestamp_seconds,
                )
            )

        interval_forensic_breakdowns: list[AaveSentinelIntervalForensicBreakdown] = []
        for forensic_window in forensic_windows:
            window_start_timestamp_seconds = forensic_window.started_at_timestamp_seconds
            window_end_timestamp_seconds = forensic_window.ended_at_timestamp_seconds
            window_ledger_entries = self._collect_ledger_entries_in_timestamp_window(
                ledger_entries=sorted_ledger_entries,
                window_start_timestamp_seconds=window_start_timestamp_seconds,
                window_end_timestamp_seconds=window_end_timestamp_seconds,
                include_start_boundary=window_start_timestamp_seconds == 0,
            )
            gas_fee_usd = 0.0
            conversion_pnl_usd = 0.0
            for ledger_entry in window_ledger_entries:
                priced_contract_addresses: list[str] = [WAVAX_CONTRACT_ADDRESS]
                priced_contract_addresses.extend(
                    collect_conversion_contract_addresses_from_ledger_entry(
                        ledger_entry=ledger_entry,
                        aave_protocol_token_addresses=aave_protocol_token_addresses,
                    )
                )
                asset_price_usd_by_contract = await resolve_forensic_asset_prices_usd(
                    aave_protocol_reader=self._aave_protocol_reader,
                    chainlink_client=self._chainlink_client,
                    frankfurter_client=self._frankfurter_client,
                    valuation_memo=self._valuation_memo,
                    block_number=ledger_entry.block_number,
                    timestamp_seconds=ledger_entry.timestamp_seconds,
                    contract_addresses=sorted(set(priced_contract_addresses)),
                    reserve_registry=reserve_registry,
                )
                wavax_price_usd = asset_price_usd_by_contract.get(WAVAX_CONTRACT_ADDRESS.lower())
                if wavax_price_usd is not None and ledger_entry.gas_fee_native_amount > 0:
                    gas_fee_usd += ledger_entry.gas_fee_native_amount * wavax_price_usd
                conversion_pnl_usd += compute_ledger_entry_conversion_pnl_usd(
                    ledger_entry=ledger_entry,
                    asset_price_usd_by_contract=asset_price_usd_by_contract,
                    aave_protocol_token_addresses=aave_protocol_token_addresses,
                )
            interval_forensic_breakdowns.append(
                AaveSentinelIntervalForensicBreakdown(
                    window_start_timestamp_seconds=window_start_timestamp_seconds,
                    window_end_timestamp_seconds=window_end_timestamp_seconds,
                    gas_fee_usd=gas_fee_usd,
                    conversion_pnl_usd=conversion_pnl_usd,
                )
            )
        return interval_forensic_breakdowns

    def _collect_ledger_entries_in_timestamp_window(
            self,
            ledger_entries: list[AaveSentinelUniversalLedgerEntry],
            window_start_timestamp_seconds: int,
            window_end_timestamp_seconds: int,
            include_start_boundary: bool,
    ) -> list[AaveSentinelUniversalLedgerEntry]:
        matching_ledger_entries: list[AaveSentinelUniversalLedgerEntry] = []
        for ledger_entry in ledger_entries:
            if ledger_entry.timestamp_seconds > window_end_timestamp_seconds:
                continue
            if include_start_boundary:
                if ledger_entry.timestamp_seconds > window_end_timestamp_seconds:
                    continue
            elif ledger_entry.timestamp_seconds <= window_start_timestamp_seconds:
                continue
            matching_ledger_entries.append(ledger_entry)
        return matching_ledger_entries

    def _replace_scaled_balances_for_underlyings(
            self,
            existing_scaled_balances: list[AaveSentinelReserveScaledBalanceState],
            reconciled_scaled_balances: list[AaveSentinelReserveScaledBalanceState],
            underlying_addresses: list[str],
    ) -> list[AaveSentinelReserveScaledBalanceState]:
        normalized_underlying_addresses = {address.lower() for address in underlying_addresses}
        retained_scaled_balances: list[AaveSentinelReserveScaledBalanceState] = [
            AaveSentinelReserveScaledBalanceState(
                underlying_address=scaled_balance.underlying_address,
                scaled_supply_balance=scaled_balance.scaled_supply_balance,
                scaled_debt_balance=scaled_balance.scaled_debt_balance,
            )
            for scaled_balance in existing_scaled_balances
            if scaled_balance.underlying_address not in normalized_underlying_addresses
        ]
        for reconciled_scaled_balance in reconciled_scaled_balances:
            retained_scaled_balances.append(
                AaveSentinelReserveScaledBalanceState(
                    underlying_address=reconciled_scaled_balance.underlying_address,
                    scaled_supply_balance=reconciled_scaled_balance.scaled_supply_balance,
                    scaled_debt_balance=reconciled_scaled_balance.scaled_debt_balance,
                )
            )
        return retained_scaled_balances

    async def _fetch_live_scaled_balances(
            self,
            reserve_registry: AaveSentinelReserveRegistry,
            underlying_addresses: list[str],
            block_number: int,
    ) -> Optional[list[AaveSentinelReserveScaledBalanceState]]:
        scaled_balances: list[AaveSentinelReserveScaledBalanceState] = []
        underlying_address_set = {address.lower() for address in underlying_addresses}
        scaled_balance_batch_requests: list[AaveScaledBalanceBatchRequest] = []
        for reserve_asset in reserve_registry.reserve_assets:
            if reserve_asset.underlying_address not in underlying_address_set:
                continue
            scaled_balance_batch_requests.append(
                AaveScaledBalanceBatchRequest(
                    underlying_address=reserve_asset.underlying_address,
                    a_token_address=reserve_asset.a_token_address,
                    variable_debt_token_address=reserve_asset.variable_debt_token_address,
                    decimal_count=reserve_asset.decimal_count,
                )
            )
        if len(scaled_balance_batch_requests) == 0:
            return scaled_balances

        scaled_balance_snapshots = await self._aave_protocol_reader.fetch_scaled_balances_at_block_batch(
            wallet_address=self._wallet_address,
            scaled_balance_batch_requests=scaled_balance_batch_requests,
            block_number=block_number,
        )
        if len(scaled_balance_snapshots) == 0:
            return None

        for scaled_balance_batch_request in scaled_balance_batch_requests:
            scaled_balance_snapshot = None
            normalized_underlying_address = scaled_balance_batch_request.underlying_address.lower()
            for candidate_scaled_balance_snapshot in scaled_balance_snapshots:
                if candidate_scaled_balance_snapshot.underlying_address == normalized_underlying_address:
                    scaled_balance_snapshot = candidate_scaled_balance_snapshot
                    break
            if scaled_balance_snapshot is None:
                continue
            if (
                    scaled_balance_snapshot.scaled_supply_balance == 0
                    and scaled_balance_snapshot.scaled_debt_balance == 0
            ):
                continue
            scaled_balances.append(
                AaveSentinelReserveScaledBalanceState(
                    underlying_address=scaled_balance_snapshot.underlying_address,
                    scaled_supply_balance=scaled_balance_snapshot.scaled_supply_balance,
                    scaled_debt_balance=scaled_balance_snapshot.scaled_debt_balance,
                )
            )
        return scaled_balances

    async def _resolve_reserve_registry(self) -> AaveSentinelReserveRegistry:
        if self._reserve_registry is None:
            self._reserve_registry = await load_aave_sentinel_reserve_registry()
        return self._reserve_registry

    async def _fetch_latest_block_number(self) -> int:
        return await self._aave_protocol_reader.fetch_latest_block_number()
