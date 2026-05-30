from __future__ import annotations

from typing import Optional, Protocol

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.wallet_maintenance.trading_wallet_maintenance_structures import (
    TradingNativeGasThresholdSnapshot,
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

    def resolve_native_gas_threshold_for_buy_guard(self) -> Optional[TradingNativeGasThresholdSnapshot]:
        ...
