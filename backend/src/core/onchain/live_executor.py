from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import base58

from src.configuration.config import settings
from src.core.structures.structures import LifiRoute
from src.core.utils.dict_utils import _read_path
from src.core.onchain.solana_signer import build_default_solana_signer, SolanaSigner
from src.core.onchain.evm_signer import build_default_evm_signer, EvmSigner
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    """
    Normalized execution result for any network.
    """
    network: str  # 'EVM' | 'SOLANA'
    tx_hash_or_signature: str


class LiveExecutionService:
    """
    Executes pre-built LI.FI routes on EVM or Solana.

    The service is lightweight and stateless. Create when needed and close when done.
    """

    def __init__(self) -> None:
        self._solana_signer: Optional[SolanaSigner] = None
        self._evm_signer: Optional[EvmSigner] = None

    async def close(self) -> None:
        """
        Nothing to close right now, kept for symmetry/forward-compat.
        """
        return

    # -------- SOLANA -------- #

    async def solana_execute_route(self, route: LifiRoute) -> str:
        """
        Execute a Solana route.

        Accepts the following shapes from LI.FI:
        - transaction.serializedTransaction
        - transactions[0].serializedTransaction
        - serializedTransaction
        - transactionRequest.data  (souvent le cas)
        """
        serialized = self._extract_solana_serialized_blob(route)
        if not isinstance(serialized, bytes) or len(serialized) == 0:
            raise ValueError("Invalid Solana serialized transaction payload.")

        # Safety: make sure the route 'fromAddress' matches our signer
        route_from = _read_path(route, ("fromAddress",))
        if self._solana_signer is None:
            self._solana_signer = build_default_solana_signer()

        if isinstance(route_from, str) and len(route_from) > 0:
            if route_from.strip() != self._solana_signer.address:
                raise ValueError(
                    f"Route fromAddress ({route_from}) does not match signer address ({self._solana_signer.address})."
                )

        log.info("[EXECUTOR][SOL] Broadcasting serialized transaction (bytes=%d)", len(serialized))
        signature = self._solana_signer.send_raw_transaction(serialized)
        log.info("[EXECUTOR][SOL] Broadcast success — signature=%s", signature)
        return signature

    @staticmethod
    def _decode_blob(raw: str) -> bytes:
        """
        Try to decode a string into bytes, attempting base64 then base58 then hex (0x...).
        Returns empty bytes on failure.
        """
        if not isinstance(raw, str) or len(raw) == 0:
            return b""

        # 1) Base64 (strict)
        try:
            import base64 as _b64
            decoded = _b64.b64decode(raw, validate=True)
            if len(decoded) > 0:
                return decoded
        except Exception:
            pass

        # 2) Base58
        try:
            decoded = base58.b58decode(raw)
            if len(decoded) > 0:
                return decoded
        except Exception:
            pass

        # 3) Hex (with or without 0x)
        try:
            hex_str = raw[2:] if raw.startswith("0x") else raw
            decoded = bytes.fromhex(hex_str)
            if len(decoded) > 0:
                return decoded
        except Exception:
            pass

        return b""

    @classmethod
    def _extract_solana_serialized_blob(cls, route: LifiRoute) -> bytes:
        """
        Extract a serialized Solana transaction blob from a LI.FI route with
        strict attribute/path navigation (no dict.get or indexing literals).
        Tries multiple shapes and logs the successful source.
        """
        candidates = [
            (("transaction", "serializedTransaction"), "transaction.serializedTransaction"),
            (("transactions", 0, "serializedTransaction"), "transactions[0].serializedTransaction"),
            (("serializedTransaction",), "serializedTransaction"),
            (("transactionRequest", "data"), "transactionRequest.data"),
        ]

        for path, label in candidates:
            candidate = _read_path(route, path)
            if isinstance(candidate, str) and len(candidate) > 0:
                decoded = cls._decode_blob(candidate)
                if len(decoded) > 0:
                    log.debug("[EXECUTOR][SOL][EXTRACT] Using %s (len(raw)=%d, len(decoded)=%d)",
                              label, len(candidate), len(decoded))
                    return decoded

        log.debug("[EXECUTOR][SOL][EXTRACT] No suitable serialized payload found in route")
        return b""

    # -------- EVM -------- #

    async def evm_execute_route(self, route: LifiRoute) -> str:
        """
        Execute an EVM route.

        Shape possibilities:
        - transactionRequest.rawTransaction  (pre-signed RLP) → broadcast as-is
        - transactionRequest{ to, data, value?, gas? }        → sign locally with EvmSigner
        """
        transaction_request = _read_path(route, ("transactionRequest",))
        if transaction_request is None:
            raise ValueError("Missing transactionRequest for EVM route.")

        # 1) Pre-signed RLP
        raw_rlp = _read_path(transaction_request, ("rawTransaction",))
        if isinstance(raw_rlp, str) and len(raw_rlp) > 0:
            from web3 import Web3  # type: ignore
            provider = Web3.HTTPProvider(settings.EVM_RPC_URL)
            web3 = Web3(provider)
            tx_hash = web3.eth.send_raw_transaction(bytes.fromhex(raw_rlp.removeprefix("0x")))
            hex_hash = tx_hash.hex()
            log.info("[EXECUTOR][EVM] Broadcast success — tx=%s", hex_hash)
            return hex_hash

        # 2) Sign locally using our EvmSigner
        to = _read_path(transaction_request, ("to",))
        data = _read_path(transaction_request, ("data",))
        value = _read_path(transaction_request, ("value",))
        gas = _read_path(transaction_request, ("gas",))

        if not isinstance(to, str) or len(to) == 0 or not isinstance(data, str) or len(data) == 0:
            raise ValueError("Unsupported EVM route shape: missing 'to' or 'data' in transactionRequest.")

        value_wei: Optional[int] = None
        if isinstance(value, int):
            value_wei = value
        elif isinstance(value, str) and len(value) > 0:
            # LI.FI renvoie souvent un hexstring
            value_wei = int(value, 16) if value.startswith("0x") else int(value)

        gas_limit: Optional[int] = None
        if isinstance(gas, int):
            gas_limit = gas
        elif isinstance(gas, str) and len(gas) > 0:
            gas_limit = int(gas, 16) if gas.startswith("0x") else int(gas)

        if self._evm_signer is None:
            self._evm_signer = build_default_evm_signer()

        log.info("[EXECUTOR][EVM] Signing and broadcasting via local signer (to=%s)", to)
        tx_hash_hex = self._evm_signer.send_transaction(to=to, data=data, value_wei=value_wei, gas_limit=gas_limit)
        log.info("[EXECUTOR][EVM] Broadcast success — tx=%s", tx_hash_hex)
        return tx_hash_hex
