from __future__ import annotations

import httpx

from src.integrations.jupiter.jupiter_structures import JupiterQuoteResponse, JupiterSwapRequest, JupiterSwapResponse
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

JUPITER_QUOTE_API_URL = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_API_URL = "https://api.jup.ag/swap/v1/swap"


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
        response_status_code = status_exception.response.status_code if status_exception.response is not None else "Unknown Status"
        response_body_text = status_exception.response.text if status_exception.response is not None else "No Response Body"
        logger.exception(
            "[JUPITER][CLIENT][QUOTE][FAILURE] HTTP status error occurred for endpoint %s with status %s and body: %s",
            JUPITER_QUOTE_API_URL,
            response_status_code,
            response_body_text,
        )
        raise status_exception
    except httpx.RequestError as request_exception:
        logger.exception(
            "[JUPITER][CLIENT][QUOTE][FAILURE] Network request error occurred for endpoint %s",
            JUPITER_QUOTE_API_URL,
        )
        raise request_exception


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
        useSharedAccounts=True,
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
        response_status_code = status_exception.response.status_code if status_exception.response is not None else "Unknown Status"
        response_body_text = status_exception.response.text if status_exception.response is not None else "No Response Body"
        logger.exception(
            "[JUPITER][CLIENT][SWAP][FAILURE] HTTP status error occurred for endpoint %s with status %s and body: %s",
            JUPITER_SWAP_API_URL,
            response_status_code,
            response_body_text,
        )
        raise status_exception
    except httpx.RequestError as request_exception:
        logger.exception(
            "[JUPITER][CLIENT][SWAP][FAILURE] Network request error occurred for endpoint %s",
            JUPITER_SWAP_API_URL,
        )
        raise request_exception


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
