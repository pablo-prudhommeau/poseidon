from __future__ import annotations

from typing import Protocol

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.walletmaintenance.trading_wallet_maintenance_structures import (
    TradingWalletMaintenanceChainGasResult,
    TradingWalletMaintenanceChainReclaimResult,
)


class TradingWalletMaintenanceChainHandler(Protocol):
    def blockchain_network(self) -> BlockchainNetwork:
        ...

    def run_native_gas_maintenance(self) -> TradingWalletMaintenanceChainGasResult:
        ...

    def run_dormant_account_reclaim(self) -> TradingWalletMaintenanceChainReclaimResult:
        ...
