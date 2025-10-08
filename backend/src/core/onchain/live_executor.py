from __future__ import annotations

import base64
from typing import Mapping, Sequence, Union, List

from src.configuration.config import settings
from src.core.onchain.evm_signer import EvmSigner, build_default_evm_signer
from src.core.onchain.solana_signer import SolanaSigner, build_default_solana_signer
from src.core.structures.structures import EvmTransactionRequest, SolanaSerializedTransaction, LifiRoute
from src.core.utils.dict_utils import _read_path, _read_str_field, _read_int_like_field, _normalize_value_wei
from src.logging.logger import get_logger

log = get_logger(__name__)


def _extract_evm_transaction_request(route: LifiRoute) -> EvmTransactionRequest:
    """
    Extract the EVM transaction payload from a LI.FI route.

    Supported layouts (most common first):
      - route["transactionRequest"] -> {"to","data","value"?, "gasLimit"?}
      - route["items"][0]["data"]["transactionRequest"] -> {...}
      - route["steps"][0]["items"][0]["data"]["transactionRequest"] -> {...}

    Raises:
        ValueError if required keys are missing.
    """
    candidate_paths: List[Sequence[Union[str, int]]] = [
        ("transactionRequest",),
        ("items", 0, "data", "transactionRequest"),
        ("steps", 0, "items", 0, "data", "transactionRequest"),
    ]

    for path in candidate_paths:
        maybe = _read_path(route, path)
        if isinstance(maybe, Mapping):
            to = _read_str_field(maybe, "to")
            data = _read_str_field(maybe, "data")
            if to and data:
                value_wei = _normalize_value_wei(_read_int_like_field(maybe, "value"))
                gas_limit = _read_int_like_field(maybe, "gasLimit")
                return EvmTransactionRequest(to=to, data=data, value_wei=value_wei, gas_limit=gas_limit)

    raise ValueError("LI.FI route did not include a valid EVM transactionRequest.")


def _extract_solana_serialized_transaction(route: LifiRoute) -> SolanaSerializedTransaction:
    """
    Extrait une transaction Solana sérialisée (base64) depuis plusieurs layouts.
    Stratégie:
      1) chemins connus rapides
      2) scan profond dict/list à la recherche d'une clé évoquant une tx
    """
    import re

    def _try_decode(b64: str) -> bytes | None:
        if not isinstance(b64, str) or len(b64) < 60:  # éviter les petits champs "id"
            return None
        # autoriser base64 sans padding
        s = b64.strip()
        if not re.fullmatch(r"[A-Za-z0-9+/=]+", s):
            return None
        for pad in ("", "=", "==", "==="):
            try:
                return base64.b64decode(s + pad)
            except Exception:
                continue
        return None

    # 1) chemins connus
    candidate_paths: List[Sequence[Union[str, int]]] = [
        ("transaction", "serializedTransaction"),
        ("transactions", 0, "serializedTransaction"),
        ("items", 0, "data", "transaction", "serializedTransaction"),
        ("steps", 0, "items", 0, "data", "transaction", "serializedTransaction"),
        ("transaction",),  # parfois la chaîne base64 est directement sous 'transaction'/'tx'
        ("items", 0, "data", "transaction"),
        ("steps", 0, "items", 0, "data", "transaction"),
        ("tx",),
        ("items", 0, "data", "tx"),
        ("steps", 0, "items", 0, "data", "tx"),
        ("transactions", 0, "tx"),
        ("execution", "transaction"),
        ("setupTransaction",),
        ("executeTransaction",),
    ]
    for path in candidate_paths:
        maybe = _read_path(route, path)
        if isinstance(maybe, str):
            raw = _try_decode(maybe)
            if raw:
                return SolanaSerializedTransaction(payload=raw)

    # 2) scan profond
    stack: List[object] = [route]
    tx_like_keys = {"serializedTransaction", "transaction", "tx", "executeTransaction", "setupTransaction"}
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    stack.append(v)
                elif isinstance(v, str) and (k in tx_like_keys or len(v) > 60):
                    raw = _try_decode(v)
                    if raw:
                        return SolanaSerializedTransaction(payload=raw)
        elif isinstance(node, list):
            stack.extend(node)

    raise ValueError("LI.FI route did not include a serialized Solana transaction.")


class LiveExecutionService:
    """
    Perform live trades on EVM and Solana chains using precomputed LI.FI routes.

    Responsibilities:
    - Accept a precomputed LI.FI route for EVM or Solana.
    - Extract the on-chain transaction payload (locally; no dependency on lifi_client.py).
    - Delegate to the appropriate signer (EVM or Solana) and broadcast.
    - Return a canonical identifier (EVM tx hash or Solana signature).

    Notes:
    - This service does NOT fetch quotes; the caller must supply a LI.FI route.
    - For Solana, we rely on a base58 secret key (no mnemonic ingestion in code).
    """

    def __init__(self) -> None:
        log.debug("[live.exec] service initialized")

    @staticmethod
    def _ensure_evm_signer() -> EvmSigner:
        """Build a default EVM signer from settings and validate configuration."""
        if not settings.EVM_RPC_URL or not settings.EVM_MNEMONIC:
            raise RuntimeError("EVM signer is not configured. Set EVM_RPC_URL and EVM_MNEMONIC.")
        return build_default_evm_signer()

    @staticmethod
    def _ensure_solana_signer() -> SolanaSigner:
        """Build a default Solana signer from settings and validate configuration."""
        if not settings.SOLANA_RPC_URL or not settings.SOLANA_SECRET_KEY_BASE58:
            raise RuntimeError("Solana signer is not configured. Set SOLANA_RPC_URL and SOLANA_SECRET_KEY_BASE58.")
        return build_default_solana_signer()

    async def evm_execute_route(self, route: LifiRoute) -> str:
        """
        Extract `transactionRequest` and broadcast it via the mnemonic signer.

        Returns:
            Hex transaction hash.
        """
        tx = _extract_evm_transaction_request(route)
        signer = self._ensure_evm_signer()

        log.info("[live.evm] broadcasting route to %s (value_wei=%d gas_limit=%s)", tx.to, tx.value_wei, tx.gas_limit)
        tx_hash = signer.send_transaction(to=tx.to, data=tx.data, value_wei=tx.value_wei, gas_limit=tx.gas_limit)
        return tx_hash

    async def solana_execute_route(self, route: LifiRoute) -> str:
        """
        Extract a serialized Solana transaction and broadcast it via the base58 signer.

        Returns:
            Base58 signature.
        """
        serialized = _extract_solana_serialized_transaction(route)
        signer = self._ensure_solana_signer()

        log.info("[live.sol] broadcasting serialized transaction")
        signature = signer.send_raw_transaction(serialized.payload)
        return signature

    async def close(self) -> None:
        """No long-lived resources to close; kept for API symmetry."""
        return None
