from __future__ import annotations

from typing import cast, Optional

import httpx

from src.configuration.config import settings
from src.logging.logger import get_logger

logger = get_logger(__name__)


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
            logger.info("[LIFI][HTTP][GET][SUCCESS] Successfully retrieved and parsed JSON payload from %s", endpoint_url)
            return cast(dict[str, object], response_payload)

    except httpx.HTTPStatusError as status_exception:
        response_status_code = status_exception.response.status_code if status_exception.response is not None else "Unknown Status"
        response_body_text = status_exception.response.text if status_exception.response is not None else "No Response Body"
        logger.error(
            "[LIFI][HTTP][GET][FAILURE] HTTP status error occurred for endpoint %s with status %s and body: %s",
            endpoint_url,
            response_status_code,
            response_body_text,
        )
        raise status_exception

    except httpx.RequestError as request_exception:
        logger.error(
            "[LIFI][HTTP][GET][FAILURE] Network request error occurred for endpoint %s with error: %s",
            endpoint_url,
            request_exception,
        )
        raise request_exception


def normalize_chain_identifier(raw_chain_identifier: Optional[str]) -> str:
    if raw_chain_identifier is None or not raw_chain_identifier.strip():
        logger.debug("[LIFI][NORMALIZATION][SKIPPED] Empty chain identifier provided, returning default fallback string")
        return "ethereum"

    lowercased_identifier = raw_chain_identifier.strip().lower()

    if lowercased_identifier in {"eth", "ethereum-mainnet"}:
        return "ethereum"
    if lowercased_identifier in {"arb", "arbitrum-one"}:
        return "arbitrum"
    if lowercased_identifier in {"op", "optimism-mainnet"}:
        return "optimism"
    if lowercased_identifier in {"bsc-mainnet", "binance-smart-chain", "binance"}:
        return "bsc"
    if lowercased_identifier in {"matic", "polygon-pos", "polygon-mainnet"}:
        return "polygon"
    if lowercased_identifier in {"avax", "avalanche-c"}:
        return "avalanche"
    if lowercased_identifier in {"xdai"}:
        return "gnosis"
    if lowercased_identifier in {"zk-sync", "zk-sync-era", "zksync-era"}:
        return "zksync"
    if lowercased_identifier in {"polygonzkevm", "polygon-zk-evm"}:
        return "polygon-zkevm"

    return lowercased_identifier
