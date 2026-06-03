from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason
from src.integrations.blockchain.blockchain_live_executor import BlockchainExecutionResult


class TradingLiveSellExecutionOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    execution_result: Optional[BlockchainExecutionResult] = None
    failure_reason: Optional[BlockchainTransactionFailureReason] = None
