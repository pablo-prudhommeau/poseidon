from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.core.structures.structures import BlockchainNetwork

if TYPE_CHECKING:
    from src.core.trading.gasreserve.trading_gas_reserve_structures import (
        BlockchainCashBalanceGasReserveEnrichment,
        GasRefillLockedStablecoinSnapshot,
        WalletAuxiliaryAssetsSnapshot,
    )


class TradingGasReserveChainHandler(ABC):
    @abstractmethod
    def blockchain_network(self) -> BlockchainNetwork:
        ...

    @abstractmethod
    def is_gas_reserve_sufficient_for_buy(self) -> bool:
        ...

    @abstractmethod
    def compute_gas_refill_locked_stablecoin_snapshot(self) -> GasRefillLockedStablecoinSnapshot:
        ...

    @abstractmethod
    def compute_wallet_auxiliary_assets_snapshot(self) -> WalletAuxiliaryAssetsSnapshot:
        ...

    @abstractmethod
    def build_blockchain_cash_balance_gas_reserve_enrichment(self) -> BlockchainCashBalanceGasReserveEnrichment:
        ...
