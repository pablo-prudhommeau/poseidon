from __future__ import annotations

"""
Jupiter client (Solana) — construit une transaction swap SOL -> SPL token.

Design:
- On quote via /v6/quote (Jupiter v6)
- Puis on construit la transaction signable via /v6/swap
- On renvoie un objet au format attendu par LiveExecutionService.solana_execute_route:
    {"transaction": {"serializedTransaction": "<base64>"}}

Entrées minimales:
- user_public_key: clé publique Solana (base58) du wallet exécutant la tx
- output_mint: mint SPL à acheter
- amount_lamports: montant SOL en lamports (1 SOL = 10^9 lamports)
"""

from typing import Any, Dict, Optional
import httpx

from src.configuration.config import settings
from src.logging.logger import get_logger

log = get_logger(__name__)

SOL_NATIVE_MINT = "So11111111111111111111111111111111111111112"
JUPITER_BASE_URL = getattr(settings, "JUPITER_BASE_URL")


def _http_get_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    timeout = httpx.Timeout(12.0, connect=6.0)
    headers = {
        "Accept": "application/json",
        "User-Agent": "poseidon-bot/1.0",
    }
    with httpx.Client(timeout=timeout, headers=headers) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _http_post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    timeout = httpx.Timeout(20.0, connect=8.0)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "poseidon-bot/1.0",
    }
    with httpx.Client(timeout=timeout, headers=headers) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def is_solana_chain_key(chain_key: str | None) -> bool:
    return (chain_key or "").strip().lower() == "solana"


def jupiter_quote_native_to_token(
        *, output_mint: str, amount_lamports: int, slippage_bps: int = 300
) -> Dict[str, Any]:
    """
    Demande une cote pour échanger SOL -> output_mint.

    slippage_bps: 300 = 3.00%
    """
    if not output_mint or amount_lamports <= 0:
        raise ValueError("output_mint must be set and amount_lamports > 0")

    url = f"{JUPITER_BASE_URL}/swap/v1/quote"
    params = {
        "inputMint": SOL_NATIVE_MINT,
        "outputMint": output_mint,
        "amount": str(amount_lamports),
        "slippageBps": int(slippage_bps),
        "onlyDirectRoutes": "false",
    }
    log.debug("Jupiter quote: %s", params)
    return _http_get_json(url, params)


def jupiter_build_swap_transaction(
        *, quote_response: Dict[str, Any], user_public_key: str
) -> Dict[str, Any]:
    """
    Construit la transaction signable auprès de Jupiter.

    Retourne:
      {"transaction": {"serializedTransaction": "<base64>"}}
    """
    if not user_public_key:
        raise ValueError("user_public_key must be provided")

    url = f"{JUPITER_BASE_URL}/swap/v1/swap"
    payload = {
        "quoteResponse": quote_response,
        "userPublicKey": user_public_key,
        # Options raisonnables par défaut
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "asLegacyTransaction": False,
    }
    log.debug("Jupiter swap build for %s", user_public_key)
    data = _http_post_json(url, payload)

    # Jupiter renvoie généralement {"swapTransaction": "<base64>"}
    raw_b64 = data.get("swapTransaction")
    if not raw_b64:
        raise ValueError("Jupiter swap response missing 'swapTransaction'")

    return {"transaction": {"serializedTransaction": raw_b64}}


def build_solana_native_to_token_route(
        *, user_public_key: str, output_mint: str, amount_lamports: int, slippage_bps: int = 300
) -> Dict[str, Any]:
    """
    Helper haut-niveau: quote + construction de la transaction.
    Retourne un objet prêt pour LiveExecutionService.solana_execute_route().
    """
    quote = jupiter_quote_native_to_token(
        output_mint=output_mint, amount_lamports=amount_lamports, slippage_bps=slippage_bps
    )
    route = jupiter_build_swap_transaction(quote_response=quote, user_public_key=user_public_key)
    log.info("Jupiter route OK: mint=%s lamports=%d", output_mint, amount_lamports)
    return route
