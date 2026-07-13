from __future__ import annotations

from src.core.aavedca.aave_dca_helpers import (
    append_pipeline_operation,
    calculate_dynamic_allocation,
    classify_aave_dca_pipeline_onchain_failure,
)
from src.core.aavedca.aave_dca_structures import (
    AaveDcaAllocationDecision,
    AaveDcaPipelineOnchainFailureRetryPolicy,
    AaveDcaPipelineOperation,
    AaveDcaPipelineOperationStatus,
    AaveDcaPipelineOperationStep,
    AaveDcaPipelinePreflightFailureReason,
)
from src.integrations.aave.aave_structures import AaveEvmTransactionConfirmationFailureKind


def test_classify_quote_swap_amount_too_small_is_blocking() -> None:
    classification = classify_aave_dca_pipeline_onchain_failure(
        confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.REVERTED,
        onchain_revert_reason="QUOTE_SWAP_AMOUNT_TOO_SMALL",
    )
    assert classification.retry_policy == AaveDcaPipelineOnchainFailureRetryPolicy.BLOCKING
    assert classification.suspension_reason == AaveDcaPipelinePreflightFailureReason.SWAP_AMOUNT_BELOW_ROUTE_MINIMUM


def test_classify_unknown_revert_is_blocking() -> None:
    classification = classify_aave_dca_pipeline_onchain_failure(
        confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.REVERTED,
        onchain_revert_reason="UnexpectedCustomBridgeFailure",
    )
    assert classification.retry_policy == AaveDcaPipelineOnchainFailureRetryPolicy.BLOCKING
    assert classification.suspension_reason == AaveDcaPipelinePreflightFailureReason.ONCHAIN_EXECUTION_FAILED


def test_classify_confirmation_timeout_is_transient() -> None:
    classification = classify_aave_dca_pipeline_onchain_failure(
        confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.CONFIRMATION_TIMEOUT,
        onchain_revert_reason=None,
    )
    assert classification.retry_policy == AaveDcaPipelineOnchainFailureRetryPolicy.TRANSIENT


def test_append_pipeline_operation_preserves_completed_and_failed_history() -> None:
    completed_operation = AaveDcaPipelineOperation(
        step=AaveDcaPipelineOperationStep.WITHDRAW,
        status=AaveDcaPipelineOperationStatus.COMPLETED,
        transaction_hash="0xwithdraw",
    )
    first_failed_operation = AaveDcaPipelineOperation(
        step=AaveDcaPipelineOperationStep.SWAP,
        status=AaveDcaPipelineOperationStatus.FAILED,
        transaction_hash="0xswap1",
        failure_code="QUOTE_SWAP_AMOUNT_TOO_SMALL",
        failure_message="DeFi routed swap transaction reverted on-chain: QUOTE_SWAP_AMOUNT_TOO_SMALL",
        pipeline_attempt_number=1,
    )
    second_failed_operation = AaveDcaPipelineOperation(
        step=AaveDcaPipelineOperationStep.SWAP,
        status=AaveDcaPipelineOperationStatus.FAILED,
        transaction_hash="0xswap2",
        failure_code="QUOTE_SWAP_AMOUNT_TOO_SMALL",
        failure_message="DeFi routed swap transaction reverted on-chain: QUOTE_SWAP_AMOUNT_TOO_SMALL",
        pipeline_attempt_number=2,
    )

    pipeline_operations_payload = append_pipeline_operation(None, completed_operation)
    pipeline_operations_payload = append_pipeline_operation(pipeline_operations_payload, first_failed_operation)
    pipeline_operations_payload = append_pipeline_operation(pipeline_operations_payload, second_failed_operation)

    pipeline_operations = pipeline_operations_payload["pipeline_operations"]
    assert len(pipeline_operations) == 3
    assert pipeline_operations[0]["status"] == "COMPLETED"
    assert pipeline_operations[1]["status"] == "FAILED"
    assert pipeline_operations[2]["failure_code"] == "QUOTE_SWAP_AMOUNT_TOO_SMALL"


def test_average_price_protection_halt_when_market_price_above_pru() -> None:
    allocation_verdict = calculate_dynamic_allocation(
        nominal_investment_amount=0.69,
        current_dry_powder_reserve=5.87,
        current_market_price=64200.0,
        current_macro_ema=64000.0,
        current_average_purchase_price=64082.0,
        price_elasticity_aggressiveness=1.0,
    )

    assert allocation_verdict.spend_amount == 0.0
    assert allocation_verdict.dry_powder_delta == 0.69
    assert allocation_verdict.allocation_decision == AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT
    assert allocation_verdict.allocation_multiplier == 1.0


def test_aggressive_dip_draws_partial_dry_powder_when_price_below_ema() -> None:
    allocation_verdict = calculate_dynamic_allocation(
        nominal_investment_amount=0.69,
        current_dry_powder_reserve=5.87,
        current_market_price=60000.0,
        current_macro_ema=64000.0,
        current_average_purchase_price=62000.0,
        price_elasticity_aggressiveness=1.0,
    )

    assert allocation_verdict.allocation_decision == AaveDcaAllocationDecision.AGGRESSIVE_DIP_ACCUMULATION_SCALED
    assert allocation_verdict.spend_amount > 0.69
    assert allocation_verdict.dry_powder_delta < 0.0


def test_last_cycle_still_respects_pru_protection() -> None:
    allocation_verdict = calculate_dynamic_allocation(
        nominal_investment_amount=0.69,
        current_dry_powder_reserve=5.87,
        current_market_price=64200.0,
        current_macro_ema=64000.0,
        current_average_purchase_price=64082.0,
        price_elasticity_aggressiveness=1.0,
    )

    assert allocation_verdict.spend_amount == 0.0
    assert allocation_verdict.allocation_decision == AaveDcaAllocationDecision.AVERAGE_PRICE_PROTECTION_HALT
