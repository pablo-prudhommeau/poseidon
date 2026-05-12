from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bip_utils import Bip39SeedGenerator, Bip32Slip10Ed25519
from solana.rpc.api import Client
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.presigner import Presigner
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from src.core.structures.structures import BlockchainNetwork

try:
    from solders.rpc.responses import SendTransactionResp
except Exception:
    SendTransactionResp = object

from src.configuration.config import settings
from src.integrations.blockchain.solana.solana_structures import SolanaTransactionFeeBreakdown
from src.integrations.blockchain.solana.solana_rpc_client import resolve_sol_usd_price
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
        bip32_node = Bip32Slip10Ed25519.FromSeed(seed)
        derivation_path = f"m/44'/501'/{configuration.wallet_derivation_index}'/0'"
        derived_node = bip32_node.DerivePath(derivation_path)
        raw_private_key = derived_node.PrivateKey().Raw().ToBytes()
        self.keypair = Keypair.from_seed(raw_private_key)
        self._rpc_url = configuration.rpc_url

        logger.info("[BLOCKCHAIN][SOLANA][SIGNER] Initialized signer. Address=%s", self.keypair.pubkey())

    @property
    def address(self) -> str:
        return str(self.keypair.pubkey())

    def fetch_confirmed_transaction_fee_breakdown_usd(self, signature_text: str) -> Optional[SolanaTransactionFeeBreakdown]:
        from solana.rpc.commitment import Confirmed
        from solders.transaction_status import EncodedConfirmedTransactionWithStatusMeta

        try:
            signature_object = Signature.from_string(signature_text)
        except Exception as exception:
            logger.warning("[BLOCKCHAIN][SOLANA][SIGNER][FEE] Invalid signature for fee fetch — %s", exception)
            return None

        try:
            response = self.client.get_transaction(
                signature_object,
                encoding="json",
                commitment=Confirmed,
                max_supported_transaction_version=0,
            )
        except Exception as exception:
            logger.warning("[BLOCKCHAIN][SOLANA][SIGNER][FEE] get_transaction failed for %s — %s", signature_text, exception)
            return None

        confirmed = response.value
        if confirmed is None:
            logger.warning("[BLOCKCHAIN][SOLANA][SIGNER][FEE] No transaction value for signature=%s", signature_text)
            return None

        if not isinstance(confirmed, EncodedConfirmedTransactionWithStatusMeta):
            logger.warning("[BLOCKCHAIN][SOLANA][SIGNER][FEE] Unexpected confirmed transaction type=%s", type(confirmed))
            return None

        encoded_with_meta = confirmed.transaction
        meta = encoded_with_meta.meta
        if meta is None:
            logger.warning("[BLOCKCHAIN][SOLANA][SIGNER][FEE] Missing meta for signature=%s", signature_text)
            return None

        ui_transaction = encoded_with_meta.transaction
        message = ui_transaction.message
        account_key_objects: list = list(message.account_keys)
        loaded = meta.loaded_addresses
        if loaded is not None:
            account_key_objects.extend(list(loaded.writable))
            account_key_objects.extend(list(loaded.readonly))

        signer_text = str(self.keypair.pubkey())
        account_key_texts = [str(key_entry) for key_entry in account_key_objects]

        pre_balances = list(meta.pre_balances)
        post_balances = list(meta.post_balances)
        account_count = min(len(pre_balances), len(post_balances), len(account_key_texts))
        if account_count == 0:
            logger.warning("[BLOCKCHAIN][SOLANA][SIGNER][FEE] Empty balance arrays for signature=%s", signature_text)
            return None

        base_fee_lamports = int(meta.fee)
        account_rent_lamports = 0
        for index in range(account_count):
            if account_key_texts[index] == signer_text:
                continue
            if pre_balances[index] == 0 and post_balances[index] > 0:
                account_rent_lamports += int(post_balances[index])

        total_lamports = base_fee_lamports + account_rent_lamports
        total_sol = total_lamports / 1_000_000_000.0
        sol_usd = resolve_sol_usd_price(self._rpc_url)
        if sol_usd is None or sol_usd <= 0.0:
            logger.warning("[BLOCKCHAIN][SOLANA][SIGNER][FEE] SOL/USD unavailable; fee USD set to 0 for signature=%s", signature_text)
            total_usd = 0.0
        else:
            total_usd = total_sol * sol_usd

        breakdown = SolanaTransactionFeeBreakdown(
            base_fee_lamports=base_fee_lamports,
            account_rent_lamports=account_rent_lamports,
            total_lamports=total_lamports,
            total_sol=total_sol,
            total_usd=total_usd,
        )
        logger.info(
            "[BLOCKCHAIN][SOLANA][SIGNER][FEE] signature=%s base_lamports=%d rent_lamports=%d total_usd=%.6f",
            signature_text,
            base_fee_lamports,
            account_rent_lamports,
            total_usd,
        )
        logger.debug(
            "[BLOCKCHAIN][SOLANA][SIGNER][FEE][VERBOSE] signature=%s total_sol=%.9f sol_usd=%s",
            signature_text,
            total_sol,
            sol_usd,
        )
        return breakdown

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
        constructor_keypair_exception: Exception | None = None

        try:
            signed_versioned_transaction = VersionedTransaction(message, [self.keypair])
            signed_bytes = bytes(signed_versioned_transaction)
            logger.debug("[BLOCKCHAIN][SOLANA][SIGNER] Signed using constructor(keypairs)")
            return signed_bytes
        except Exception as exception_constructor_keypair:
            constructor_keypair_exception = exception_constructor_keypair
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
                f"ctor(keypairs): {constructor_keypair_exception!r} | ctor(presigner): {exception_constructor_presigner!r}"
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

    def confirm_transaction(self, signature_str: str, timeout_seconds: int = 45) -> bool:
        import time
        from solders.signature import Signature

        try:
            signature_obj = Signature.from_string(signature_str)
        except Exception:
            return False

        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                response = self.client.get_signature_statuses([signature_obj])
                if response and hasattr(response, "value"):
                    statuses = response.value
                    if statuses and len(statuses) > 0 and statuses[0] is not None:
                        status = statuses[0]
                        if hasattr(status, "err") and status.err is not None:
                            logger.error("[BLOCKCHAIN][SOLANA][SIGNER] Transaction %s failed with error: %s", signature_str, status.err)
                            return False

                        if hasattr(status, "confirmation_status"):
                            conf_status = str(status.confirmation_status)
                            if "confirmed" in conf_status.lower() or "finalized" in conf_status.lower():
                                return True
            except Exception as exception:
                logger.debug("[BLOCKCHAIN][SOLANA][SIGNER] Error checking status: %s", exception)

            time.sleep(2.0)

        logger.warning("[BLOCKCHAIN][SOLANA][SIGNER] Transaction %s confirmation timed out after %d seconds", signature_str, timeout_seconds)
        return False


def build_default_solana_signer() -> SolanaSigner:
    from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
    configuration = SolanaSignerConfiguration(
        rpc_url=resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA),
        mnemonic=settings.WALLET_MNEMONIC,
        wallet_derivation_index=settings.WALLET_DERIVATION_INDEX
    )
    return SolanaSigner(configuration)
