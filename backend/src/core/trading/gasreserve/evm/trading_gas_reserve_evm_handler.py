from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.evm.trading_gas_reserve_evm_structures import EvmOnchainWalletContext
from src.core.trading.gasreserve.trading_gas_reserve_chain_handler import TradingGasReserveChainHandler
from src.core.trading.gasreserve.trading_gas_reserve_structures import (
    BlockchainCashBalanceGasReserveEnrichment,
    GasRefillLockedStablecoinSnapshot,
    WalletAuxiliaryAssetsSnapshot,
)


class TradingGasReserveEvmHandler(TradingGasReserveChainHandler):
    def __init__(
            self,
            blockchain_network: BlockchainNetwork,
            wallet_context: EvmOnchainWalletContext,
    ) -> None:
        if wallet_context.blockchain_network != blockchain_network:
            raise ValueError(
                f"EVM wallet context blockchain mismatch — handler_blockchain={blockchain_network.value} "
                f"wallet_context_blockchain={wallet_context.blockchain_network.value}",
            )
        self._blockchain_network = blockchain_network
        self._wallet_context = wallet_context

    def blockchain_network(self) -> BlockchainNetwork:
        return self._blockchain_network

    def is_gas_reserve_sufficient_for_buy(self) -> bool:
        raise NotImplementedError(
            f"Gas reserve buy guard is not implemented for blockchain '{self._blockchain_network.value}'",
        )

    def compute_gas_refill_locked_stablecoin_snapshot(self) -> GasRefillLockedStablecoinSnapshot:
        raise NotImplementedError(
            f"Gas reserve locked stablecoin snapshot is not implemented for blockchain '{self._blockchain_network.value}'",
        )

    def compute_wallet_auxiliary_assets_snapshot(self) -> WalletAuxiliaryAssetsSnapshot:
        raise NotImplementedError(
            f"Wallet auxiliary assets snapshot is not implemented for blockchain '{self._blockchain_network.value}'",
        )

    def build_blockchain_cash_balance_gas_reserve_enrichment(self) -> BlockchainCashBalanceGasReserveEnrichment:
        raise NotImplementedError(
            f"Blockchain cash balance gas reserve enrichment is not implemented for blockchain '{self._blockchain_network.value}'",
        )
