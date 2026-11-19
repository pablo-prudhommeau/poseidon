from __future__ import annotations

import pytest

from src.integrations.lifi.lifi_helpers import LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, validate_lifi_swap_transaction_request
from src.integrations.lifi.lifi_structures import LifiTransactionRequest, LifiTransactionRequestRejectedError

WALLET_ADDRESS: str = "0xD404a0000000000000000000000000000003f75B"
USDC_ADDRESS: str = "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E"
AVALANCHE_CHAIN_IDENTIFIER: int = 43114


def _build_transaction_request(to: str, value: str, from_address: str, chain_id: int) -> LifiTransactionRequest:
    return LifiTransactionRequest(
        to=to,
        data="0xabcdef",
        value=value,
        from_address=from_address,
        gas_limit="0x716fd",
        chain_id=chain_id,
    )


def _validate(transaction_request: LifiTransactionRequest) -> None:
    validate_lifi_swap_transaction_request(
        transaction_request=transaction_request,
        wallet_address=WALLET_ADDRESS,
        expected_router_address=LIFI_EVM_DIAMOND_CONTRACT_ADDRESS,
        expected_chain_identifier=AVALANCHE_CHAIN_IDENTIFIER,
    )


def test_validate_lifi_swap_transaction_request_accepts_a_real_quote_shape() -> None:
    _validate(_build_transaction_request(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, "0x0", WALLET_ADDRESS, AVALANCHE_CHAIN_IDENTIFIER))


def test_validate_lifi_swap_transaction_request_compares_addresses_case_insensitively() -> None:
    _validate(_build_transaction_request(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS.lower(), "0", WALLET_ADDRESS.upper().replace("0X", "0x"), AVALANCHE_CHAIN_IDENTIFIER))


def test_validate_lifi_swap_transaction_request_rejects_a_foreign_recipient() -> None:
    with pytest.raises(LifiTransactionRequestRejectedError, match="recipient"):
        _validate(_build_transaction_request(USDC_ADDRESS, "0x0", WALLET_ADDRESS, AVALANCHE_CHAIN_IDENTIFIER))


def test_validate_lifi_swap_transaction_request_rejects_a_native_value() -> None:
    with pytest.raises(LifiTransactionRequestRejectedError, match="native value of 1 wei"):
        _validate(_build_transaction_request(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, "0x1", WALLET_ADDRESS, AVALANCHE_CHAIN_IDENTIFIER))


def test_validate_lifi_swap_transaction_request_rejects_a_foreign_sender() -> None:
    with pytest.raises(LifiTransactionRequestRejectedError, match="sender"):
        _validate(_build_transaction_request(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, "0x0", USDC_ADDRESS, AVALANCHE_CHAIN_IDENTIFIER))


def test_validate_lifi_swap_transaction_request_rejects_a_foreign_chain() -> None:
    with pytest.raises(LifiTransactionRequestRejectedError, match="chain"):
        _validate(_build_transaction_request(LIFI_EVM_DIAMOND_CONTRACT_ADDRESS, "0x0", WALLET_ADDRESS, 1))
