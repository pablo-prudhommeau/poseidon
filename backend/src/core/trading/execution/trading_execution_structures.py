from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from src.integrations.blockchain.blockchain_execution_structures import BlockchainExecutionResult
from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason
from src.persistence.models import TradingTrade


class TradingLiveSellExecutionOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    execution_result: Optional[BlockchainExecutionResult] = None
    failure_reason: Optional[BlockchainTransactionFailureReason] = None


class TradingPositionClosingSellResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    trading_trade: Optional[TradingTrade] = None
    stablecoin_swap_settled_on_chain: bool = False
