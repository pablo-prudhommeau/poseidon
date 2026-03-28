from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class LifiAction(BaseModel):
    type: str


class LifiEstimate(BaseModel):
    tool: str


class LifiTransactionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    to: str
    data: str
    value: str
    from_address: Optional[str] = None


class LifiQuote(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    tool: str
    action: LifiAction
    estimate: LifiEstimate
    transaction_request: LifiTransactionRequest


class EvmChain(BaseModel):
    dexscreener_chain_identifier: str
    chain_identifier: int
    native_token_symbol: str
