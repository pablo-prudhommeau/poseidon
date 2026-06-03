from __future__ import annotations

import re

from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason

_INSTRUCTION_ERROR_CUSTOM_17_PATTERN = re.compile(r"InstructionErrorCustom\s*\(\s*17\s*\)", re.IGNORECASE)
_ACCOUNT_FROZEN_TEXT_PATTERN = re.compile(r"AccountFrozen", re.IGNORECASE)
_STALE_BLOCKHASH_TEXT_PATTERN = re.compile(r"STALE_BLOCKHASH|blockhash.*no longer valid", re.IGNORECASE)


def resolve_blockchain_transaction_failure_reason_from_confirmation_error(
        raw_error_text: str,
        confirmation_timed_out: bool,
) -> BlockchainTransactionFailureReason:
    if confirmation_timed_out and len(raw_error_text.strip()) == 0:
        return BlockchainTransactionFailureReason.CONFIRMATION_TIMEOUT

    if _INSTRUCTION_ERROR_CUSTOM_17_PATTERN.search(raw_error_text):
        return BlockchainTransactionFailureReason.ACCOUNT_FROZEN

    if _ACCOUNT_FROZEN_TEXT_PATTERN.search(raw_error_text):
        return BlockchainTransactionFailureReason.ACCOUNT_FROZEN

    if _STALE_BLOCKHASH_TEXT_PATTERN.search(raw_error_text):
        return BlockchainTransactionFailureReason.STALE_BLOCKHASH

    if confirmation_timed_out:
        return BlockchainTransactionFailureReason.CONFIRMATION_TIMEOUT

    return BlockchainTransactionFailureReason.UNKNOWN
