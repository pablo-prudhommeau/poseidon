from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bip_utils import Bip39SeedGenerator, Bip32Slip10Ed25519
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.presigner import Presigner
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError

try:
    from solders.rpc.responses import SendTransactionResp
except Exception:
    SendTransactionResp = object

from src.configuration.config import settings
from src.integrations.blockchain.solana.solana_structures import (
    SolanaTransactionConfirmationResult,
    SolanaTransactionFeeBreakdown,
)
from src.integrations.blockchain.solana.solana_utils import (
    resolve_blockchain_transaction_failure_reason_from_confirmation_error,
)
from src.integrations.blockchain.solana.solana_rpc_client import (
    resolve_sol_usd_price,
    rpc_get_signature_statuses,
    rpc_send_transaction,
)
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

        logger.info(
            "[BLOCKCHAIN][SOLANA][SIGNER] Signer initialized — blockchain_network=%s wallet_address=%s",
            BlockchainNetwork.SOLANA.value,
            self.keypair.pubkey(),
        )

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
            swap_fee_usd = 0.0
        else:
            total_usd = total_sol * sol_usd
            base_sol = base_fee_lamports / 1_000_000_000.0
            swap_fee_usd = base_sol * sol_usd

        breakdown = SolanaTransactionFeeBreakdown(
            base_fee_lamports=base_fee_lamports,
            account_rent_lamports=account_rent_lamports,
            total_lamports=total_lamports,
            total_sol=total_sol,
            total_usd=total_usd,
            swap_fee_usd=swap_fee_usd,
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
            logger.debug("[BLOCKCHAIN][SOLANA][SIGNER] Blockhash validity check failed — error=%s", exception)
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
            logger.debug(
                "[BLOCKCHAIN][SOLANA][SIGNER] Signing path failed — signing_path=constructor_keypairs error=%s",
                exception_constructor_keypair,
            )

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

        logger.debug(
            "[BLOCKCHAIN][SOLANA][SIGNER] Preparing transaction signing and broadcast — "
            "blockchain_network=%s transaction_payload_bytes=%d",
            BlockchainNetwork.SOLANA.value,
            len(raw_bytes),
        )

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
                logger.debug(
                    "[BLOCKCHAIN][SOLANA][SIGNER] Recent blockhash validated — recent_blockhash=%s",
                    blockhash_text,
                )
        except Exception as exception_check:
            logger.debug(
                "[BLOCKCHAIN][SOLANA][SIGNER] Pre-send blockhash check skipped — reason=%s",
                exception_check,
            )

        signed_payload = self._sign_versioned_bytes(raw_bytes)

        signature = rpc_send_transaction(self._rpc_url, signed_payload)
        logger.info(
            "[BLOCKCHAIN][SOLANA][SIGNER] Transaction broadcasted — "
            "blockchain_network=%s transaction_signature=%s",
            BlockchainNetwork.SOLANA.value,
            signature,
        )
        return signature

    def confirm_transaction(self, signature_str: str, timeout_seconds: int = 45) -> SolanaTransactionConfirmationResult:
        import time
        from solders.signature import Signature

        try:
            signature_obj = Signature.from_string(signature_str)
        except Exception:
            failure_reason = resolve_blockchain_transaction_failure_reason_from_confirmation_error(
                raw_error_text="invalid_signature",
                confirmation_timed_out=False,
            )
            return SolanaTransactionConfirmationResult(
                is_confirmed=False,
                failure_reason=failure_reason,
                raw_error_text="invalid_signature",
            )

        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                statuses = rpc_get_signature_statuses(self._rpc_url, [signature_str])
                if statuses and len(statuses) > 0 and statuses[0] is not None:
                    status = statuses[0]
                    status_error = status.get("err")
                    if status_error is not None:
                        raw_error_text = str(status_error)
                        failure_reason = resolve_blockchain_transaction_failure_reason_from_confirmation_error(
                            raw_error_text=raw_error_text,
                            confirmation_timed_out=False,
                        )
                        logger.warning(
                            "[BLOCKCHAIN][SOLANA][SIGNER] Transaction confirmation failed — "
                            "transaction_signature=%s failure_reason=%s error=%s",
                            signature_str,
                            failure_reason.value,
                            raw_error_text,
                        )
                        return SolanaTransactionConfirmationResult(
                            is_confirmed=False,
                            failure_reason=failure_reason,
                            raw_error_text=raw_error_text,
                        )

                    confirmation_status = str(status.get("confirmationStatus", ""))
                    if "confirmed" in confirmation_status.lower() or "finalized" in confirmation_status.lower():
                        return SolanaTransactionConfirmationResult(
                            is_confirmed=True,
                            failure_reason=None,
                            raw_error_text="",
                        )
            except BlockchainRpcUnavailableError as rpc_unavailable_error:
                logger.debug(
                    "[BLOCKCHAIN][SOLANA][SIGNER] RPC unavailable while checking transaction confirmation status — "
                    "transaction_signature=%s failure_reason=%s",
                    signature_str,
                    rpc_unavailable_error.failure_reason.value,
                )
            except Exception as exception:
                logger.debug(
                    "[BLOCKCHAIN][SOLANA][SIGNER] Error while checking transaction confirmation status — "
                    "transaction_signature=%s error=%s",
                    signature_str,
                    exception,
                )

            time.sleep(2.0)

        logger.warning(
            "[BLOCKCHAIN][SOLANA][SIGNER] Transaction confirmation timed out — "
            "transaction_signature=%s timeout_seconds=%d",
            signature_str,
            timeout_seconds,
        )
        failure_reason = resolve_blockchain_transaction_failure_reason_from_confirmation_error(
            raw_error_text="",
            confirmation_timed_out=True,
        )
        return SolanaTransactionConfirmationResult(
            is_confirmed=False,
            failure_reason=failure_reason,
            raw_error_text="confirmation_timeout",
        )

    def broadcast_presigned_transaction(self, signed_raw_bytes: bytes) -> str:
        if len(signed_raw_bytes) == 0:
            raise ValueError("Signed transaction payload is empty")

        signature = rpc_send_transaction(self._rpc_url, signed_raw_bytes)
        logger.info(
            "[BLOCKCHAIN][SOLANA][SIGNER] Presigned transaction broadcasted — "
            "blockchain_network=%s transaction_signature=%s",
            BlockchainNetwork.SOLANA.value,
            signature,
        )
        return signature


def build_default_solana_signer() -> SolanaSigner:
    from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
    configuration = SolanaSignerConfiguration(
        rpc_url=resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA),
        mnemonic=settings.WALLET_MNEMONIC,
        wallet_derivation_index=settings.WALLET_DERIVATION_INDEX
    )
    return SolanaSigner(configuration)
