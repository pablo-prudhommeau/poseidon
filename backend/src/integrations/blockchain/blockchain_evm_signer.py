from __future__ import annotations

from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from pydantic import BaseModel
from web3 import Web3
from web3.types import TxParams

from src.configuration.config import settings
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class EvmSignerConfiguration(BaseModel):
    rpc_endpoint_url: str
    security_mnemonic_phrase: str
    wallet_derivation_index: int = 0


class EvmSigner:
    def __init__(self, configuration: EvmSignerConfiguration) -> None:
        if not configuration.rpc_endpoint_url or not configuration.security_mnemonic_phrase:
            raise ValueError("[BLOCKCHAIN][EVM][SIGNER] Initialization failed: RPC URL and mnemonic phrase are strictly required")

        self.web3_provider = Web3(Web3.HTTPProvider(configuration.rpc_endpoint_url, request_kwargs={"timeout": 30}))

        if not self.web3_provider.is_connected():
            raise RuntimeError(f"[BLOCKCHAIN][EVM][SIGNER] Could not establish connection to RPC endpoint: {configuration.rpc_endpoint_url}")

        Account.enable_unaudited_hdwallet_features()

        derivation_path = f"m/44'/60'/0'/0/{configuration.wallet_derivation_index}"
        self.local_account: LocalAccount = Account.from_mnemonic(
            mnemonic=configuration.security_mnemonic_phrase,
            account_path=derivation_path
        )
        self.wallet_address: str = self.local_account.address

        logger.info(
            "[BLOCKCHAIN][EVM][SIGNER] Signer successfully initialized. Address: %s | ChainId: %s",
            self.wallet_address,
            self.web3_provider.eth.chain_id
        )

    def _build_eip1559_transaction_payload(
            self,
            recipient_address: str,
            transaction_data_hex: str | bytes,
            value_in_wei: Optional[int],
            forced_gas_limit: Optional[int]
    ) -> TxParams:
        latest_block = self.web3_provider.eth.get_block("latest")
        network_base_fee = int(latest_block.get("baseFeePerGas") or 0)

        try:
            max_priority_fee = int(self.web3_provider.eth.max_priority_fee)
        except Exception:
            max_priority_fee = Web3.to_wei(1, "gwei")

        total_max_fee_per_gas = (network_base_fee * 2) + max_priority_fee
        current_nonce = self.web3_provider.eth.get_transaction_count(self.wallet_address)

        transaction_payload: TxParams = {
            "chainId": self.web3_provider.eth.chain_id,
            "type": 2,
            "nonce": current_nonce,
            "to": Web3.to_checksum_address(recipient_address),
            "data": transaction_data_hex,
            "value": value_in_wei if value_in_wei is not None else 0,
            "maxPriorityFeePerGas": max_priority_fee,
            "maxFeePerGas": total_max_fee_per_gas,
        }

        if forced_gas_limit is not None:
            transaction_payload["gas"] = forced_gas_limit
        else:
            try:
                estimated_units = self.web3_provider.eth.estimate_gas({
                    "from": self.wallet_address,
                    "to": transaction_payload["to"],
                    "data": transaction_payload["data"],
                    "value": transaction_payload["value"]
                })
                transaction_payload["gas"] = int(estimated_units * 1.1)
            except Exception as exception:
                logger.warning(
                    "[BLOCKCHAIN][EVM][GAS] Gas estimation failed, falling back to static limit of 400,000 units",
                    exception
                )
                transaction_payload["gas"] = 400000

        logger.debug(
            "[BLOCKCHAIN][EVM][BUILD] Transaction skeleton prepared: Nonce=%s | GasLimit=%s | MaxFee=%s Gwei",
            transaction_payload.get("nonce"),
            transaction_payload.get("gas"),
            Web3.from_wei(transaction_payload.get("maxFeePerGas", 0), "gwei")
        )

        return transaction_payload

    def broadcast_transaction(
            self,
            recipient_address: str,
            transaction_data_hex: str,
            value_in_wei: Optional[int] = None,
            gas_limit: Optional[int] = None
    ) -> str:
        logger.info("[BLOCKCHAIN][EVM][SEND] Preparing to transmit transaction to %s", recipient_address)

        transaction_payload = self._build_eip1559_transaction_payload(
            recipient_address=recipient_address,
            transaction_data_hex=transaction_data_hex,
            value_in_wei=value_in_wei,
            forced_gas_limit=gas_limit
        )

        signed_transaction_envelope = self.local_account.sign_transaction(transaction_payload)

        raw_transaction_bytes = signed_transaction_envelope.rawTransaction

        if not raw_transaction_bytes:
            raise RuntimeError("[BLOCKCHAIN][EVM][SIGN] Critical error: Signed transaction contains no raw bytes")

        transaction_hash_bytes = self.web3_provider.eth.send_raw_transaction(raw_transaction_bytes)
        transaction_hash_hex = transaction_hash_bytes.hex()

        logger.info("[BLOCKCHAIN][EVM][BROADCAST] Transaction successfully broadcasted. Hash: %s", transaction_hash_hex)
        return transaction_hash_hex


def build_default_evm_signer() -> EvmSigner:
    default_configuration = EvmSignerConfiguration(
        rpc_endpoint_url=settings.EVM_RPC_URL,
        security_mnemonic_phrase=settings.WALLET_MNEMONIC,
        wallet_derivation_index=settings.WALLET_DERIVATION_INDEX,
    )
    return EvmSigner(default_configuration)
