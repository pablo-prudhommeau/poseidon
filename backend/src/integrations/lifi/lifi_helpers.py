from __future__ import annotations

import json
from typing import cast, Optional

import httpx

from src.configuration.config import settings
from src.integrations.lifi.lifi_structures import (
    LifiQuote,
    LifiQuoteUnavailableError,
    LifiRoute,
    LifiRouteNormalizationError,
    LifiSolanaQuotePayload,
    LifiSolanaSerializedTransaction,
    LifiTransactionRequest,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

LIFI_EVM_DIAMOND_CONTRACT_ADDRESS: str = "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE"


def parse_lifi_hex_or_decimal_integer(value: str) -> int:
    if value.startswith("0x"):
        return int(value, 16)
    return int(value)


def validate_executable_evm_transaction_request(transaction_request: LifiTransactionRequest) -> None:
    if not transaction_request.to.strip():
        raise LifiRouteNormalizationError("LI.FI EVM transaction request is missing recipient contract address")
    if not transaction_request.data.strip():
        raise LifiRouteNormalizationError("LI.FI EVM transaction request is missing calldata")
    if transaction_request.from_address is None or not transaction_request.from_address.strip():
        raise LifiRouteNormalizationError("LI.FI EVM transaction request is missing source wallet address")
    if transaction_request.gas_limit is None or not transaction_request.gas_limit.strip():
        raise LifiRouteNormalizationError("LI.FI EVM transaction request is missing gas limit")


def resolve_lifi_transaction_gas_limit_in_units(transaction_request: LifiTransactionRequest) -> int:
    validate_executable_evm_transaction_request(transaction_request)
    gas_limit_text = transaction_request.gas_limit
    if gas_limit_text is None:
        raise LifiRouteNormalizationError("LI.FI EVM transaction request is missing gas limit")
    return parse_lifi_hex_or_decimal_integer(gas_limit_text)


def build_lifi_route_from_evm_quote(quote: LifiQuote) -> LifiRoute:
    validate_executable_evm_transaction_request(quote.transaction_request)
    logger.debug(
        "[LIFI][ROUTE][EVM] Normalized executable route to=%s from=%s gas_limit=%s",
        quote.transaction_request.to,
        quote.transaction_request.from_address,
        quote.transaction_request.gas_limit,
    )
    return LifiRoute(
        transaction_request=quote.transaction_request,
        estimate=quote.estimate,
    )


def build_lifi_route_from_solana_quote_payload(payload: LifiSolanaQuotePayload) -> LifiRoute:
    if payload.transaction is not None and payload.transaction.serialized_transaction.strip():
        solana_transaction = LifiSolanaSerializedTransaction(
            serialized_transaction=payload.transaction.serialized_transaction,
        )
        logger.debug("[LIFI][ROUTE][SOLANA] Normalized executable route from single transaction payload")
        return LifiRoute(transaction=solana_transaction)

    if payload.transactions is not None and len(payload.transactions) > 0:
        first_transaction = payload.transactions[0]
        if first_transaction.serialized_transaction.strip():
            solana_transaction = LifiSolanaSerializedTransaction(
                serialized_transaction=first_transaction.serialized_transaction,
            )
            logger.debug("[LIFI][ROUTE][SOLANA] Normalized executable route from transactions list payload")
            return LifiRoute(transactions=[solana_transaction])

    raise LifiRouteNormalizationError("LI.FI Solana quote does not contain an executable serialized transaction")


def build_lifi_http_headers() -> dict[str, str]:
    http_headers: dict[str, str] = {}
    lifi_api_key = getattr(settings, "LIFI_API_KEY", None)

    if isinstance(lifi_api_key, str) and lifi_api_key.strip():
        http_headers["x-lifi-api-key"] = lifi_api_key.strip()
        logger.debug("[LIFI][HTTP][HEADERS] LI.FI API key successfully injected into HTTP headers")
    else:
        logger.debug("[LIFI][HTTP][HEADERS] No LI.FI API key found in configuration, proceeding without authentication headers")

    return http_headers


def execute_http_get_json(endpoint_url: str, query_parameters: dict[str, object]) -> dict[str, object]:
    request_timeout = httpx.Timeout(12.0, connect=6.0)

    logger.debug("[LIFI][HTTP][GET][REQUEST] Initiating GET request to endpoint %s", endpoint_url)

    try:
        with httpx.Client(timeout=request_timeout, headers=build_lifi_http_headers()) as http_client:
            http_response = http_client.get(endpoint_url, params=query_parameters)
            http_response.raise_for_status()
            response_payload = http_response.json()
            logger.debug("[LIFI][HTTP][GET][SUCCESS] Successfully retrieved and parsed JSON payload from %s", endpoint_url)
            return cast(dict[str, object], response_payload)

    except httpx.HTTPStatusError as status_exception:
        raise _build_lifi_http_status_error(
            endpoint_url=endpoint_url,
            status_exception=status_exception,
        ) from status_exception

    except httpx.RequestError as request_exception:
        logger.warning(
            "[LIFI][HTTP][GET][FAILURE] Network request error occurred for endpoint %s with error: %s",
            endpoint_url,
            request_exception,
        )
        raise request_exception


def _build_lifi_http_status_error(
        endpoint_url: str,
        status_exception: httpx.HTTPStatusError,
) -> LifiQuoteUnavailableError:
    response_status_code: Optional[int] = (
        status_exception.response.status_code
        if status_exception.response is not None
        else None
    )
    response_body_text: str = (
        status_exception.response.text
        if status_exception.response is not None
        else "No Response Body"
    )
    response_message: Optional[str] = _extract_lifi_error_message(response_body_text)
    is_no_quote_response: bool = _is_lifi_no_quote_response(
        http_status_code=response_status_code,
        response_message=response_message,
        response_body_text=response_body_text,
    )

    if is_no_quote_response:
        logger.warning(
            "[LIFI][HTTP][GET][NO_QUOTE] No route available for endpoint %s http_status=%s message=%s",
            endpoint_url,
            response_status_code,
            response_message,
        )
        logger.debug(
            "[LIFI][HTTP][GET][NO_QUOTE] Full LI.FI response body for endpoint %s: %s",
            endpoint_url,
            response_body_text,
        )
        return LifiQuoteUnavailableError(
            message=response_message or "No available LI.FI route for requested transfer",
            http_status_code=response_status_code,
            response_message=response_message,
        )

    logger.warning(
        "[LIFI][HTTP][GET][FAILURE] HTTP status error occurred for endpoint %s with status %s and body: %s",
        endpoint_url,
        response_status_code,
        response_body_text[:500],
    )
    return LifiQuoteUnavailableError(
        message=f"LI.FI HTTP {response_status_code} for endpoint {endpoint_url}",
        http_status_code=response_status_code,
        response_message=response_message,
    )


def _extract_lifi_error_message(response_body_text: str) -> Optional[str]:
    try:
        response_payload = json.loads(response_body_text)
        if not isinstance(response_payload, dict):
            return None
        message_value = response_payload.get("message")
        if isinstance(message_value, str) and message_value.strip():
            return message_value.strip()
    except ValueError:
        return None
    return None


def _is_lifi_no_quote_response(
        http_status_code: Optional[int],
        response_message: Optional[str],
        response_body_text: str,
) -> bool:
    if http_status_code != 404:
        return False
    if response_message is not None and "no available quotes" in response_message.lower():
        return True
    return '"code":1002' in response_body_text or '"code": 1002' in response_body_text
