from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.integrations.lifi.lifi_structures import LifiTransactionRequest


class BlockchainSolanaRoute(BaseModel):
    serialized_transaction_base64: str


class BlockchainEvmRoute(BaseModel):
    transaction_request: LifiTransactionRequest
    approval_token_address: Optional[str] = None
    approval_required_amount_wei: int = 0


class BlockchainExecutionRoute(BaseModel):
    evm_route: Optional[BlockchainEvmRoute] = None
    solana_route: Optional[BlockchainSolanaRoute] = None
