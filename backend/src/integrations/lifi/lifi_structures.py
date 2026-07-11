from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LifiRouteNormalizationError(ValueError):
    pass


class LifiQuoteUnavailableError(RuntimeError):
    def __init__(
            self,
            message: str,
            http_status_code: Optional[int] = None,
            response_message: Optional[str] = None,
    ) -> None:
        self.http_status_code = http_status_code
        self.response_message = response_message
        super().__init__(message)


class LifiAction(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LifiEstimate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    tool: Optional[str] = None
    to_amount: Optional[str] = Field(default=None, alias="toAmount")
    to_amount_min: Optional[str] = Field(default=None, alias="toAmountMin")


class LifiTransactionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    to: str
    data: str
    value: str
    from_address: Optional[str] = Field(default=None, alias="from")
    gas_limit: Optional[str] = Field(default=None, alias="gasLimit")
    chain_id: Optional[int] = Field(default=None, alias="chainId")
    raw_transaction: Optional[str] = Field(default=None, alias="rawTransaction")


class LifiQuote(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    type: Optional[str] = None
    tool: Optional[str] = None
    action: Optional[LifiAction] = None
    estimate: LifiEstimate
    transaction_request: LifiTransactionRequest = Field(alias="transactionRequest")


class EvmChain(BaseModel):
    dexscreener_chain_identifier: str
    chain_identifier: int
    native_token_symbol: str


class LifiSolanaSerializedTransaction(BaseModel):
    serialized_transaction: str


class LifiSolanaSerializedTransactionPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    serialized_transaction: str = Field(alias="serializedTransaction")


class LifiSolanaQuotePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    transaction: Optional[LifiSolanaSerializedTransactionPayload] = None
    transactions: Optional[list[LifiSolanaSerializedTransactionPayload]] = None


class LifiRoute(BaseModel):
    transaction_request: Optional[LifiTransactionRequest] = None
    estimate: Optional[LifiEstimate] = None
    transaction: Optional[LifiSolanaSerializedTransaction] = None
    transactions: Optional[list[LifiSolanaSerializedTransaction]] = None


class LifiAlternativeRouteSummary(BaseModel):
    tool: Optional[str]
    to_amount: Optional[str]
    to_amount_min: Optional[str]
    implied_expected_price_usd: Optional[float]
    deviation_expected_percent: Optional[float]
