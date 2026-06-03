from __future__ import annotations

from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason
from src.integrations.blockchain.solana.solana_utils import (
    resolve_blockchain_transaction_failure_reason_from_confirmation_error,
)


def test_resolve_failure_reason_from_instruction_error_custom_17() -> None:
    raw_error_text = "TransactionErrorInstructionError((5, Tagged(Custom(InstructionErrorCustom(17)))))"
    failure_reason = resolve_blockchain_transaction_failure_reason_from_confirmation_error(
        raw_error_text=raw_error_text,
        confirmation_timed_out=False,
    )
    assert failure_reason == BlockchainTransactionFailureReason.ACCOUNT_FROZEN


def test_resolve_failure_reason_from_confirmation_timeout() -> None:
    failure_reason = resolve_blockchain_transaction_failure_reason_from_confirmation_error(
        raw_error_text="",
        confirmation_timed_out=True,
    )
    assert failure_reason == BlockchainTransactionFailureReason.CONFIRMATION_TIMEOUT
