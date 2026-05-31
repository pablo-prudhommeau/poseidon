from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_gas_refill_service import (
    run_solana_native_gas_refill,
)
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_token_account_reclaim_service import (
    run_solana_dormant_token_account_reclaim,
)
from src.core.trading.walletmaintenance.trading_wallet_maintenance_structures import (
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
