from __future__ import annotations

import enum


class BlockchainTransactionFailureReason(str, enum.Enum):
    ACCOUNT_FROZEN = "ACCOUNT_FROZEN"
    STALE_BLOCKHASH = "STALE_BLOCKHASH"
    CONFIRMATION_TIMEOUT = "CONFIRMATION_TIMEOUT"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    UNKNOWN = "UNKNOWN"


class BlockchainTransactionExecutionError(Exception):
    def __init__(
            self,
            message: str,
            transaction_signature: str,
            failure_reason: BlockchainTransactionFailureReason,
            raw_error_text: str,
    ) -> None:
        super().__init__(message)
        self.transaction_signature = transaction_signature
        self.failure_reason = failure_reason
        self.raw_error_text = raw_error_text
