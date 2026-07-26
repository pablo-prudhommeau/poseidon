from __future__ import annotations

import asyncio
from typing import Optional

import base58
from web3 import Web3

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.blockchain_execution_structures import (
    BlockchainExecutionResult,
    BlockchainTransactionExecutionError,
    BlockchainTransactionFailureReason,
)
from src.integrations.blockchain.blockchain_rpc_registry import (
    resolve_rpc_url_for_chain,
    resolve_web3_provider_for_chain,
)
from src.integrations.blockchain.blockchain_structures import BlockchainEvmRoute, BlockchainSolanaRoute
from src.integrations.blockchain.blockchain_utils import normalize_evm_transaction_hash
from src.integrations.blockchain.evm.blockchain_evm_price_reader import read_evm_native_token_price_usd
from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer, EvmSigner
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer, SolanaSigner
from src.integrations.lifi.lifi_helpers import parse_lifi_hex_or_decimal_integer
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class BlockchainExecutionService:
    def __init__(self) -> None:
        self._solana_signer: Optional[SolanaSigner] = None
        self._evm_signer: Optional[EvmSigner] = None

    async def close(self) -> None:
        return

    async def solana_execute_route(self, route: BlockchainSolanaRoute) -> BlockchainExecutionResult:
        serialized_base64 = route.serialized_transaction_base64
        serialized = self._decode_blob(serialized_base64)
        if not isinstance(serialized, bytes) or len(serialized) == 0:
            raise ValueError("Invalid Solana serialized transaction payload")

        if self._solana_signer is None:
            self._solana_signer = build_default_solana_signer()

        logger.info("[BLOCKCHAIN][EXECUTOR][SOL] Broadcasting serialized transaction (bytes=%d)", len(serialized))
        signature = self._solana_signer.send_raw_transaction(serialized)
        logger.info("[BLOCKCHAIN][EXECUTOR][SOL] Broadcast success — signature=%s. Waiting for confirmation...", signature)

        confirmation_result = await asyncio.to_thread(self._solana_signer.confirm_transaction, signature)
        if not confirmation_result.is_confirmed:
            failure_reason = confirmation_result.failure_reason
            if failure_reason is None:
                failure_reason = BlockchainTransactionFailureReason.UNKNOWN
            raise BlockchainTransactionExecutionError(
                message=f"Solana transaction {signature} failed during on-chain execution or timed out",
                transaction_signature=signature,
                failure_reason=failure_reason,
                raw_error_text=confirmation_result.raw_error_text,
            )

        logger.info("[BLOCKCHAIN][EXECUTOR][SOL] Confirmation success — signature=%s", signature)

        fee_breakdown = await asyncio.to_thread(
            self._solana_signer.fetch_confirmed_transaction_fee_breakdown_usd,
            signature,
        )
        fee_usd = 0.0 if fee_breakdown is None else fee_breakdown.swap_fee_usd
        return BlockchainExecutionResult(
            network=BlockchainNetwork.SOLANA,
            transaction_hash_or_signature=signature,
            transaction_fee_usd=fee_usd,
        )

    @staticmethod
    def _decode_blob(raw: str) -> bytes:
        if not isinstance(raw, str) or len(raw) == 0:
            return b""

        try:
            import base64 as _b64
            decoded = _b64.b64decode(raw, validate=True)
            if len(decoded) > 0:
                return decoded
        except Exception:
            pass

        try:
            decoded = base58.b58decode(raw)
            if len(decoded) > 0:
                return decoded
        except Exception:
            pass

        try:
            hex_str = raw[2:] if raw.startswith("0x") else raw
            decoded = bytes.fromhex(hex_str)
            if len(decoded) > 0:
                return decoded
        except Exception:
            pass

        return b""

    async def evm_execute_route(self, route: BlockchainEvmRoute, chain: BlockchainNetwork) -> BlockchainExecutionResult:
        transaction_request = route.transaction_request
        if self._evm_signer is None:
            self._evm_signer = build_default_evm_signer(chain=chain)

        request_from_address = transaction_request.from_address
        if request_from_address is None or not request_from_address.strip():
            raise ValueError("Missing from address on EVM transaction request")
        if request_from_address.lower() != self._evm_signer.wallet_address.lower():
            raise ValueError(
                f"LiFi transaction from address {request_from_address} does not match local wallet "
                f"{self._evm_signer.wallet_address}",
            )

        raw_rlp = transaction_request.raw_transaction
        if isinstance(raw_rlp, str) and len(raw_rlp) > 0:
            web3_provider = resolve_web3_provider_for_chain(chain)
            if web3_provider is None:
                rpc_url = resolve_rpc_url_for_chain(chain)
                web3_provider = Web3(Web3.HTTPProvider(rpc_url))
            tx_hash = web3_provider.eth.send_raw_transaction(bytes.fromhex(raw_rlp.removeprefix("0x")))
            hex_hash = normalize_evm_transaction_hash(tx_hash)
            logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Broadcast success — tx=%s. Waiting for confirmation...", hex_hash)

            is_confirmed = await asyncio.to_thread(self._evm_signer.confirm_transaction, hex_hash)
            if not is_confirmed:
                raise BlockchainTransactionExecutionError(
                    message=f"EVM transaction {hex_hash} failed during on-chain execution or timed out",
                    transaction_signature=hex_hash,
                    failure_reason=BlockchainTransactionFailureReason.UNKNOWN,
                    raw_error_text=f"confirmation_failed:{hex_hash}",
                )

            logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Confirmation success — tx=%s", hex_hash)
            transaction_fee_usd = await asyncio.to_thread(
                self._resolve_evm_transaction_fee_usd,
                chain,
                hex_hash,
            )
            return BlockchainExecutionResult(
                network=chain,
                transaction_hash_or_signature=hex_hash,
                transaction_fee_usd=transaction_fee_usd,
            )

        to = transaction_request.to
        data = transaction_request.data
        value = transaction_request.value

        if not isinstance(to, str) or len(to) == 0 or not isinstance(data, str) or len(data) == 0:
            raise ValueError("Unsupported EVM route shape: missing 'to' or 'data' in transactionRequest")

        value_wei: Optional[int] = None
        if isinstance(value, int):
            value_wei = value
        elif isinstance(value, str) and len(value) > 0:
            value_wei = parse_lifi_hex_or_decimal_integer(value)

        gas_limit: Optional[int] = None
        if transaction_request.gas_limit is not None and transaction_request.gas_limit.strip():
            gas_limit = parse_lifi_hex_or_decimal_integer(transaction_request.gas_limit)

        logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Signing and broadcasting via local signer (to=%s)", to)
        transaction_hash_hex = self._evm_signer.broadcast_transaction(
            recipient_address=to,
            transaction_data_hex=data,
            value_in_wei=value_wei,
            gas_limit=gas_limit,
        )
        logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Broadcast success — tx=%s. Waiting for confirmation...", transaction_hash_hex)

        is_confirmed = await asyncio.to_thread(self._evm_signer.confirm_transaction, transaction_hash_hex)
        if not is_confirmed:
            raise BlockchainTransactionExecutionError(
                message=f"EVM transaction {transaction_hash_hex} failed during on-chain execution or timed out",
                transaction_signature=transaction_hash_hex,
                failure_reason=BlockchainTransactionFailureReason.UNKNOWN,
                raw_error_text=f"confirmation_failed:{transaction_hash_hex}",
            )

        logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Confirmation success — tx=%s", transaction_hash_hex)
        transaction_fee_usd = await asyncio.to_thread(
            self._resolve_evm_transaction_fee_usd,
            chain,
            transaction_hash_hex,
        )
        return BlockchainExecutionResult(
            network=chain,
            transaction_hash_or_signature=transaction_hash_hex,
            transaction_fee_usd=transaction_fee_usd,
        )

    def _resolve_evm_transaction_fee_usd(
            self,
            blockchain_network: BlockchainNetwork,
            transaction_hash_hex: str,
    ) -> float:
        if self._evm_signer is None:
            return 0.0
        try:
            receipt = self._evm_signer.web3_provider.eth.get_transaction_receipt(transaction_hash_hex)
            gas_used = int(receipt["gasUsed"])
            effective_gas_price_wei = int(receipt.get("effectiveGasPrice") or 0)
            if effective_gas_price_wei <= 0:
                transaction = self._evm_signer.web3_provider.eth.get_transaction(transaction_hash_hex)
                effective_gas_price_wei = int(transaction.get("gasPrice") or 0)
            if gas_used <= 0 or effective_gas_price_wei <= 0:
                return 0.0
            fee_native = float(Web3.from_wei(gas_used * effective_gas_price_wei, "ether"))
            native_price_usd = read_evm_native_token_price_usd(
                self._evm_signer.web3_provider,
                blockchain_network,
            )
            if native_price_usd is None or native_price_usd <= 0.0:
                return 0.0
            return fee_native * native_price_usd
        except Exception:
            logger.exception(
                "[BLOCKCHAIN][EXECUTOR][EVM] Failed to resolve transaction fee usd — tx=%s chain=%s",
                transaction_hash_hex,
                blockchain_network.value,
            )
            return 0.0
