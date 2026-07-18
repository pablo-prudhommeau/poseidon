from __future__ import annotations

from src.integrations.aave.aave_protocol_reader import (
    _decode_uint256_return_data,
    _normalize_contract_call_data,
)
from src.integrations.blockchain.evm.blockchain_evm_multicall_reader import (
    AVALANCHE_MULTICALL3_CONTRACT_ADDRESS,
    BlockchainEvmMulticallCall,
)


def test_normalize_contract_call_data_accepts_hex_string_and_bytes() -> None:
    hex_call_data: str = "0xabcdef12"
    normalized_from_hex: bytes = _normalize_contract_call_data(hex_call_data)
    normalized_from_bytes: bytes = _normalize_contract_call_data(bytes.fromhex("abcdef12"))
    assert normalized_from_hex == bytes.fromhex("abcdef12")
    assert normalized_from_bytes == bytes.fromhex("abcdef12")


def test_decode_uint256_return_data_reads_abi_encoded_integer() -> None:
    encoded_uint256: bytes = (987654321).to_bytes(32, byteorder="big")
    decoded_value: int = _decode_uint256_return_data(encoded_uint256)
    assert decoded_value == 987654321


def test_multicall_call_model_keeps_target_and_payload() -> None:
    multicall_call = BlockchainEvmMulticallCall(
        target_address=AVALANCHE_MULTICALL3_CONTRACT_ADDRESS,
        call_data=bytes.fromhex("deadbeef"),
        allow_failure=True,
    )
    assert multicall_call.target_address == AVALANCHE_MULTICALL3_CONTRACT_ADDRESS
    assert multicall_call.call_data == bytes.fromhex("deadbeef")
    assert multicall_call.allow_failure is True
