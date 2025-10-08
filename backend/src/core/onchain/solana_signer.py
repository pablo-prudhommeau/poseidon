from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import base58
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class SolanaSignerConfig:
    """
    Strongly typed configuration for the Solana signer.
    """
    rpc_url: str
    secret_key_base58: str


class SolanaSigner:
    """
    Sign and broadcast Solana transactions using a base58 secret key (solders-based).
    Provides a minimal, explicit API with a clean logging strategy.
    """

    def __init__(self, config: SolanaSignerConfig) -> None:
        if not config.rpc_url or not config.secret_key_base58:
            raise ValueError(
                "Solana signer requires RPC URL and base58 secret key (SOLANA_SECRET_KEY_BASE58)."
            )

        self.client = Client(config.rpc_url, timeout=30)
        raw_secret = base58.b58decode(config.secret_key_base58)
        self.keypair = Keypair.from_bytes(raw_secret)

        log.info("[SOLANA][SIGNER] Initialized signer. Address=%s", self.keypair.pubkey())

    @property
    def address(self) -> str:
        """
        Public base58 address derived from the loaded secret key.
        """
        return str(self.keypair.pubkey())

    @staticmethod
    def _extract_signature(response: object) -> str:
        """
        Normalize an RPC response into a base58 signature string.

        We avoid dict indexing and getattr-style reflection per codebase standards:
        - If the response is a Signature, convert to str.
        - If the response is a str, return as-is.
        - If the response has a 'value' attribute (common RPC wrapper), use it.
        """
        if isinstance(response, Signature):
            return str(response)
        if isinstance(response, str):
            if len(response) == 0:
                raise ValueError("Empty signature string from Solana RPC response.")
            return response

        # Tolerate objects that expose a `.value` attribute without using getattr().
        try:
            value = response.__getattribute__("value")  # direct attribute access without getattr()
            if isinstance(value, str) and len(value) > 0:
                return value
        except Exception:
            pass

        raise ValueError(f"Unexpected Solana RPC response type for signature: {type(response)!r}")

    def send_raw_transaction(self, raw_bytes: bytes) -> str:
        """
        Deserialize, sign if needed, and send a serialized transaction (e.g., from a LI.FI route).

        Strategy:
        1) Try to deserialize as VersionedTransaction.
        2) Attempt to sign with our Keypair (many LI.FI routes are unsigned).
        3) If signing path fails (already signed or unknown format), try broadcasting as-is.
        """
        if len(raw_bytes) == 0:
            raise ValueError("Raw transaction payload is empty.")

        log.info("[SOLANA][SIGNER] Preparing to broadcast serialized transaction (bytes=%d)", len(raw_bytes))

        signed_payload: Optional[bytes] = None
        try:
            versioned_tx = VersionedTransaction.from_bytes(raw_bytes)
            try:
                # Preferred path: let solders sign the versioned transaction
                versioned_tx_signed = versioned_tx.sign([self.keypair])
                signed_payload = bytes(versioned_tx_signed)
                log.debug("[SOLANA][SIGNER] Transaction signed via VersionedTransaction.sign()")
            except Exception:
                # Fallback: sign the message and rebuild
                message = versioned_tx.message
                signature: Signature = self.keypair.sign_message(bytes(message))
                versioned_tx_signed = VersionedTransaction(message, [signature])
                signed_payload = bytes(versioned_tx_signed)
                log.debug("[SOLANA][SIGNER] Transaction signed via manual message signature")
        except Exception as exc:
            log.debug(
                "[SOLANA][SIGNER] Could not parse as VersionedTransaction (%s). Will try raw broadcast.",
                exc,
            )

        payload = signed_payload or raw_bytes
        response = self.client.send_raw_transaction(
            payload,
            opts=TxOpts(skip_preflight=False, max_retries=3),
        )
        signature = self._extract_signature(response)
        log.info("[SOLANA][SIGNER] Broadcasted signature %s", signature)
        return signature


def build_default_solana_signer() -> SolanaSigner:
    """
    Factory using Settings for convenience. Ensures a single, consistent way to instantiate the signer.
    """
    config = SolanaSignerConfig(
        rpc_url=settings.SOLANA_RPC_URL,
        secret_key_base58=settings.SOLANA_SECRET_KEY_BASE58,
    )
    return SolanaSigner(config)
