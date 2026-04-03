from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.configuration.config import settings
from src.core.trading.trading_structures import TradingLifiRoute as LifiRoute, TradingLifiEvmTransactionRequest as LifiEvmTransactionRequest, TradingLifiSolanaSerializedTransaction as LifiSolanaSerializedTransaction
from src.integrations.lifi.lifi_helpers import normalize_chain_identifier, execute_http_get_json
from src.integrations.lifi.lifi_structures import EvmChain, LifiQuote
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

EVM_NATIVE_TOKEN_ZERO_ADDRESS: str = "0x0000000000000000000000000000000000000000"

SOLANA_CHAIN_IDENTIFIER: str = "SOL"
SOLANA_NATIVE_TOKEN_TICKER: str = "SOL"

_EVM_CHAIN_REGISTRY: dict[str, EvmChain] = {
    "ethereum": EvmChain(dexscreener_chain_identifier="ethereum", chain_identifier=1, native_token_symbol="ETH"),
    "arbitrum": EvmChain(dexscreener_chain_identifier="arbitrum", chain_identifier=42161, native_token_symbol="ETH"),
    "optimism": EvmChain(dexscreener_chain_identifier="optimism", chain_identifier=10, native_token_symbol="ETH"),
    "base": EvmChain(dexscreener_chain_identifier="base", chain_identifier=8453, native_token_symbol="ETH"),
    "linea": EvmChain(dexscreener_chain_identifier="linea", chain_identifier=59144, native_token_symbol="ETH"),
    "scroll": EvmChain(dexscreener_chain_identifier="scroll", chain_identifier=534352, native_token_symbol="ETH"),
    "blast": EvmChain(dexscreener_chain_identifier="blast", chain_identifier=81457, native_token_symbol="ETH"),
    "zksync": EvmChain(dexscreener_chain_identifier="zksync", chain_identifier=324, native_token_symbol="ETH"),
    "era": EvmChain(dexscreener_chain_identifier="era", chain_identifier=324, native_token_symbol="ETH"),
    "polygon-zkevm": EvmChain(dexscreener_chain_identifier="polygon-zkevm", chain_identifier=1101, native_token_symbol="ETH"),
    "polygon_zkevm": EvmChain(dexscreener_chain_identifier="polygon_zkevm", chain_identifier=1101, native_token_symbol="ETH"),
    "bsc": EvmChain(dexscreener_chain_identifier="bsc", chain_identifier=56, native_token_symbol="BNB"),
    "opbnb": EvmChain(dexscreener_chain_identifier="opbnb", chain_identifier=204, native_token_symbol="BNB"),
    "polygon": EvmChain(dexscreener_chain_identifier="polygon", chain_identifier=137, native_token_symbol="MATIC"),
    "avalanche": EvmChain(dexscreener_chain_identifier="avalanche", chain_identifier=43114, native_token_symbol="AVAX"),
    "fantom": EvmChain(dexscreener_chain_identifier="fantom", chain_identifier=250, native_token_symbol="FTM"),
    "cronos": EvmChain(dexscreener_chain_identifier="cronos", chain_identifier=25, native_token_symbol="CRO"),
    "gnosis": EvmChain(dexscreener_chain_identifier="gnosis", chain_identifier=100, native_token_symbol="xDAI"),
    "celo": EvmChain(dexscreener_chain_identifier="celo", chain_identifier=42220, native_token_symbol="CELO"),
    "metis": EvmChain(dexscreener_chain_identifier="metis", chain_identifier=1088, native_token_symbol="METIS"),
    "mantle": EvmChain(dexscreener_chain_identifier="mantle", chain_identifier=5000, native_token_symbol="MNT"),
    "kava": EvmChain(dexscreener_chain_identifier="kava", chain_identifier=2222, native_token_symbol="KAVA"),
    "moonbeam": EvmChain(dexscreener_chain_identifier="moonbeam", chain_identifier=1284, native_token_symbol="GLMR"),
    "moonriver": EvmChain(dexscreener_chain_identifier="moonriver", chain_identifier=1285, native_token_symbol="MOVR"),
}


class LifiQuoteStepData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    transaction_request: Optional[dict[str, object]] = Field(default=None, alias="transactionRequest")


class LifiQuoteStepItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: Optional[LifiQuoteStepData] = None


class LifiQuoteStep(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: Optional[list[LifiQuoteStepItem]] = None


class LifiRouteResponsePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    transaction_request: Optional[dict[str, object]] = Field(default=None, alias="transactionRequest")
    transaction: Optional[dict[str, object]] = None
    transactions: Optional[list[dict[str, object]]] = None
    items: Optional[list[LifiQuoteStepItem]] = None
    steps: Optional[list[LifiQuoteStep]] = None


def resolve_lifi_chain_identifier(dexscreener_chain_identifier: str) -> Optional[int]:
    normalized_chain_identifier = normalize_chain_identifier(raw_chain_identifier=dexscreener_chain_identifier)
    matched_chain = _EVM_CHAIN_REGISTRY.get(normalized_chain_identifier)

    if matched_chain is None:
        logger.debug("[LIFI][CLIENT][CHAIN][RESOLVE] Unsupported Dexscreener chain identifier '%s'", dexscreener_chain_identifier)
        return None

    return matched_chain.chain_identifier


def generate_native_token_to_erc20_quote(
        chain_identifier: str,
        source_address: str,
        destination_token_address: str,
        source_amount_wei: int,
        slippage_tolerance: float = 0.03,
) -> LifiQuote:
    if not source_address.strip() or not destination_token_address.strip():
        logger.error("[LIFI][CLIENT][QUOTE][EVM] Missing required address parameters")
        raise ValueError("Source address and destination token address must be explicitly provided.")

    if source_amount_wei <= 0:
        logger.error("[LIFI][CLIENT][QUOTE][EVM] Invalid source amount %d", source_amount_wei)
        raise ValueError("Source amount in wei must be strictly positive.")

    lifi_chain_identifier = resolve_lifi_chain_identifier(dexscreener_chain_identifier=chain_identifier)
    if lifi_chain_identifier is None:
        logger.error("[LIFI][CLIENT][QUOTE][EVM] Unsupported EVM chain %s", chain_identifier)
        raise ValueError(f"Unsupported EVM chain for LI.FI routing: '{chain_identifier}'")

    lifi_base_url = str(settings.LIFI_BASE_URL).rstrip("/")
    if not lifi_base_url:
        raise ValueError("LI.FI base URL must be configured in settings.")

    target_endpoint_url = f"{lifi_base_url}/v1/quote"
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
        chain_identifier,
        lifi_chain_identifier,
        destination_token_address,
        source_amount_wei,
        slippage_tolerance,
    )

    response_payload = execute_http_get_json(endpoint_url=target_endpoint_url, query_parameters=query_parameters)

    logger.info("[LIFI][CLIENT][QUOTE][EVM][SUCCESS] Received quote for chain %s to token %s", chain_identifier, destination_token_address)
    return LifiQuote.model_validate(response_payload)


def generate_solana_native_to_token_quote(
        source_address: str,
        destination_token_mint: str,
        source_amount_lamports: int,
        slippage_tolerance: float = 0.03,
) -> LifiRouteResponsePayload:
    if not source_address.strip() or not destination_token_mint.strip():
        logger.error("[LIFI][CLIENT][QUOTE][SOLANA] Missing required address parameters")
        raise ValueError("Source address and destination token mint must be explicitly provided.")

    if source_amount_lamports <= 0:
        logger.error("[LIFI][CLIENT][QUOTE][SOLANA] Invalid source amount %d", source_amount_lamports)
        raise ValueError("Source amount in lamports must be strictly positive.")

    lifi_base_url = str(settings.LIFI_BASE_URL).rstrip("/")
    if not lifi_base_url:
        raise ValueError("LI.FI base URL must be configured in settings.")

    target_endpoint_url = f"{lifi_base_url}/v1/quote"
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

    logger.info("[LIFI][CLIENT][QUOTE][SOLANA][SUCCESS] Received quote to mint %s", destination_token_mint)
    return LifiRouteResponsePayload.model_validate(response_payload)


def normalize_quote_response_to_route(quote_response: LifiRouteResponsePayload) -> Optional[LifiRoute]:
    resolved_route = LifiRoute(transaction_request=LifiEvmTransactionRequest(to="", data="", value=""))

    if quote_response.transaction_request is not None:
        resolved_route.transaction_request.to = str(quote_response.transaction_request.get("to", ""))
        resolved_route.transaction_request.data = str(quote_response.transaction_request.get("data", ""))
        resolved_route.transaction_request.value = str(quote_response.transaction_request.get("value", ""))
        resolved_route.transaction_request.from_address = str(quote_response.transaction_request.get("from", ""))
        return resolved_route

    if quote_response.items is not None and len(quote_response.items) > 0:
        item_data = quote_response.items[0].data
        if item_data is not None and item_data.transaction_request is not None:
            resolved_route.transaction_request.to = str(item_data.transaction_request.get("to", ""))
            resolved_route.transaction_request.data = str(item_data.transaction_request.get("data", ""))
            resolved_route.transaction_request.value = str(item_data.transaction_request.get("value", ""))
            resolved_route.transaction_request.from_address = str(item_data.transaction_request.get("from", ""))
            return resolved_route

    if quote_response.steps is not None and len(quote_response.steps) > 0:
        quote_step = quote_response.steps[0]
        if quote_step.items is not None and len(quote_step.items) > 0:
            step_item_data = quote_step.items[0].data
            if step_item_data is not None and step_item_data.transaction_request is not None:
                resolved_route.transaction_request.to = str(step_item_data.transaction_request.get("to", ""))
                resolved_route.transaction_request.data = str(step_item_data.transaction_request.get("data", ""))
                resolved_route.transaction_request.value = str(step_item_data.transaction_request.get("value", ""))
                resolved_route.transaction_request.from_address = str(step_item_data.transaction_request.get("from", ""))
                return resolved_route

    if quote_response.transaction is not None:
        serialized_transaction_data = quote_response.transaction.get("serializedTransaction")
        if serialized_transaction_data:
            solana_transaction = LifiSolanaSerializedTransaction(serialized_transaction=str(serialized_transaction_data))
            resolved_route.transaction = solana_transaction
            return resolved_route

    if quote_response.transactions is not None and len(quote_response.transactions) > 0:
        serialized_transaction_data = quote_response.transactions[0].get("serializedTransaction")
        if serialized_transaction_data:
            solana_transaction = LifiSolanaSerializedTransaction(serialized_transaction=str(serialized_transaction_data))
            resolved_route.transactions = [solana_transaction]
            return resolved_route

    return None


def generate_native_to_token_route(
        chain_identifier: str,
        source_address: str,
        destination_token_address: str,
        source_amount_wei: int,
        slippage_tolerance: float,
) -> Optional[LifiRoute]:
    normalized_chain = normalize_chain_identifier(raw_chain_identifier=chain_identifier)

    if normalized_chain == "solana":
        quote_payload = generate_solana_native_to_token_quote(
            source_address=source_address,
            destination_token_mint=destination_token_address,
            source_amount_lamports=source_amount_wei,
            slippage_tolerance=slippage_tolerance,
        )
        resolved_route = normalize_quote_response_to_route(quote_response=quote_payload)
    else:
        evm_quote_model = generate_native_token_to_erc20_quote(
            chain_identifier=normalized_chain,
            source_address=source_address,
            destination_token_address=destination_token_address,
            source_amount_wei=source_amount_wei,
            slippage_tolerance=slippage_tolerance,
        )
        quote_payload = LifiRouteResponsePayload.model_validate(evm_quote_model.model_dump(by_alias=True))
        resolved_route = normalize_quote_response_to_route(quote_response=quote_payload)

    if resolved_route is None:
        logger.warning(
            "[LIFI][CLIENT][ROUTE][NORMALIZE] Missing executable payload in quote for chain %s and token %s",
            chain_identifier,
            destination_token_address,
        )
        return None

    network_tag = "SOLANA" if normalized_chain == "solana" else "EVM"
    logger.debug("[LIFI][CLIENT][ROUTE][SUCCESS] Successfully normalized LI.FI quote to route for network %s", network_tag)
    return resolved_route


def generate_token_to_token_quote(
        chain_identifier: str,
        source_address: str,
        source_token_address: str,
        destination_token_address: str,
        source_amount_wei: int,
        slippage_tolerance: float = 0.03,
) -> LifiQuote:
    if not source_address.strip() or not source_token_address.strip() or not destination_token_address.strip():
        logger.error("[LIFI][CLIENT][QUOTE][TOKEN] Missing required address parameters")
        raise ValueError("All addresses must be explicitly provided.")

    if source_amount_wei <= 0:
        logger.error("[LIFI][CLIENT][QUOTE][TOKEN] Invalid source amount %d", source_amount_wei)
        raise ValueError("Source amount in wei must be strictly positive.")

    lifi_chain_identifier = resolve_lifi_chain_identifier(dexscreener_chain_identifier=chain_identifier)
    if lifi_chain_identifier is None:
        logger.error("[LIFI][CLIENT][QUOTE][TOKEN] Unsupported EVM chain %s", chain_identifier)
        raise ValueError(f"Unsupported EVM chain for LI.FI routing: '{chain_identifier}'")

    lifi_base_url = str(settings.LIFI_BASE_URL).rstrip("/")

    target_endpoint_url = f"{lifi_base_url}/v1/quote"
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
        chain_identifier,
        lifi_chain_identifier,
        source_token_address,
        destination_token_address,
        source_amount_wei,
    )

    response_payload = execute_http_get_json(endpoint_url=target_endpoint_url, query_parameters=query_parameters)
    logger.info("[LIFI][CLIENT][QUOTE][TOKEN][SUCCESS] Received quote for chain %s from token %s to token %s", chain_identifier, source_token_address, destination_token_address)

    return LifiQuote.model_validate(response_payload)
