from __future__ import annotations

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
