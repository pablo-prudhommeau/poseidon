from __future__ import annotations

from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason

NON_RETRYABLE_BLOCKCHAIN_TRANSACTION_FAILURE_REASONS: frozenset[BlockchainTransactionFailureReason] = frozenset({
    BlockchainTransactionFailureReason.ACCOUNT_FROZEN,
    BlockchainTransactionFailureReason.INSUFFICIENT_LIQUIDITY,
})


def is_non_retryable_blockchain_transaction_failure_reason(
        failure_reason: BlockchainTransactionFailureReason | None,
) -> bool:
    if failure_reason is None:
        return False
    return failure_reason in NON_RETRYABLE_BLOCKCHAIN_TRANSACTION_FAILURE_REASONS
