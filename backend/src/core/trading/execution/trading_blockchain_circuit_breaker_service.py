from __future__ import annotations

import threading

from src.configuration.config import settings
from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason
from src.integrations.blockchain.blockchain_utils import is_non_retryable_blockchain_transaction_failure_reason
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_retryable_exit_failure_count_by_position_id: dict[int, int] = {}
_circuit_breaker_lock = threading.Lock()


def is_blockchain_circuit_breaker_enabled() -> bool:
    return settings.TRADING_BLOCKCHAIN_CIRCUIT_BREAKER_ENABLED


def should_block_live_sell_before_broadcast(wallet_token_transfer_blocked: bool) -> bool:
    if not is_blockchain_circuit_breaker_enabled():
        return False
    return wallet_token_transfer_blocked


def should_mark_position_staled_immediately_after_failure(
        failure_reason: BlockchainTransactionFailureReason | None,
) -> bool:
    if not is_blockchain_circuit_breaker_enabled():
        return False
    return is_non_retryable_blockchain_transaction_failure_reason(failure_reason)


def should_mark_position_staled_after_retryable_exit_failure(position_id: int) -> bool:
    if not is_blockchain_circuit_breaker_enabled():
        return False
    consecutive_retryable_failures = _read_retryable_exit_failure_count(position_id)
    return consecutive_retryable_failures >= settings.TRADING_BLOCKCHAIN_CIRCUIT_BREAKER_MAX_CONSECUTIVE_EXIT_FAILURES


def record_retryable_exit_failure(position_id: int) -> int:
    with _circuit_breaker_lock:
        next_count = _retryable_exit_failure_count_by_position_id.get(position_id, 0) + 1
        _retryable_exit_failure_count_by_position_id[position_id] = next_count
        logger.warning(
            "[TRADING][BLOCKCHAIN][CIRCUIT_BREAKER] Retryable exit failure recorded — position_id=%s consecutive_retryable_exit_failures=%s max=%s",
            position_id,
            next_count,
            settings.TRADING_BLOCKCHAIN_CIRCUIT_BREAKER_MAX_CONSECUTIVE_EXIT_FAILURES,
        )
        return next_count


def reset_retryable_exit_failure_count(position_id: int) -> None:
    with _circuit_breaker_lock:
        if position_id in _retryable_exit_failure_count_by_position_id:
            del _retryable_exit_failure_count_by_position_id[position_id]
            logger.info(
                "[TRADING][BLOCKCHAIN][CIRCUIT_BREAKER] Retryable exit failure counter reset — position_id=%s",
                position_id,
            )


def _read_retryable_exit_failure_count(position_id: int) -> int:
    with _circuit_breaker_lock:
        return _retryable_exit_failure_count_by_position_id.get(position_id, 0)
