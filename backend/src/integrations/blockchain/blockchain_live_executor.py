from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import base58

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_structures import TradingEvmRoute, TradingSolanaRoute
from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer, EvmSigner
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer, SolanaSigner
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


@dataclass(frozen=True)
class BlockchainExecutionResult:
    network: BlockchainNetwork
    transaction_hash_or_signature: str


class LiveExecutionService:
    def __init__(self) -> None:
        self._solana_signer: Optional[SolanaSigner] = None
        self._evm_signer: Optional[EvmSigner] = None

    async def close(self) -> None:
        return

    async def solana_execute_route(self, route: TradingSolanaRoute) -> str:
        serialized_base64 = route.serialized_transaction_base64
        serialized = self._decode_blob(serialized_base64)
        if not isinstance(serialized, bytes) or len(serialized) == 0:
            raise ValueError("Invalid Solana serialized transaction payload")

        if self._solana_signer is None:
            self._solana_signer = build_default_solana_signer()

        logger.info("[BLOCKCHAIN][EXECUTOR][SOL] Broadcasting serialized transaction (bytes=%d)", len(serialized))
        signature = self._solana_signer.send_raw_transaction(serialized)
        logger.info("[BLOCKCHAIN][EXECUTOR][SOL] Broadcast success — signature=%s. Waiting for confirmation...", signature)

        is_confirmed = await asyncio.to_thread(self._solana_signer.confirm_transaction, signature, 45)
        if not is_confirmed:
            raise RuntimeError(f"Solana transaction {signature} failed during on-chain execution or timed out")

        logger.info("[BLOCKCHAIN][EXECUTOR][SOL] Confirmation success — signature=%s", signature)
        return signature

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

    async def evm_execute_route(self, route: TradingEvmRoute, chain: BlockchainNetwork) -> str:
        transaction_request = route.transaction_request
        if transaction_request is None:
            raise ValueError("Missing transaction_request for EVM route")

        raw_rlp = transaction_request.raw_transaction
        if isinstance(raw_rlp, str) and len(raw_rlp) > 0:
            from web3 import Web3
            from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
            provider = Web3.HTTPProvider(resolve_rpc_url_for_chain(chain))
            web3 = Web3(provider)
            tx_hash = web3.eth.send_raw_transaction(bytes.fromhex(raw_rlp.removeprefix("0x")))
            hex_hash = tx_hash.hex()
            logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Broadcast success — tx=%s. Waiting for confirmation...", hex_hash)

            if self._evm_signer is None:
                self._evm_signer = build_default_evm_signer(chain=chain)

            is_confirmed = await asyncio.to_thread(self._evm_signer.confirm_transaction, hex_hash, 45)
            if not is_confirmed:
                raise RuntimeError(f"EVM transaction {hex_hash} failed during on-chain execution or timed out")

            logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Confirmation success — tx=%s", hex_hash)
            return hex_hash

        to = transaction_request.to
        data = transaction_request.data
        value = transaction_request.value
        gas = transaction_request.gas

        if not isinstance(to, str) or len(to) == 0 or not isinstance(data, str) or len(data) == 0:
            raise ValueError("Unsupported EVM route shape: missing 'to' or 'data' in transactionRequest")

        value_wei: Optional[int] = None
        if isinstance(value, int):
            value_wei = value
        elif isinstance(value, str) and len(value) > 0:
            value_wei = int(value, 16) if value.startswith("0x") else int(value)

        gas_limit: Optional[int] = None
        if isinstance(gas, int):
            gas_limit = gas
        elif isinstance(gas, str) and len(gas) > 0:
            gas_limit = int(gas, 16) if gas.startswith("0x") else int(gas)

        if self._evm_signer is None:
            self._evm_signer = build_default_evm_signer(chain=chain)

        logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Signing and broadcasting via local signer (to=%s)", to)
        transaction_hash_hex = self._evm_signer.broadcast_transaction(recipient_address=to, transaction_data_hex=data, value_in_wei=value_wei, gas_limit=gas_limit)
        logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Broadcast success — tx=%s. Waiting for confirmation...", transaction_hash_hex)

        is_confirmed = await asyncio.to_thread(self._evm_signer.confirm_transaction, transaction_hash_hex, 45)
        if not is_confirmed:
            raise RuntimeError(f"EVM transaction {transaction_hash_hex} failed during on-chain execution or timed out")

        logger.info("[BLOCKCHAIN][EXECUTOR][EVM] Confirmation success — tx=%s", transaction_hash_hex)
        return transaction_hash_hex
