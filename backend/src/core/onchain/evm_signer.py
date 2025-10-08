from __future__ import annotations

"""
EVM signer using eth-account HD wallet (Option B).

Design goals:
- No bip-utils; rely solely on eth-account for BIP-32/44 derivation.
- Derive account at m/44'/60'/0'/0/{index}.
- Build and sign EIP-1559 transactions with dynamic fees.
- Never log secrets or raw calldata.

Environment:
- settings.EVM_RPC_URL
- settings.EVM_MNEMONIC
- settings.EVM_DERIVATION_INDEX
"""

from dataclasses import dataclass
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.types import TxParams

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class EvmSignerConfig:
    rpc_url: str
    mnemonic: str
    derivation_index: int = 0


class EvmSigner:
    """Sign and broadcast EVM transactions derived from a mnemonic using eth-account."""

    def __init__(self, config: EvmSignerConfig) -> None:
        if not config.rpc_url or not config.mnemonic:
            raise ValueError("EVM signer requires RPC URL and mnemonic (set via environment variables).")

        self.web3 = Web3(Web3.HTTPProvider(config.rpc_url, request_kwargs={"timeout": 30}))
        if not self.web3.is_connected():
            raise RuntimeError("Failed to connect to EVM RPC endpoint.")

        Account.enable_unaudited_hdwallet_features()
        account_path = f"m/44'/60'/0'/0/{config.derivation_index}"
        self.account: LocalAccount = Account.from_mnemonic(config.mnemonic, account_path=account_path)
        self.address: str = self.account.address

        log.info("EVM signer initialized. Address=%s ChainId=%s", self.address, self.web3.eth.chain_id)

    def _build_eip1559(self, to: str, data: bytes | str, value_wei: int | None, gas_limit: Optional[int]) -> TxParams:
        """Construct a typed EIP-1559 transaction with dynamic fees and filled nonce."""
        latest = self.web3.eth.get_block("latest")
        base_fee = int(latest.get("baseFeePerGas") or 0)
        try:
            max_priority = int(self.web3.eth.max_priority_fee)  # node suggestion
        except Exception:
            max_priority = int(Web3.to_wei(1, "gwei"))
        max_fee = base_fee * 2 + max_priority

        nonce = self.web3.eth.get_transaction_count(self.address)
        tx: TxParams = {
            "chainId": self.web3.eth.chain_id,
            "type": 2,
            "nonce": nonce,
            "to": Web3.to_checksum_address(to),
            "data": data,
            "value": int(value_wei or 0),
            "maxPriorityFeePerGas": max_priority,
            "maxFeePerGas": int(max_fee),
        }
        if gas_limit is not None:
            tx["gas"] = int(gas_limit)
        else:
            try:
                estimated = self.web3.eth.estimate_gas(
                    {"from": self.address, "to": tx["to"], "data": tx["data"], "value": tx["value"]})
                tx["gas"] = int(estimated)
            except Exception as exc:
                log.warning("EVM gas estimation failed (%s). Falling back to static headroom.", exc)
                tx["gas"] = 400000
        log.debug("EVM tx skeleton built: nonce=%s gas=%s maxFeePerGas=%s", tx.get("nonce"), tx.get("gas"),
                  tx.get("maxFeePerGas"))
        return tx

    def send_transaction(self, to: str, data: str, value_wei: int | None, gas_limit: Optional[int] = None) -> str:
        """
        Sign and broadcast a transaction. Returns the hex transaction hash.
        """
        log.info("EVM: preparing transaction to %s", to)
        tx = self._build_eip1559(to=to, data=data, value_wei=value_wei, gas_limit=gas_limit)

        signed = self.account.sign_transaction(tx)

        # web3/eth-account v5 -> rawTransaction ; v6 -> raw_transaction
        raw = getattr(signed, "rawTransaction", None)
        if raw is None:
            raw = getattr(signed, "raw_transaction", None)
        if raw is None:
            # quelques builds exposent 'raw' ; sinon on échoue proprement
            raw = getattr(signed, "raw", None)
        if raw is None:
            raise RuntimeError("SignedTransaction does not expose raw bytes on this web3/eth-account version.")

        tx_hash = self.web3.eth.send_raw_transaction(raw)
        hex_hash = tx_hash.hex()
        log.info("EVM: broadcasted transaction %s", hex_hash)
        return hex_hash


def build_default_evm_signer() -> EvmSigner:
    """Factory using Settings for convenience."""
    cfg = EvmSignerConfig(
        rpc_url=settings.EVM_RPC_URL,
        mnemonic=settings.EVM_MNEMONIC,
        derivation_index=settings.EVM_DERIVATION_INDEX,
    )
    return EvmSigner(cfg)

