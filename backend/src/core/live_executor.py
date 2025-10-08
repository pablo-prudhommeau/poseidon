from __future__ import annotations
"""
Live execution service (Option B).

- EVM: consomme un `transactionRequest` LI.FI et exécute la TX.
- Solana: consomme une TX Jupiter sérialisée (base64) et la diffuse.

Ce service ne fait pas de *quote* lui-même : l'appelant doit fournir une route déjà
construite (LI.FI pour EVM, Jupiter pour Solana).

Logs:
- INFO pour les étapes clefs (début exécution, hash).
- DEBUG verbeux pour le parsing et les valeurs numériques.
"""

from typing import Any, Dict, Optional

from src.configuration.config import settings
from src.integrations.lifi_client import resolve_lifi_chain_id  # uniquement pour sanity check éventuel
from src.core.evm_signer import EvmSigner, build_default_evm_signer
from src.core.solana_signer import SolanaSigner, build_default_solana_signer
from src.logging.logger import get_logger

log = get_logger(__name__)


# ======================================================================================
# Helpers
# ======================================================================================

def parse_int_maybe_hex(value: Any) -> Optional[int]:
    """
    Parse an integer that may be provided as:
      - None -> None
      - int  -> returned as-is
      - str decimal ("12345") -> int(…)
      - str hex ("0x1a2b")    -> int(…, 16)

    Returns:
        int or None if value is falsy.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v == "":
            return None
        if v.startswith("0x"):
            return int(v, 16)
        return int(v)
    # Dernier ressort (peu probable) : tenter cast direct
    return int(value)


def _extract_evm_transaction_request(route: Dict[str, Any]) -> Dict[str, Any]:
    """
    LI.FI renvoie généralement un champ `transactionRequest` à la racine de la route.
    On garde la fonction isolée pour gérer facilement les variations si nécessaire.
    """
    tx_req = route.get("transactionRequest")
    if isinstance(tx_req, dict):
        return tx_req
    raise ValueError("Invalid LI.FI route: missing 'transactionRequest' object.")


# ======================================================================================
# Service
# ======================================================================================

class LiveExecutionService:
    """Execute live trades on EVM and Solana chains using pre-built routes."""

    def __init__(self) -> None:
        self._evm_signer: Optional[EvmSigner] = None
        self._sol_signer: Optional[SolanaSigner] = None

    # ------------------------- Signer factories -------------------------

    def _ensure_evm_signer(self) -> EvmSigner:
        if self._evm_signer is None:
            self._evm_signer = build_default_evm_signer()
        return self._evm_signer

    def _ensure_solana_signer(self) -> SolanaSigner:
        if self._sol_signer is None:
            self._sol_signer = build_default_solana_signer()
        return self._sol_signer

    # ------------------------- EVM execution -------------------------

    async def evm_execute_route(self, route: Dict[str, Any]) -> str:
        """
        Execute a LI.FI same-chain route on EVM.

        The `route` must contain a `transactionRequest` compatible with web3:
            {
              "from": "...",
              "to": "...",
              "data": "0x...",
              "value": "0x...",          # ou entier / décimal
              "chainId": 56,
              "gas": "0x...",            # optionnel
              "gasLimit": "0x...",       # optionnel (alias)
              "gasPrice": "0x...",       # optionnel (legacy)
              "maxFeePerGas": "0x...",   # optionnel (EIP-1559)
              "maxPriorityFeePerGas": "0x...",
              "nonce": "0x..." | int     # optionnel
            }
        Returns:
            tx hash (hex string)
        """
        tx_req = _extract_evm_transaction_request(route)

        to_address = tx_req.get("to") or tx_req.get("toAddress")
        data_hex = tx_req.get("data") or tx_req.get("calldata")
        if not to_address or not data_hex:
            raise ValueError("LI.FI transactionRequest must include 'to' and 'data'.")

        value_wei = parse_int_maybe_hex(tx_req.get("value")) or 0
        gas_limit = parse_int_maybe_hex(tx_req.get("gasLimit")) or parse_int_maybe_hex(tx_req.get("gas"))
        gas_price_wei = parse_int_maybe_hex(tx_req.get("gasPrice"))
        max_fee_per_gas_wei = parse_int_maybe_hex(tx_req.get("maxFeePerGas"))
        max_priority_fee_per_gas_wei = parse_int_maybe_hex(tx_req.get("maxPriorityFeePerGas"))
        nonce = parse_int_maybe_hex(tx_req.get("nonce"))
        chain_id = parse_int_maybe_hex(tx_req.get("chainId"))

        log.debug(
            "EVM tx parsing: to=%s valueWei=%s gasLimit=%s gasPrice=%s maxFee=%s maxPrio=%s nonce=%s chainId=%s",
            to_address, value_wei, gas_limit, gas_price_wei, max_fee_per_gas_wei, max_priority_fee_per_gas_wei, nonce, chain_id
        )

        signer = self._ensure_evm_signer()

        # Sanity check optionnel: si LI.FI fournit chainId et qu'il ne matche pas le provider → warning
        try:
            if chain_id is not None and hasattr(signer, "chain_id") and signer.chain_id and int(signer.chain_id) != chain_id:
                log.warning("EVM chainId mismatch: signer=%s route=%s", getattr(signer, "chain_id", "?"), chain_id)
        except Exception:
            pass

        log.info("LiveExecutor: broadcasting EVM route to %s", to_address)

        # On garde la signature existante de ton signer (pas de breaking change)
        tx_hash = signer.send_transaction(  # type: ignore[attr-defined]
            to=to_address,
            data=data_hex,
            value_wei=value_wei,
            gas_limit=gas_limit,
            gas_price_wei=gas_price_wei,
            max_fee_per_gas_wei=max_fee_per_gas_wei,
            max_priority_fee_per_gas_wei=max_priority_fee_per_gas_wei,
            nonce=nonce,
            chain_id=chain_id,
        )
        return tx_hash

    # ------------------------- Solana execution -------------------------

    async def solana_execute_route(self, route: Dict[str, Any]) -> str:
        """
        Execute a serialized Solana transaction returned by Jupiter:
            route = {"transaction": {"serializedTransaction": "<base64>"}}
        Returns:
            Base58 signature string.
        """
        tx_obj = route.get("transaction") or {}
        raw_b64 = tx_obj.get("serializedTransaction")
        if not raw_b64:
            raise ValueError("Invalid Jupiter route: missing transaction.serializedTransaction")

        signer = self._ensure_solana_signer()
        log.info("LiveExecutor: broadcasting Solana swap")
        tx_sig = signer.sign_and_send_serialized_transaction(raw_b64, skip_preflight=False)
        return tx_sig
