from __future__ import annotations

import pytest

from src.core.aavedca.aave_dca_constants import AAVE_DCA_ORDER_ESTIMATED_GAS_UNITS
from src.core.aavedca.aave_dca_structures import AaveDcaNativeGasRequirement, AaveDcaStrategyStatus
from src.core.aavedca.aave_dca_utils import (
    build_aave_dca_pipeline_step_failure_message,
    compute_aave_dca_native_gas_requirement,
    is_aave_dca_strategy_status_transition_allowed,
)
from src.integrations.aave.aave_structures import AaveEvmTransactionConfirmationFailureKind
from src.integrations.blockchain.evm.blockchain_evm_revert_utils import (
    decode_evm_revert_reason_from_contract_logic_error,
    decode_evm_revert_reason_from_hex,
)

QUOTE_SWAP_AMOUNT_TOO_SMALL_REVERT_HEX: str = (
    "0x08c379a0"
    "0000000000000000000000000000000000000000000000000000000000000020"
    "000000000000000000000000000000000000000000000000000000000000001d"
    "51554f54455f535741505f414d4f554e545f544f4f5f534d414c4c"
    "000000000000000000000000000000000000000000"
)


def test_decode_evm_revert_reason_from_hex_quote_swap_amount_too_small() -> None:
    decoded_reason: str = decode_evm_revert_reason_from_hex(QUOTE_SWAP_AMOUNT_TOO_SMALL_REVERT_HEX)
    assert decoded_reason == "QUOTE_SWAP_AMOUNT_TOO_SMALL"


def test_decode_evm_revert_reason_from_contract_logic_error_message() -> None:
    decoded_reason: str = decode_evm_revert_reason_from_contract_logic_error(
        error_message="execution reverted: QUOTE_SWAP_AMOUNT_TOO_SMALL",
        revert_data_hex=None,
    )
    assert decoded_reason == "QUOTE_SWAP_AMOUNT_TOO_SMALL"


def test_aave_dca_order_estimated_gas_units_budgets_every_transaction_of_an_order() -> None:
    assert AAVE_DCA_ORDER_ESTIMATED_GAS_UNITS == 3 * 80_000 + 2 * 350_000 + 1_000_000


def test_compute_aave_dca_native_gas_requirement_adds_the_reserve_to_the_orders_cost() -> None:
    native_gas_requirement: AaveDcaNativeGasRequirement = compute_aave_dca_native_gas_requirement(
        order_count=20,
        max_fee_per_gas_wei=15_000_000_000,
        wallet_balance_avax=1.0,
        minimum_reserve_avax=0.05,
    )
    assert native_gas_requirement.estimated_gas_cost_avax == pytest.approx(20 * 1_940_000 * 15e-9)
    assert native_gas_requirement.required_balance_avax == pytest.approx(0.582 + 0.05)
    assert native_gas_requirement.missing_balance_avax == 0.0
    assert native_gas_requirement.is_sufficient


def test_compute_aave_dca_native_gas_requirement_reports_the_missing_balance() -> None:
    native_gas_requirement: AaveDcaNativeGasRequirement = compute_aave_dca_native_gas_requirement(
        order_count=20,
        max_fee_per_gas_wei=15_000_000_000,
        wallet_balance_avax=0.5,
        minimum_reserve_avax=0.05,
    )
    assert not native_gas_requirement.is_sufficient
    assert native_gas_requirement.missing_balance_avax == pytest.approx(0.132)


def test_compute_aave_dca_native_gas_requirement_accepts_an_exact_balance() -> None:
    native_gas_requirement: AaveDcaNativeGasRequirement = compute_aave_dca_native_gas_requirement(
        order_count=0,
        max_fee_per_gas_wei=15_000_000_000,
        wallet_balance_avax=0.05,
        minimum_reserve_avax=0.05,
    )
    assert native_gas_requirement.is_sufficient


def test_is_aave_dca_strategy_status_transition_allowed_between_active_and_paused() -> None:
    assert is_aave_dca_strategy_status_transition_allowed(AaveDcaStrategyStatus.ACTIVE, AaveDcaStrategyStatus.PAUSED)
    assert is_aave_dca_strategy_status_transition_allowed(AaveDcaStrategyStatus.PAUSED, AaveDcaStrategyStatus.ACTIVE)
    assert is_aave_dca_strategy_status_transition_allowed(AaveDcaStrategyStatus.ACTIVE, AaveDcaStrategyStatus.CANCELLED)
    assert is_aave_dca_strategy_status_transition_allowed(AaveDcaStrategyStatus.PAUSED, AaveDcaStrategyStatus.COMPLETED)


def test_is_aave_dca_strategy_status_transition_allowed_refuses_the_same_status() -> None:
    assert not is_aave_dca_strategy_status_transition_allowed(AaveDcaStrategyStatus.ACTIVE, AaveDcaStrategyStatus.ACTIVE)


def test_is_aave_dca_strategy_status_transition_allowed_never_leaves_a_terminal_status() -> None:
    assert not is_aave_dca_strategy_status_transition_allowed(AaveDcaStrategyStatus.CANCELLED, AaveDcaStrategyStatus.ACTIVE)
    assert not is_aave_dca_strategy_status_transition_allowed(AaveDcaStrategyStatus.COMPLETED, AaveDcaStrategyStatus.PAUSED)


def test_build_aave_dca_pipeline_step_failure_message_for_a_dropped_transaction() -> None:
    failure_message: str = build_aave_dca_pipeline_step_failure_message(
        pipeline_step_label="DeFi routed swap",
        onchain_revert_reason=None,
        confirmation_failure_kind=AaveEvmTransactionConfirmationFailureKind.REPLACED_OR_DROPPED,
    )
    assert failure_message == "DeFi routed swap transaction was replaced or dropped before confirmation"
