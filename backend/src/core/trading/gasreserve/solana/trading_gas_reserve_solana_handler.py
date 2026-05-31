from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_service import (
    is_solana_gas_reserve_sufficient_for_buy,
)


class TradingGasReserveSolanaHandler:
    def blockchain_network(self) -> BlockchainNetwork:
        return BlockchainNetwork.SOLANA

    def is_gas_reserve_sufficient_for_buy(self) -> bool:
        return is_solana_gas_reserve_sufficient_for_buy()
