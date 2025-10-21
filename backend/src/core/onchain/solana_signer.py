from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import base58
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from solders.presigner import Presigner

# Optionnel: types de réponses solders (présents avec solana-py récent)
try:
    from solders.rpc.responses import SendTransactionResp  # type: ignore
except Exception:  # pragma: no cover - compat
    SendTransactionResp = object  # sentinel pour isinstance

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
    Signs and broadcasts Solana versioned transactions (solders-based).

    Key points:
    - Robust signature extraction compatible with recent solana-py/solders.
    - Multiple signing strategies to satisfy different PyO3 overload sets.
    - Optional blockhash validity check when RPC supports it.
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
        """Public base58 address derived from the loaded secret key."""
        return str(self.keypair.pubkey())

    @staticmethod
    def _extract_signature(response: object) -> str:
        """
        Normalize an RPC response into a base58 signature string.

        Handles:
        - solders.signature.Signature
        - solders.rpc.responses.SendTransactionResp (value: Signature)
        - str
        - objects exposing .value as Signature or str
        - objects exposing .to_json() with {"result": "..."}
        """
        # Direct Signature
        if isinstance(response, Signature):
            return str(response)

        # Typed SendTransactionResp (newer solana-py path)
        if isinstance(response, SendTransactionResp):
            try:
                value = response.value  # type: ignore[attr-defined]
                if isinstance(value, Signature):
                    return str(value)
                if isinstance(value, str) and len(value) > 0:
                    return value
            except Exception:
                pass

        # Generic .value attribute (Signature or str)
        try:
            value_attr = response.__getattribute__("value")
            if isinstance(value_attr, Signature):
                return str(value_attr)
            if isinstance(value_attr, str) and len(value_attr) > 0:
                return value_attr
        except Exception:
            pass

        # Last resort: to_json() → dict → "result"
        try:
            to_json = response.to_json()  # type: ignore[attr-defined]
            if isinstance(to_json, dict):
                result = to_json.get("result")
                if isinstance(result, str) and len(result) > 0:
                    return result
        except Exception:
            pass

        raise ValueError(f"Unexpected Solana RPC response type for signature: {type(response)!r}")

    @staticmethod
    def _recent_blockhash_str_from_message(message: object) -> str:
        """
        Best-effort extraction of the recent blockhash string from a VersionedMessage.
        Returns an empty string if not accessible (non-fatal).
        """
        try:
            recent = message.__getattribute__("recent_blockhash")
            text = str(recent)
            return text if isinstance(text, str) else ""
        except Exception:
            return ""

    def _is_blockhash_valid(self, blockhash: str) -> Optional[bool]:
        """
        Ask the RPC if a given blockhash is still valid, when the client supports it.

        Returns:
         - True / False when the node answers,
         - None if the endpoint is missing or fails (non-blocking).
        """
        if not blockhash:
            return None
        # Certaines versions de solana-py n'exposent pas is_blockhash_valid
        if not hasattr(self.client, "is_blockhash_valid"):
            return None
        try:
            resp = self.client.is_blockhash_valid(blockhash)  # type: ignore[attr-defined]
            try:
                value = resp.__getattribute__("value")
                if isinstance(value, bool):
                    return value
            except Exception:
                pass
            return None
        except Exception as exc:
            log.debug("[SOLANA][SIGNER] is_blockhash_valid failed — %s", exc)
            return None

    def _sign_versioned_bytes(self, raw_bytes: bytes) -> bytes:
        """
        Parse bytes as VersionedTransaction, sign with local keypair, and return
        signed bytes.

        Strategy:
        1) VersionedTransaction(message, [keypair])
        2) VersionedTransaction(message, [Presigner(pubkey, manual_sig)])
        """
        try:
            versioned_tx = VersionedTransaction.from_bytes(raw_bytes)
        except Exception as exc:
            raise ValueError(f"Payload is not a valid VersionedTransaction: {exc}") from exc

        message = versioned_tx.message

        # (1) Constructor with keypairs (preferred)
        try:
            signed_vtx = VersionedTransaction(message, [self.keypair])
            signed_bytes = bytes(signed_vtx)
            log.debug("[SOLANA][SIGNER] Signed using constructor(keypairs).")
            return signed_bytes
        except Exception as exc_ctor_keypair:
            log.debug("[SOLANA][SIGNER] constructor(keypairs) path failed: %s", exc_ctor_keypair)

        # (2) Manual signature + Presigner wrapper
        try:
            manual_sig: Signature = self.keypair.sign_message(bytes(message))
            presigner = Presigner(self.keypair.pubkey(), manual_sig)
            signed_vtx = VersionedTransaction(message, [presigner])
            signed_bytes = bytes(signed_vtx)
            log.debug("[SOLANA][SIGNER] Signed using constructor(Presigner).")
            return signed_bytes
        except Exception as exc_ctor_presigner:
            raise ValueError(
                f"[SOLANA][SIGNER] Could not sign VersionedTransaction using any method. "
                f"ctor(keypairs): {exc_ctor_keypair!r} | ctor(presigner): {exc_ctor_presigner!r}"
            ) from exc_ctor_presigner

    def send_raw_transaction(self, raw_bytes: bytes) -> str:
        """
        Sign and send an UNSIGNED serialized VersionedTransaction.

        Steps:
          - Parse → optionally validate recent blockhash (if RPC supports)
          - Sign
          - Broadcast with relaxed preflight (to limit false negatives)
        """
        if len(raw_bytes) == 0:
            raise ValueError("Raw transaction payload is empty.")

        log.info("[SOLANA][SIGNER] Preparing to sign+broadcast serialized transaction (bytes=%d)", len(raw_bytes))

        # Best-effort blockhash sanity (non-fatal if unsupported)
        try:
            parsed = VersionedTransaction.from_bytes(raw_bytes)
            blockhash_text = self._recent_blockhash_str_from_message(parsed.message)
            valid = self._is_blockhash_valid(blockhash_text)
            if valid is False:
                raise ValueError(
                    f"[SOLANA][SIGNER][STALE_BLOCKHASH] The route's recent blockhash is no longer valid "
                    f"({blockhash_text}). Rebuild the LI.FI transaction and retry."
                )
            if valid is True:
                log.debug("[SOLANA][SIGNER] Recent blockhash is valid: %s", blockhash_text)
        except Exception as exc_check:
            # Soft-fail: si lecture/validation échoue, on continue; le réseau tranchera
            log.debug("[SOLANA][SIGNER] Pre-send blockhash check skipped (%s).", exc_check)

        signed_payload = self._sign_versioned_bytes(raw_bytes)

        response = self.client.send_raw_transaction(
            signed_payload,
            opts=TxOpts(skip_preflight=True, max_retries=5, preflight_commitment="processed"),
        )
        signature = self._extract_signature(response)
        log.info("[SOLANA][SIGNER] Broadcasted signature %s", signature)
        return signature


def build_default_solana_signer() -> SolanaSigner:
    """Factory using Settings for convenience."""
    config = SolanaSignerConfig(
        rpc_url=settings.SOLANA_RPC_URL,
        secret_key_base58=settings.SOLANA_SECRET_KEY_BASE58,
    )
    return SolanaSigner(config)
