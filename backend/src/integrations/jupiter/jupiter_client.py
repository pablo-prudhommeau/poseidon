from __future__ import annotations

import time
from typing import Optional

import httpx

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_configuration_service import resolve_stablecoin_address_for_blockchain
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.integrations.blockchain.solana.solana_rpc_client import get_spl_token_decimals
from src.integrations.blockchain.solana.solana_structures import SOLANA_WRAPPED_SOL_MINT
from src.integrations.jupiter.jupiter_structures import (
    JupiterApiFailureReason,
    JupiterApiUnavailableError,
    JupiterQuoteResponse,
    JupiterSwapRequest,
    JupiterSwapResponse,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

JUPITER_QUOTE_API_URL = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_API_URL = "https://api.jup.ag/swap/v1/swap"

JUPITER_SOL_USD_REFERENCE_CACHE_TTL_SECONDS = 30
JUPITER_SOL_USD_REFERENCE_AMOUNT_LAMPORTS = 1_000_000_000
JUPITER_SOL_USD_REFERENCE_SLIPPAGE_BASIS_POINTS = 50

_cached_sol_usd_reference_price: Optional[float] = None
_cached_sol_usd_reference_timestamp: float = 0.0


def fetch_jupiter_quote(
        input_mint: str,
        output_mint: str,
        amount_in_lamports: int,
        slippage_basis_points: int
) -> JupiterQuoteResponse:
    if amount_in_lamports <= 0:
        logger.error("[JUPITER][CLIENT][QUOTE] Invalid amount %d", amount_in_lamports)
        raise ValueError("Amount in lamports must be strictly positive.")

    request_timeout = httpx.Timeout(12.0, connect=6.0)
    query_parameters: dict[str, object] = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_in_lamports),
        "slippageBps": str(slippage_basis_points),
    }

    logger.debug(
        "[JUPITER][CLIENT][QUOTE][REQUEST] Requesting quote from %s to %s for %d lamports with slippage %d bps",
        input_mint,
        output_mint,
        amount_in_lamports,
        slippage_basis_points,
    )

    try:
        with httpx.Client(timeout=request_timeout) as http_client:
            http_response = http_client.get(JUPITER_QUOTE_API_URL, params=query_parameters)
            http_response.raise_for_status()
            response_payload = http_response.json()
            logger.info("[JUPITER][CLIENT][QUOTE][SUCCESS] Successfully retrieved quote from %s to %s", input_mint, output_mint)
            return JupiterQuoteResponse.model_validate(response_payload)
    except httpx.HTTPStatusError as status_exception:
        raise _build_jupiter_http_unavailable_error(
            api_endpoint=JUPITER_QUOTE_API_URL,
            operation_label="quote",
            status_exception=status_exception,
        ) from status_exception
    except httpx.RequestError as request_exception:
        logger.debug(
            "[JUPITER][CLIENT][QUOTE][UNAVAILABLE] Network request error for endpoint %s",
            JUPITER_QUOTE_API_URL,
        )
        raise JupiterApiUnavailableError(
            f"[JUPITER][CLIENT][QUOTE] Network request error for endpoint {JUPITER_QUOTE_API_URL}",
            failure_reason=JupiterApiFailureReason.NETWORK_ERROR,
        ) from request_exception


def fetch_jupiter_swap_transaction(
        quote_response: JupiterQuoteResponse,
        user_public_key: str
) -> str:
    if not user_public_key.strip():
        logger.error("[JUPITER][CLIENT][SWAP] Missing required user public key parameter")
        raise ValueError("User public key must be explicitly provided.")

    request_timeout = httpx.Timeout(12.0, connect=6.0)
    swap_request = JupiterSwapRequest(
        quoteResponse=quote_response,
        userPublicKey=user_public_key,
        wrapAndUnwrapSol=True,
        useSharedAccounts=False,
        dynamicComputeUnitLimit=True,
        skipUserAccountsRpcCalls=True
    )

    request_payload = swap_request.model_dump(by_alias=True)
    logger.debug("[JUPITER][CLIENT][SWAP][REQUEST] Requesting swap transaction for user %s", user_public_key)

    try:
        with httpx.Client(timeout=request_timeout) as http_client:
            http_response = http_client.post(JUPITER_SWAP_API_URL, json=request_payload)
            http_response.raise_for_status()
            response_payload = http_response.json()
            swap_response = JupiterSwapResponse.model_validate(response_payload)
            logger.info("[JUPITER][CLIENT][SWAP][SUCCESS] Successfully retrieved swap transaction")
            return swap_response.swap_transaction
    except httpx.HTTPStatusError as status_exception:
        raise _build_jupiter_http_unavailable_error(
            api_endpoint=JUPITER_SWAP_API_URL,
            operation_label="swap",
            status_exception=status_exception,
        ) from status_exception
    except httpx.RequestError as request_exception:
        logger.debug(
            "[JUPITER][CLIENT][SWAP][UNAVAILABLE] Network request error for endpoint %s",
            JUPITER_SWAP_API_URL,
        )
        raise JupiterApiUnavailableError(
            f"[JUPITER][CLIENT][SWAP] Network request error for endpoint {JUPITER_SWAP_API_URL}",
            failure_reason=JupiterApiFailureReason.NETWORK_ERROR,
        ) from request_exception


def resolve_sol_usd_price() -> Optional[float]:
    global _cached_sol_usd_reference_price, _cached_sol_usd_reference_timestamp

    now = time.monotonic()
    if (
            _cached_sol_usd_reference_price is not None
            and (now - _cached_sol_usd_reference_timestamp) < JUPITER_SOL_USD_REFERENCE_CACHE_TTL_SECONDS
    ):
        return _cached_sol_usd_reference_price

    try:
        stablecoin_mint = resolve_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    except Exception:
        logger.debug("[JUPITER][CLIENT][REFERENCE][SOL_USD] Solana stablecoin mint unavailable")
        return _cached_sol_usd_reference_price

    if not stablecoin_mint:
        logger.debug("[JUPITER][CLIENT][REFERENCE][SOL_USD] Solana stablecoin mint unavailable")
        return _cached_sol_usd_reference_price

    try:
        quote_response = fetch_jupiter_quote(
            input_mint=SOLANA_WRAPPED_SOL_MINT,
            output_mint=stablecoin_mint,
            amount_in_lamports=JUPITER_SOL_USD_REFERENCE_AMOUNT_LAMPORTS,
            slippage_basis_points=JUPITER_SOL_USD_REFERENCE_SLIPPAGE_BASIS_POINTS,
        )
    except (JupiterApiUnavailableError, ValueError):
        logger.debug("[JUPITER][CLIENT][REFERENCE][SOL_USD] Quote unavailable")
        return _cached_sol_usd_reference_price

    output_amount_raw = int(quote_response.out_amount)
    if output_amount_raw <= 0:
        return _cached_sol_usd_reference_price

    try:
        rpc_url = resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA)
        stablecoin_decimals = get_spl_token_decimals(rpc_url, stablecoin_mint)
    except Exception:
        logger.debug("[JUPITER][CLIENT][REFERENCE][SOL_USD] Stablecoin decimals unavailable for mint %s", stablecoin_mint[:12])
        return _cached_sol_usd_reference_price

    sol_usd_price = output_amount_raw / (10 ** stablecoin_decimals)
    if sol_usd_price <= 0:
        return _cached_sol_usd_reference_price

    _cached_sol_usd_reference_price = sol_usd_price
    _cached_sol_usd_reference_timestamp = now
    logger.debug("[JUPITER][CLIENT][REFERENCE][SOL_USD] SOL/USD = %.4f", sol_usd_price)
    return sol_usd_price


def generate_jupiter_swap_transaction(
        source_address: str,
        input_mint: str,
        output_mint: str,
        amount_in_lamports: int,
        slippage_basis_points: int
) -> str:
    quote_response = fetch_jupiter_quote(
        input_mint=input_mint,
        output_mint=output_mint,
        amount_in_lamports=amount_in_lamports,
        slippage_basis_points=slippage_basis_points
    )
    return fetch_jupiter_swap_transaction(
        quote_response=quote_response,
        user_public_key=source_address
    )


def _build_jupiter_http_unavailable_error(
        api_endpoint: str,
        operation_label: str,
        status_exception: httpx.HTTPStatusError,
) -> JupiterApiUnavailableError:
    response_status_code = (
        status_exception.response.status_code
        if status_exception.response is not None
        else None
    )
    response_body_text = (
        status_exception.response.text
        if status_exception.response is not None
        else "No Response Body"
    )
    if response_status_code == 429:
        logger.debug(
            "[JUPITER][CLIENT][%s][UNAVAILABLE] Rate-limited — endpoint=%s http_status=429",
            operation_label.upper(),
            api_endpoint,
        )
        return JupiterApiUnavailableError(
            f"[JUPITER][CLIENT][{operation_label.upper()}] HTTP 429 for endpoint {api_endpoint}",
            failure_reason=JupiterApiFailureReason.RATE_LIMITED,
            http_status_code=response_status_code,
        )

    logger.warning(
        "[JUPITER][CLIENT][%s][UNAVAILABLE] HTTP status error — endpoint=%s http_status=%s body=%s",
        operation_label.upper(),
        api_endpoint,
        response_status_code,
        response_body_text,
    )
    return JupiterApiUnavailableError(
        f"[JUPITER][CLIENT][{operation_label.upper()}] HTTP {response_status_code} for endpoint {api_endpoint}",
        failure_reason=JupiterApiFailureReason.HTTP_ERROR,
        http_status_code=response_status_code,
    )
