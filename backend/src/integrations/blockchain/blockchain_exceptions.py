from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork


class BlockchainPriceUnavailableError(Exception):
    def __init__(self, message: str, blockchain_network: BlockchainNetwork) -> None:
        super().__init__(message)
        self.blockchain_network = blockchain_network
