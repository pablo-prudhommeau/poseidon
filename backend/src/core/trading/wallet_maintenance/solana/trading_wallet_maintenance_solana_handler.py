from __future__ import annotations

from typing import Optional

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.wallet_maintenance.solana.trading_wallet_maintenance_solana_gas_budget_service import (
    build_solana_gas_budget_snapshot,
)
from src.core.trading.wallet_maintenance.solana.trading_wallet_maintenance_solana_gas_refill_service import (
    run_solana_native_gas_refill,
)
from src.core.trading.wallet_maintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service import (
    run_solana_dormant_token_account_reclaim,
)
from src.core.trading.wallet_maintenance.trading_wallet_maintenance_structures import (
    TradingNativeGasThresholdSnapshot,
    TradingWalletMaintenanceChainGasResult,
    TradingWalletMaintenanceChainReclaimResult,
)


class TradingWalletMaintenanceSolanaHandler:
    def blockchain_network(self) -> BlockchainNetwork:
        return BlockchainNetwork.SOLANA

    def run_native_gas_maintenance(self) -> TradingWalletMaintenanceChainGasResult:
        return run_solana_native_gas_refill()

    def run_dormant_account_reclaim(self) -> TradingWalletMaintenanceChainReclaimResult:
        return run_solana_dormant_token_account_reclaim()

    def resolve_native_gas_threshold_for_buy_guard(self) -> Optional[TradingNativeGasThresholdSnapshot]:
        budget_snapshot = build_solana_gas_budget_snapshot()
        return TradingNativeGasThresholdSnapshot(
            blockchain_network=BlockchainNetwork.SOLANA,
            threshold_raw_lamports=budget_snapshot.refill_threshold_lamports,
            target_raw_lamports=budget_snapshot.refill_target_lamports,
            native_token_symbol="SOL",
        )
