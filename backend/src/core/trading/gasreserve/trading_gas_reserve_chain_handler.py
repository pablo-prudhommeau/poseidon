from __future__ import annotations

from typing import Protocol

from src.core.structures.structures import BlockchainNetwork


class TradingGasReserveChainHandler(Protocol):
    def blockchain_network(self) -> BlockchainNetwork:
        ...

    def is_gas_reserve_sufficient_for_buy(self) -> bool:
        ...
