from __future__ import annotations

from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason

NON_RETRYABLE_BLOCKCHAIN_TRANSACTION_FAILURE_REASONS: frozenset[BlockchainTransactionFailureReason] = frozenset({
    BlockchainTransactionFailureReason.ACCOUNT_FROZEN,
    BlockchainTransactionFailureReason.INSUFFICIENT_LIQUIDITY,
})


def normalize_evm_transaction_hash(transaction_hash: str | bytes) -> str:
    if isinstance(transaction_hash, bytes):
        hex_value = transaction_hash.hex()
    else:
        hex_value = transaction_hash.strip().removeprefix("0x")
    return f"0x{hex_value}"


def is_non_retryable_blockchain_transaction_failure_reason(
        failure_reason: BlockchainTransactionFailureReason | None,
) -> bool:
    if failure_reason is None:
        return False
    return failure_reason in NON_RETRYABLE_BLOCKCHAIN_TRANSACTION_FAILURE_REASONS
