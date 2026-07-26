from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.evm.trading_gas_reserve_evm_service import (
    build_evm_blockchain_cash_balance_gas_reserve_enrichment,
    compute_evm_gas_refill_locked_stablecoin_snapshot,
    compute_evm_wallet_auxiliary_assets_snapshot,
    is_evm_gas_reserve_sufficient_for_buy,
)
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
        return is_evm_gas_reserve_sufficient_for_buy(self._wallet_context)

    def compute_gas_refill_locked_stablecoin_snapshot(self) -> GasRefillLockedStablecoinSnapshot:
        return compute_evm_gas_refill_locked_stablecoin_snapshot(self._wallet_context)

    def compute_wallet_auxiliary_assets_snapshot(self) -> WalletAuxiliaryAssetsSnapshot:
        return compute_evm_wallet_auxiliary_assets_snapshot(self._wallet_context)

    def build_blockchain_cash_balance_gas_reserve_enrichment(self) -> BlockchainCashBalanceGasReserveEnrichment:
        return build_evm_blockchain_cash_balance_gas_reserve_enrichment(self._wallet_context)
