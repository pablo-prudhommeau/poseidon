from __future__ import annotations
"""
EVM signer using eth-account HD wallet (Option B).

Goals
-----
- Derive an account from a BIP-44 path (m/44'/60'/0'/0/{index}) using eth-account only.
- Build and sign transactions:
  * Prefer EIP-1559 if the caller provides maxFeePerGas / maxPriorityFeePerGas.
  * Fall back to legacy type-0 if the caller provides gasPrice only.
  * Otherwise, compute dynamic EIP-1559 fees from the node.
- Allow the caller (LiveExecutionService) to override gas limit, fees, nonce and chainId.
- Never log secrets or raw calldata.

Environment
-----------
- settings.EVM_RPC_URL
- settings.EVM_MNEMONIC
- settings.EVM_DERIVATION_INDEX
"""

from dataclasses import dataclass
from typing import Optional, Union, Dict, Any

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

        # Enable HD wallet derivation and derive the target account
        Account.enable_unaudited_hdwallet_features()
        account_path = f"m/44'/60'/0'/0/{config.derivation_index}"
        self.account: LocalAccount = Account.from_mnemonic(config.mnemonic, account_path=account_path)
        self.address: str = self.account.address
        self.chain_id: int = int(self.web3.eth.chain_id)

        log.info("EVM signer initialized. Address=%s ChainId=%s", self.address, self.chain_id)

    # --------------------------------------------------------------------- #
    # Fee helpers
    # --------------------------------------------------------------------- #

    def _suggest_eip1559_fees(self) -> Dict[str, int]:
        """
        Return a dict with EIP-1559 fees: {'maxPriorityFeePerGas': int, 'maxFeePerGas': int}.
        Uses node hints when available, otherwise applies a safe fallback.
        """
        latest = self.web3.eth.get_block("latest")
        base_fee = int(latest.get("baseFeePerGas") or 0)

        try:
            # Some nodes expose a suggested priority fee
            max_priority = int(self.web3.eth.max_priority_fee)
        except Exception:
            max_priority = int(Web3.to_wei(1, "gwei"))

        # Safe cap: 2 * base + tip
        max_fee = base_fee * 2 + max_priority
        return {"maxPriorityFeePerGas": max_priority, "maxFeePerGas": int(max_fee)}

    # --------------------------------------------------------------------- #
    # Transaction builders
    # --------------------------------------------------------------------- #

    def _build_tx(
            self,
            *,
            to: str,
            data: Union[str, bytes],
            value_wei: Optional[int],
            gas_limit: Optional[int],
            gas_price_wei: Optional[int],
            max_fee_per_gas_wei: Optional[int],
            max_priority_fee_per_gas_wei: Optional[int],
            nonce: Optional[int],
            chain_id: Optional[int],
    ) -> TxParams:
        """
        Build a transaction dict respecting the caller's overrides.

        Priority:
        - If EIP-1559 fees provided (maxFeePerGas or maxPriority), build type 2 (EIP-1559).
        - Else if legacy gasPrice provided, build legacy type-0.
        - Else compute EIP-1559 fees dynamically and build type 2.

        Gas limit:
        - Use provided gas_limit when set.
        - Else estimate and fallback to a conservative static value if estimation fails.
        """
        to_checksum = Web3.to_checksum_address(to)
        tx: TxParams = {
            "to": to_checksum,
            "data": data,
            "value": int(value_wei or 0),
        }

        # Nonce & chain id
        tx["nonce"] = int(nonce) if nonce is not None else self.web3.eth.get_transaction_count(self.address)
        tx["chainId"] = int(chain_id) if chain_id is not None else self.chain_id
        if chain_id is not None and int(chain_id) != self.chain_id:
            log.warning("EVM signer chainId=%s overridden by route chainId=%s", self.chain_id, chain_id)

        # Fee model selection
        if max_fee_per_gas_wei is not None or max_priority_fee_per_gas_wei is not None:
            # EIP-1559 explicit
            fees = {
                "maxPriorityFeePerGas": int(max_priority_fee_per_gas_wei or 0),
                "maxFeePerGas": int(max_fee_per_gas_wei or 0),
            }
            # If one is missing, fill from suggestion
            if fees["maxPriorityFeePerGas"] <= 0 or fees["maxFeePerGas"] <= 0:
                suggested = self._suggest_eip1559_fees()
                fees["maxPriorityFeePerGas"] = fees["maxPriorityFeePerGas"] or suggested["maxPriorityFeePerGas"]
                fees["maxFeePerGas"] = fees["maxFeePerGas"] or suggested["maxFeePerGas"]
            tx.update({"type": 2, **fees})
        elif gas_price_wei is not None:
            # Legacy (type-0)
            tx.update({"gasPrice": int(gas_price_wei), "type": 0})
        else:
            # Dynamic EIP-1559
            tx.update({"type": 2, **self._suggest_eip1559_fees()})

        # Gas limit
        if gas_limit is not None:
            tx["gas"] = int(gas_limit)
        else:
            try:
                tx["gas"] = int(
                    self.web3.eth.estimate_gas(
                        {"from": self.address, "to": to_checksum, "data": data, "value": tx["value"]}
                    )
                )
            except Exception as exc:
                log.warning("EVM gas estimation failed (%s). Falling back to static headroom.", exc)
                tx["gas"] = 400_000

        log.debug(
            "EVM tx built: nonce=%s chainId=%s to=%s valueWei=%s gas=%s type=%s gp=%s mf=%s mp=%s",
            tx.get("nonce"),
            tx.get("chainId"),
            to_checksum,
            tx.get("value"),
            tx.get("gas"),
            tx.get("type"),
            tx.get("gasPrice"),
            tx.get("maxFeePerGas"),
            tx.get("maxPriorityFeePerGas"),
        )
        return tx

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def send_transaction(
            self,
            *,
            to: str,
            data: Union[str, bytes],
            value_wei: Optional[int] = None,
            gas_limit: Optional[int] = None,
            gas_price_wei: Optional[int] = None,
            max_fee_per_gas_wei: Optional[int] = None,
            max_priority_fee_per_gas_wei: Optional[int] = None,
            nonce: Optional[int] = None,
            chain_id: Optional[int] = None,
    ) -> str:
        """
        Sign and broadcast a transaction. Returns the hex transaction hash.

        Parameters
        ----------
        to : str
            Destination contract address.
        data : bytes | str
            Calldata (0x-hex or raw bytes).
        value_wei : int | None
            Native value (wei).
        gas_limit : int | None
            Explicit gas limit.
        gas_price_wei : int | None
            Legacy gas price (type-0). If provided, overrides EIP-1559.
        max_fee_per_gas_wei : int | None
            EIP-1559 max fee (type-2). If provided, EIP-1559 is used.
        max_priority_fee_per_gas_wei : int | None
            EIP-1559 priority fee (type-2). If provided, EIP-1559 is used.
        nonce : int | None
            Explicit nonce.
        chain_id : int | None
            Explicit chain id.

        Notes
        -----
        - If both EIP-1559 fees and gasPrice are omitted, dynamic EIP-1559 fees are computed.
        - If only one EIP-1559 fee is given, the other is auto-filled from node suggestions.
        """
        log.info("EVM: preparing transaction to %s", to)

        tx = self._build_tx(
            to=to,
            data=data,
            value_wei=value_wei,
            gas_limit=gas_limit,
            gas_price_wei=gas_price_wei,
            max_fee_per_gas_wei=max_fee_per_gas_wei,
            max_priority_fee_per_gas_wei=max_priority_fee_per_gas_wei,
            nonce=nonce,
            chain_id=chain_id,
        )

        signed = self.account.sign_transaction(tx)
        tx_hash = self.web3.eth.send_raw_transaction(signed.rawTransaction)
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
