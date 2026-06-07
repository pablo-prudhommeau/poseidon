from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service import (
    build_solana_gas_refill_locked_breakdown,
    compute_solana_gas_refill_locked_stablecoin_snapshot,
    compute_solana_wallet_auxiliary_assets_snapshot,
    is_solana_gas_reserve_sufficient_for_buy,
)
from src.core.trading.gasreserve.trading_gas_reserve_chain_handler import TradingGasReserveChainHandler
from src.core.trading.gasreserve.trading_gas_reserve_structures import (
    BlockchainCashBalanceGasReserveEnrichment,
    GasRefillLockedStablecoinSnapshot,
    WalletAuxiliaryAssetsSnapshot,
)
from src.integrations.blockchain.solana.solana_structures import SolanaOnchainWalletContext


class TradingGasReserveSolanaHandler(TradingGasReserveChainHandler):
    def __init__(self, wallet_context: SolanaOnchainWalletContext) -> None:
        self._wallet_context = wallet_context

    def blockchain_network(self) -> BlockchainNetwork:
        return BlockchainNetwork.SOLANA

    def is_gas_reserve_sufficient_for_buy(self) -> bool:
        return is_solana_gas_reserve_sufficient_for_buy()

    def compute_gas_refill_locked_stablecoin_snapshot(self) -> GasRefillLockedStablecoinSnapshot:
        return compute_solana_gas_refill_locked_stablecoin_snapshot(
            wallet_context=self._wallet_context,
        )

    def compute_wallet_auxiliary_assets_snapshot(self) -> WalletAuxiliaryAssetsSnapshot:
        return compute_solana_wallet_auxiliary_assets_snapshot(
            wallet_context=self._wallet_context,
        )

    def build_blockchain_cash_balance_gas_reserve_enrichment(self) -> BlockchainCashBalanceGasReserveEnrichment:
        gas_refill_locked_breakdown = build_solana_gas_refill_locked_breakdown(
            wallet_context=self._wallet_context,
        )
        return BlockchainCashBalanceGasReserveEnrichment(
            gas_refill_locked_stablecoin_usd=gas_refill_locked_breakdown.locked_stablecoin_usd,
            gas_refill_locked_breakdown=gas_refill_locked_breakdown,
            solana_token_account_rent=self._wallet_context.rent_breakdown,
        )
