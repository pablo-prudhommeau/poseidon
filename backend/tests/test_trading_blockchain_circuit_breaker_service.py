from __future__ import annotations

from unittest.mock import patch

from src.core.trading.execution import trading_blockchain_circuit_breaker_service as circuit_breaker_service
from src.integrations.blockchain.blockchain_execution_structures import BlockchainTransactionFailureReason


def test_record_retryable_exit_failure_is_independent_per_position() -> None:
    circuit_breaker_service._retryable_exit_failure_count_by_position_id.clear()
    with patch.object(circuit_breaker_service.settings, "TRADING_BLOCKCHAIN_CIRCUIT_BREAKER_ENABLED", True), patch.object(
        circuit_breaker_service.settings,
        "TRADING_BLOCKCHAIN_CIRCUIT_BREAKER_MAX_CONSECUTIVE_EXIT_FAILURES",
        3,
    ):
        assert circuit_breaker_service.record_retryable_exit_failure(1) == 1
        assert circuit_breaker_service.record_retryable_exit_failure(1) == 2
        assert circuit_breaker_service.record_retryable_exit_failure(2) == 1
        assert not circuit_breaker_service.should_mark_position_staled_after_retryable_exit_failure(1)
        assert circuit_breaker_service.record_retryable_exit_failure(1) == 3
        assert circuit_breaker_service.should_mark_position_staled_after_retryable_exit_failure(1)


def test_non_retryable_failure_does_not_use_consecutive_counter() -> None:
    circuit_breaker_service._retryable_exit_failure_count_by_position_id.clear()
    with patch.object(circuit_breaker_service.settings, "TRADING_BLOCKCHAIN_CIRCUIT_BREAKER_ENABLED", True):
        assert circuit_breaker_service.should_mark_position_staled_immediately_after_failure(
            BlockchainTransactionFailureReason.ACCOUNT_FROZEN,
        )
        assert not circuit_breaker_service.should_mark_position_staled_immediately_after_failure(
            BlockchainTransactionFailureReason.CONFIRMATION_TIMEOUT,
        )
