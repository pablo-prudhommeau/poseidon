from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.core.structures.structures import BlockchainNetwork


class EvmOnchainWalletContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blockchain_network: BlockchainNetwork
