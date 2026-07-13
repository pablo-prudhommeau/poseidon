from __future__ import annotations

from typing import Optional

EVM_ERROR_STRING_SELECTOR_BYTES: bytes = bytes.fromhex("08c379a0")
EVM_PANIC_SELECTOR_BYTES: bytes = bytes.fromhex("4e487b71")


def decode_evm_revert_reason_from_hex(revert_data_hex: str) -> str:
    normalized_hex: str = revert_data_hex.removeprefix("0x")
    if not normalized_hex:
        return "UNKNOWN_REVERT"
    revert_bytes: bytes = bytes.fromhex(normalized_hex)
    return decode_evm_revert_reason_from_bytes(revert_bytes)


def decode_evm_revert_reason_from_bytes(revert_bytes: bytes) -> str:
    if len(revert_bytes) < 4:
        return revert_bytes.hex()

    selector_bytes: bytes = revert_bytes[:4]
    payload_bytes: bytes = revert_bytes[4:]

    if selector_bytes == EVM_ERROR_STRING_SELECTOR_BYTES:
        if len(payload_bytes) < 64:
            return revert_bytes.hex()
        string_length: int = int.from_bytes(payload_bytes[32:64], byteorder="big")
        string_bytes: bytes = payload_bytes[64:64 + string_length]
        return string_bytes.decode("utf-8", errors="replace").rstrip("\x00")

    if selector_bytes == EVM_PANIC_SELECTOR_BYTES:
        if len(payload_bytes) >= 32:
            panic_code: int = int.from_bytes(payload_bytes[:32], byteorder="big")
            return f"Panic({panic_code})"
        return revert_bytes.hex()

    return revert_bytes.hex()


def decode_evm_revert_reason_from_contract_logic_error(
        error_message: str,
        revert_data_hex: Optional[str],
) -> str:
    execution_reverted_prefix: str = "execution reverted:"
    if execution_reverted_prefix in error_message:
        revert_reason: str = error_message.split(execution_reverted_prefix, maxsplit=1)[1].strip()
        if revert_reason:
            return revert_reason
    if revert_data_hex is not None and revert_data_hex.strip():
        return decode_evm_revert_reason_from_hex(revert_data_hex)
    if error_message.strip():
        return error_message.strip()
    return "UNKNOWN_REVERT"
