from __future__ import annotations

from typing import Optional

from src.core.structures.structures import BlockchainNetwork
from src.integrations.lifi.lifi_constants import LIFI_API_BASE_URL
from src.integrations.lifi.lifi_helpers import (
    build_lifi_route_from_evm_quote,
    build_lifi_route_from_solana_quote_payload,
    execute_http_get_json,
)
from src.integrations.lifi.lifi_structures import EvmChain, LifiAlternativeRouteSummary, LifiQuote, LifiRoute, LifiSolanaQuotePayload
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

EVM_NATIVE_TOKEN_ZERO_ADDRESS: str = "0x0000000000000000000000000000000000000000"

SOLANA_CHAIN_IDENTIFIER: str = "SOL"
SOLANA_NATIVE_TOKEN_TICKER: str = "SOL"

_EVM_CHAIN_REGISTRY: dict[BlockchainNetwork, EvmChain] = {
    BlockchainNetwork.BASE: EvmChain(dexscreener_chain_identifier="base", chain_identifier=8453, native_token_symbol="ETH"),
    BlockchainNetwork.BSC: EvmChain(dexscreener_chain_identifier="bsc", chain_identifier=56, native_token_symbol="BNB"),
    BlockchainNetwork.AVALANCHE: EvmChain(dexscreener_chain_identifier="avalanche", chain_identifier=43114, native_token_symbol="AVAX"),
    BlockchainNetwork.ROBINHOOD: EvmChain(dexscreener_chain_identifier="robinhood", chain_identifier=4663, native_token_symbol="ETH"),
}


def resolve_lifi_chain_identifier(chain: BlockchainNetwork) -> Optional[int]:
    matched_chain = _EVM_CHAIN_REGISTRY.get(chain)

    if matched_chain is None:
        logger.debug("[LIFI][CLIENT][CHAIN][RESOLVE] Unsupported chain identifier '%s'", chain.value)
        return None

    return matched_chain.chain_identifier


def generate_native_token_to_erc20_quote(
        chain: BlockchainNetwork,
        source_address: str,
        destination_token_address: str,
        source_amount_wei: int,
        slippage_tolerance: float,
) -> LifiQuote:
    if not source_address.strip() or not destination_token_address.strip():
        logger.error("[LIFI][CLIENT][QUOTE][EVM] Missing required address parameters")
        raise ValueError("Source address and destination token address must be explicitly provided.")

    if source_amount_wei <= 0:
        logger.error("[LIFI][CLIENT][QUOTE][EVM] Invalid source amount %d", source_amount_wei)
        raise ValueError("Source amount in wei must be strictly positive.")

    lifi_chain_identifier = resolve_lifi_chain_identifier(chain=chain)
    if lifi_chain_identifier is None:
        logger.error("[LIFI][CLIENT][QUOTE][EVM] Unsupported EVM chain %s", chain.value)
        raise ValueError(f"Unsupported EVM chain for LI.FI routing: '{chain.value}'")

    target_endpoint_url = f"{LIFI_API_BASE_URL}/v1/quote"
    query_parameters: dict[str, object] = {
        "fromChain": lifi_chain_identifier,
        "toChain": lifi_chain_identifier,
        "fromToken": EVM_NATIVE_TOKEN_ZERO_ADDRESS,
        "toToken": destination_token_address,
        "fromAmount": str(source_amount_wei),
        "fromAddress": source_address,
        "slippage": slippage_tolerance,
        "allowSwitchChain": "false",
    }

    logger.debug(
        "[LIFI][CLIENT][QUOTE][EVM][REQUEST] Requesting quote for chain %s (ID: %s) to token %s for %d wei with slippage %f",
        chain.value,
        lifi_chain_identifier,
        destination_token_address,
        source_amount_wei,
        slippage_tolerance,
    )

    response_payload = execute_http_get_json(endpoint_url=target_endpoint_url, query_parameters=query_parameters)

    logger.debug("[LIFI][CLIENT][QUOTE][EVM][SUCCESS] Received quote for chain %s to token %s", chain.value, destination_token_address)
    return LifiQuote.model_validate(response_payload)


def generate_solana_native_to_token_quote(
        source_address: str,
        destination_token_mint: str,
        source_amount_lamports: int,
        slippage_tolerance: float,
) -> LifiSolanaQuotePayload:
    if not source_address.strip() or not destination_token_mint.strip():
        logger.error("[LIFI][CLIENT][QUOTE][SOLANA] Missing required address parameters")
        raise ValueError("Source address and destination token mint must be explicitly provided.")

    if source_amount_lamports <= 0:
        logger.error("[LIFI][CLIENT][QUOTE][SOLANA] Invalid source amount %d", source_amount_lamports)
        raise ValueError("Source amount in lamports must be strictly positive.")

    target_endpoint_url = f"{LIFI_API_BASE_URL}/v1/quote"
    query_parameters: dict[str, object] = {
        "fromChain": SOLANA_CHAIN_IDENTIFIER,
        "toChain": SOLANA_CHAIN_IDENTIFIER,
        "fromToken": SOLANA_NATIVE_TOKEN_TICKER,
        "toToken": destination_token_mint,
        "fromAmount": str(source_amount_lamports),
        "fromAddress": source_address,
        "toAddress": source_address,
        "slippage": slippage_tolerance,
        "allowSwitchChain": "false",
    }

    logger.debug(
        "[LIFI][CLIENT][QUOTE][SOLANA][REQUEST] Requesting quote from %s to mint %s for %d lamports with slippage %f",
        source_address,
        destination_token_mint,
        source_amount_lamports,
        slippage_tolerance,
    )

    response_payload = execute_http_get_json(endpoint_url=target_endpoint_url, query_parameters=query_parameters)

    logger.debug("[LIFI][CLIENT][QUOTE][SOLANA][SUCCESS] Received quote to mint %s", destination_token_mint)
    return LifiSolanaQuotePayload.model_validate(response_payload)


def generate_native_to_token_route(
        chain: BlockchainNetwork,
        source_address: str,
        destination_token_address: str,
        source_amount_wei: int,
        slippage_tolerance: float,
) -> LifiRoute:
    if chain == BlockchainNetwork.SOLANA:
        quote_payload = generate_solana_native_to_token_quote(
            source_address=source_address,
            destination_token_mint=destination_token_address,
            source_amount_lamports=source_amount_wei,
            slippage_tolerance=slippage_tolerance,
        )
        return build_lifi_route_from_solana_quote_payload(quote_payload)

    evm_quote_model = generate_native_token_to_erc20_quote(
        chain=chain,
        source_address=source_address,
        destination_token_address=destination_token_address,
        source_amount_wei=source_amount_wei,
        slippage_tolerance=slippage_tolerance,
    )
    return build_lifi_route_from_evm_quote(evm_quote_model)


def generate_token_to_token_route(
        chain: BlockchainNetwork,
        source_address: str,
        source_token_address: str,
        destination_token_address: str,
        source_amount_wei: int,
        slippage_tolerance: float,
) -> LifiRoute:
    evm_quote_model = generate_token_to_token_quote(
        chain=chain,
        source_address=source_address,
        source_token_address=source_token_address,
        destination_token_address=destination_token_address,
        source_amount_wei=source_amount_wei,
        slippage_tolerance=slippage_tolerance,
    )
    return build_lifi_route_from_evm_quote(evm_quote_model)


def generate_token_to_token_quote(
        chain: BlockchainNetwork,
        source_address: str,
        source_token_address: str,
        destination_token_address: str,
        source_amount_wei: int,
        slippage_tolerance: float,
) -> LifiQuote:
    if not source_address.strip() or not source_token_address.strip() or not destination_token_address.strip():
        logger.error("[LIFI][CLIENT][QUOTE][TOKEN] Missing required address parameters")
        raise ValueError("All addresses must be explicitly provided.")

    if source_amount_wei <= 0:
        logger.error("[LIFI][CLIENT][QUOTE][TOKEN] Invalid source amount %d", source_amount_wei)
        raise ValueError("Source amount in wei must be strictly positive.")

    lifi_chain_identifier = resolve_lifi_chain_identifier(chain=chain)
    if lifi_chain_identifier is None:
        logger.error("[LIFI][CLIENT][QUOTE][TOKEN] Unsupported EVM chain %s", chain.value)
        raise ValueError(f"Unsupported EVM chain for LI.FI routing: '{chain.value}'")

    target_endpoint_url = f"{LIFI_API_BASE_URL}/v1/quote"
    query_parameters: dict[str, object] = {
        "fromChain": lifi_chain_identifier,
        "toChain": lifi_chain_identifier,
        "fromToken": source_token_address,
        "toToken": destination_token_address,
        "fromAmount": str(source_amount_wei),
        "fromAddress": source_address,
        "slippage": slippage_tolerance,
        "allowSwitchChain": "false",
    }

    logger.debug(
        "[LIFI][CLIENT][QUOTE][TOKEN][REQUEST] Requesting quote for chain %s (ID: %s) from token %s to token %s for amount %d",
        chain.value,
        lifi_chain_identifier,
        source_token_address,
        destination_token_address,
        source_amount_wei,
    )

    response_payload = execute_http_get_json(endpoint_url=target_endpoint_url, query_parameters=query_parameters)
    logger.debug(
        "[LIFI][CLIENT][QUOTE][TOKEN][SUCCESS] Received quote for chain %s from token %s to token %s",
        chain.value,
        source_token_address,
        destination_token_address,
    )

    return LifiQuote.model_validate(response_payload)


def fetch_alternative_token_to_token_route_summaries(
        chain: BlockchainNetwork,
        source_address: str,
        source_token_address: str,
        destination_token_address: str,
        source_amount_wei: int,
        slippage_tolerance: float,
        maximum_route_count: int = 3,
) -> list[LifiAlternativeRouteSummary]:
    lifi_chain_identifier = resolve_lifi_chain_identifier(chain=chain)
    if lifi_chain_identifier is None:
        return []

    target_endpoint_url = f"{LIFI_API_BASE_URL}/v1/advanced/routes"
    query_parameters: dict[str, object] = {
        "fromChain": lifi_chain_identifier,
        "toChain": lifi_chain_identifier,
        "fromToken": source_token_address,
        "toToken": destination_token_address,
        "fromAmount": str(source_amount_wei),
        "fromAddress": source_address,
        "slippage": slippage_tolerance,
        "allowSwitchChain": "false",
    }

    try:
        response_payload = execute_http_get_json(endpoint_url=target_endpoint_url, query_parameters=query_parameters)
    except Exception as exception:
        logger.debug(
            "[LIFI][CLIENT][ROUTES][DEBUG] Alternative routes request failed for chain %s: %s",
            chain.value,
            exception,
        )
        return []

    raw_routes = response_payload.get("routes")
    if not isinstance(raw_routes, list):
        return []

    route_summaries: list[LifiAlternativeRouteSummary] = []
    for raw_route in raw_routes[:maximum_route_count]:
        if not isinstance(raw_route, dict):
            continue
        estimate_payload = raw_route.get("estimate")
        if not isinstance(estimate_payload, dict):
            continue
        tool_value = estimate_payload.get("tool")
        to_amount_value = estimate_payload.get("toAmount")
        to_amount_min_value = estimate_payload.get("toAmountMin")
        tool: Optional[str] = tool_value if isinstance(tool_value, str) else None
        to_amount: Optional[str] = to_amount_value if isinstance(to_amount_value, str) else None
        to_amount_min: Optional[str] = to_amount_min_value if isinstance(to_amount_min_value, str) else None
        route_summaries.append(
            LifiAlternativeRouteSummary(
                tool=tool,
                to_amount=to_amount,
                to_amount_min=to_amount_min,
                implied_expected_price_usd=None,
                deviation_expected_percent=None,
            )
        )

    logger.debug(
        "[LIFI][CLIENT][ROUTES][DEBUG] Retrieved %d alternative route summaries for chain %s",
        len(route_summaries),
        chain.value,
    )
    return route_summaries
