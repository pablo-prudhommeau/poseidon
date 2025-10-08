from __future__ import annotations
"""
Solana signer wrapper built on `solders` + `solana-py`.

- Loads the keypair from a base58-encoded 64-byte secret key (NOT a mnemonic).
- Exposes `public_key_base58` (and alias `address`) for Jupiter /v6/swap.
- Signs and broadcasts base64 serialized v0 transactions (e.g., from Jupiter).

Environment (Settings):
  - SOLANA_RPC_URL
  - SOLANA_SECRET_KEY_BASE58
"""

import base64
from dataclasses import dataclass
from typing import Optional, Any

import base58  # pip package: base58
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class SolanaSignerConfig:
    """Configuration for the Solana signer."""
    rpc_url: str
    secret_key_base58: str


class SolanaSigner:
    """
    Thin signer wrapper for Solana.

    Usage:
        signer = build_default_solana_signer()
        user_pubkey = signer.public_key_base58
        tx_sig = signer.sign_and_send_serialized_transaction(b64_tx)
    """

    def __init__(self, config: SolanaSignerConfig) -> None:
        if not config.rpc_url or not config.secret_key_base58:
            raise ValueError("SolanaSigner requires both rpc_url and secret_key_base58.")

        self._client: Client = Client(config.rpc_url)

        # Decode base58 secret key (expected 64-byte secret key)
        secret_bytes = base58.b58decode(config.secret_key_base58)
        if len(secret_bytes) != 64:
            raise ValueError(
                f"Expected a 64-byte secret key after base58 decoding, got {len(secret_bytes)} bytes. "
                f"Export it with: solana-keygen recover 'prompt://?key=0/0' → base58 (64 bytes)."
            )
        self._keypair: Keypair = Keypair.from_bytes(secret_bytes)
        self._public_key: Pubkey = self._keypair.pubkey()

        log.info("SolanaSigner loaded (pubkey=%s)", str(self._public_key))

    # -------------------- Properties --------------------

    @property
    def client(self) -> Client:
        """Underlying JSON-RPC client."""
        return self._client

    @property
    def public_key(self) -> Pubkey:
        """Public key object."""
        return self._public_key

    @property
    def public_key_base58(self) -> str:
        """Public key in base58 (string) — used by Jupiter /v6/swap."""
        return str(self._public_key)

    @property
    def address(self) -> str:
        """Alias to `public_key_base58` for API symmetry with the EVM signer."""
        return self.public_key_base58

    # -------------------- Signing / Sending --------------------

    @staticmethod
    def _decode_versioned_transaction(serialized_tx_base64: str) -> VersionedTransaction:
        """
        Decode a base64-encoded VersionedTransaction using solders' `from_bytes`.
        """
        raw_bytes = base64.b64decode(serialized_tx_base64)
        return VersionedTransaction.from_bytes(raw_bytes)

    def _sign_versioned_transaction(self, vtx: VersionedTransaction) -> VersionedTransaction:
        """
        Sign a VersionedTransaction with our keypair.

        Note: In solders, constructing `VersionedTransaction(message, [keypair])`
        signs the provided message and returns a fully-signed transaction.
        """
        message = vtx.message
        return VersionedTransaction(message, [self._keypair])

    def sign_and_send_serialized_transaction(
            self,
            serialized_tx_base64: str,
            *,
            skip_preflight: bool = False,
    ) -> str:
        """
        Sign a base64-encoded Versioned (v0) transaction (e.g., from Jupiter) and broadcast it.

        Returns:
            The transaction signature (base58 string).
        """
        # 1) Decode to VersionedTransaction
        versioned_tx = self._decode_versioned_transaction(serialized_tx_base64)

        # 2) Sign it
        signed_vtx = self._sign_versioned_transaction(versioned_tx)

        # 3) Serialize to raw bytes and send
        raw_tx_bytes = bytes(signed_vtx)  # __bytes__ implemented in your binding
        resp = self._client.send_raw_transaction(raw_tx_bytes, opts=TxOpts(skip_preflight=skip_preflight))

        # solana-py returns an RPCResponse (usually with `.value` == signature)
        tx_sig: Optional[Any] = getattr(resp, "value", None)
        if tx_sig is None and isinstance(resp, dict):
            # Fallback if a plain dict is returned
            tx_sig = resp.get("result")

        if tx_sig is None:
            raise RuntimeError(f"send_raw_transaction failed: {resp}")

        # Normalize to string
        if isinstance(tx_sig, Signature):
            return str(tx_sig)
        return str(tx_sig)


# -------------------- Factory --------------------

def build_default_solana_signer() -> SolanaSigner:
    """
    Build the default signer using environment-backed Settings.
    Raises if misconfigured.
    """
    rpc_url = settings.SOLANA_RPC_URL
    secret_key_b58 = settings.SOLANA_SECRET_KEY_BASE58
    if not rpc_url or not secret_key_b58:
        raise RuntimeError("Solana signer not configured. Set SOLANA_RPC_URL and SOLANA_SECRET_KEY_BASE58.")
    return SolanaSigner(SolanaSignerConfig(rpc_url=rpc_url, secret_key_base58=secret_key_b58))
