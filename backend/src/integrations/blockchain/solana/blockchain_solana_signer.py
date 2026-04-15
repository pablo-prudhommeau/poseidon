from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bip_utils import Bip39SeedGenerator, Bip44, Bip44Coins, Bip44Changes
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.presigner import Presigner
from solders.signature import Signature
from solders.transaction import VersionedTransaction

try:
    from solders.rpc.responses import SendTransactionResp
except Exception:
    SendTransactionResp = object

from src.configuration.config import settings
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


@dataclass(frozen=True)
class SolanaSignerConfiguration:
    rpc_url: str
    mnemonic: str
    wallet_derivation_index: int


class SolanaSigner:
    def __init__(self, configuration: SolanaSignerConfiguration) -> None:
        if not configuration.rpc_url or not configuration.mnemonic:
            raise ValueError("Solana signer requires RPC URL and mnemonic")

        self.client = Client(configuration.rpc_url, timeout=30)

        seed = Bip39SeedGenerator(configuration.mnemonic).Generate("")
        bip_obj = Bip44.FromSeed(seed, Bip44Coins.SOLANA)
        account = bip_obj.Purpose().Coin().Account(configuration.wallet_derivation_index).Change(Bip44Changes.CHAIN_EXT).AddressIndex(0)
        raw_private_key = account.PrivateKey().Raw().ToBytes()
        self.keypair = Keypair.from_bytes(raw_private_key)

        logger.info("[BLOCKCHAIN][SOLANA][SIGNER] Initialized signer. Address=%s", self.keypair.pubkey())

    @property
    def address(self) -> str:
        return str(self.keypair.pubkey())

    @staticmethod
    def _extract_signature(response: object) -> str:
        if isinstance(response, Signature):
            return str(response)

        if isinstance(response, SendTransactionResp):
            try:
                value = response.value
                if isinstance(value, Signature):
                    return str(value)
                if isinstance(value, str) and len(value) > 0:
                    return value
            except Exception:
                pass

        try:
            value_attr = response.__getattribute__("value")
            if isinstance(value_attr, Signature):
                return str(value_attr)
            if isinstance(value_attr, str) and len(value_attr) > 0:
                return value_attr
        except Exception:
            pass

        try:
            to_json = response.to_json()
            if isinstance(to_json, dict):
                result = to_json.get("result")
                if isinstance(result, str) and len(result) > 0:
                    return result
        except Exception:
            pass

        raise ValueError(f"Unexpected Solana RPC response type for signature: {type(response)!r}")

    @staticmethod
    def _recent_blockhash_str_from_message(message: object) -> str:
        try:
            recent = message.__getattribute__("recent_blockhash")
            text = str(recent)
            return text if isinstance(text, str) else ""
        except Exception:
            return ""

    def _is_blockhash_valid(self, blockhash: str) -> Optional[bool]:
        if not blockhash:
            return None
        if not hasattr(self.client, "is_blockhash_valid"):
            return None
        try:
            resp = self.client.is_blockhash_valid(blockhash)
            try:
                value = resp.__getattribute__("value")
                if isinstance(value, bool):
                    return value
            except Exception:
                pass
            return None
        except Exception as exception:
            logger.exception("[BLOCKCHAIN][SOLANA][SIGNER] is_blockhash_valid failed — %s", exception)
            return None

    def _sign_versioned_bytes(self, raw_bytes: bytes) -> bytes:
        try:
            versioned_transaction = VersionedTransaction.from_bytes(raw_bytes)
        except Exception as exception:
            raise ValueError(f"Payload is not a valid VersionedTransaction: {exception}") from exception

        message = versioned_transaction.message

        try:
            signed_versioned_transaction = VersionedTransaction(message, [self.keypair])
            signed_bytes = bytes(signed_versioned_transaction)
            logger.debug("[BLOCKCHAIN][SOLANA][SIGNER] Signed using constructor(keypairs)")
            return signed_bytes
        except Exception as exception_constructor_keypair:
            logger.exception("[BLOCKCHAIN][SOLANA][SIGNER] constructor(keypairs) path failed: %s", exception_constructor_keypair)

        try:
            manual_signature: Signature = self.keypair.sign_message(bytes(message))
            presigner = Presigner(self.keypair.pubkey(), manual_signature)
            signed_versioned_transaction = VersionedTransaction(message, [presigner])
            signed_bytes = bytes(signed_versioned_transaction)
            logger.debug("[BLOCKCHAIN][SOLANA][SIGNER] Signed using constructor(Presigner)")
            return signed_bytes
        except Exception as exception_constructor_presigner:
            raise ValueError(
                f"[BLOCKCHAIN][SOLANA][SIGNER] Could not sign VersionedTransaction using any method. "
                f"ctor(keypairs): {exception_constructor_keypair!r} | ctor(presigner): {exception_constructor_presigner!r}"
            ) from exception_constructor_presigner

    def send_raw_transaction(self, raw_bytes: bytes) -> str:
        if len(raw_bytes) == 0:
            raise ValueError("Raw transaction payload is empty")

        logger.info("[BLOCKCHAIN][SOLANA][SIGNER] Preparing to sign+broadcast serialized transaction (bytes=%d)", len(raw_bytes))

        try:
            parsed = VersionedTransaction.from_bytes(raw_bytes)
            blockhash_text = self._recent_blockhash_str_from_message(parsed.message)
            valid = self._is_blockhash_valid(blockhash_text)
            if valid is False:
                raise ValueError(
                    f"[BLOCKCHAIN][SOLANA][SIGNER][STALE_BLOCKHASH] The route's recent blockhash is no longer valid "
                    f"({blockhash_text}). Rebuild the LI.FI transaction and retry."
                )
            if valid is True:
                logger.debug("[BLOCKCHAIN][SOLANA][SIGNER] Recent blockhash is valid: %s", blockhash_text)
        except Exception as exception_check:
            logger.exception("[BLOCKCHAIN][SOLANA][SIGNER] Pre-send blockhash check skipped (%s)", exception_check)

        signed_payload = self._sign_versioned_bytes(raw_bytes)

        response = self.client.send_raw_transaction(
            signed_payload,
            opts=TxOpts(skip_preflight=True, max_retries=5, preflight_commitment="processed"),
        )
        signature = self._extract_signature(response)
        logger.info("[BLOCKCHAIN][SOLANA][SIGNER] Broadcasted signature %s", signature)
        return signature


def build_default_solana_signer() -> SolanaSigner:
    configuration = SolanaSignerConfiguration(
        rpc_url=settings.SOLANA_RPC_URL,
        mnemonic=settings.WALLET_MNEMONIC,
        wallet_derivation_index=settings.WALLET_DERIVATION_INDEX
    )
    return SolanaSigner(configuration)
