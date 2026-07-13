from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RoutescanAccountAction(str, Enum):
    NORMAL_TRANSACTION_LIST = "txlist"
    INTERNAL_TRANSACTION_LIST = "txlistinternal"
    TOKEN_TRANSACTION_LIST = "tokentx"


class RoutescanNormalTransactionRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    transaction_hash: str = Field(alias="hash")
    block_number: str = Field(alias="blockNumber")
    timestamp_seconds: str = Field(alias="timeStamp")
    sender_address: str = Field(alias="from")
    recipient_address: str = Field(alias="to")
    native_value_wei: str = Field(alias="value")


class RoutescanInternalTransactionRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    transaction_hash: str = Field(alias="hash")
    block_number: str = Field(default="0", alias="blockNumber")
    timestamp_seconds: str = Field(default="0", alias="timeStamp")
    sender_address: str = Field(alias="from")
    recipient_address: str = Field(alias="to")
    native_value_wei: str = Field(alias="value")


class RoutescanTokenTransactionRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    transaction_hash: str = Field(alias="hash")
    block_number: str = Field(alias="blockNumber")
    timestamp_seconds: str = Field(alias="timeStamp")
    sender_address: str = Field(alias="from")
    recipient_address: str = Field(alias="to")
    contract_address: str = Field(alias="contractAddress")
    token_decimal_count: str = Field(alias="tokenDecimal")
    token_value_raw: str = Field(alias="value")
