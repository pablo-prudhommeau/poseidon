from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.core.structures.structures import BlockchainNetwork


class EvmOnchainWalletContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blockchain_network: BlockchainNetwork
    wallet_address: str
    native_token_balance_wei: int
    native_token_balance_usd: float
    stablecoin_balance_raw: float
