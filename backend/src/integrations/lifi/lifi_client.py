from __future__ import annotations

from typing import Optional, cast, Dict, Mapping

from src.configuration.config import settings
from src.core.structures.structures import LifiRoute
from src.core.utils.dict_utils import _read_path
from src.integrations.lifi.lifi_helpers import _normalize_chain_key, _http_get_json
from src.integrations.lifi.lifi_structures import EvmChain, LifiQuoteJson
from src.logging.logger import get_logger

log = get_logger(__name__)

EVM_NATIVE_TOKEN_ZERO_ADDRESS: str = "0x0000000000000000000000000000000000000000"

# LI.FI chain code for Solana (use string code, not numeric id)
SOLANA_CHAIN_CODE: str = "SOL"
SOLANA_NATIVE_TICKER: str = "SOL"

_EVM_CHAIN_REGISTRY: Dict[str, EvmChain] = {
    "ethereum": EvmChain("ethereum", 1, "ETH"),
    "arbitrum": EvmChain("arbitrum", 42161, "ETH"),
    "optimism": EvmChain("optimism", 10, "ETH"),
    "base": EvmChain("base", 8453, "ETH"),
    "linea": EvmChain("linea", 59144, "ETH"),
    "scroll": EvmChain("scroll", 534352, "ETH"),
    "blast": EvmChain("blast", 81457, "ETH"),
    "zksync": EvmChain("zksync", 324, "ETH"),
    "era": EvmChain("era", 324, "ETH"),
    "polygon-zkevm": EvmChain("polygon-zkevm", 1101, "ETH"),
    "polygon_zkevm": EvmChain("polygon_zkevm", 1101, "ETH"),
    "bsc": EvmChain("bsc", 56, "BNB"),
    "opbnb": EvmChain("opbnb", 204, "BNB"),
    "polygon": EvmChain("polygon", 137, "MATIC"),
    "avalanche": EvmChain("avalanche", 43114, "AVAX"),
    "fantom": EvmChain("fantom", 250, "FTM"),
    "cronos": EvmChain("cronos", 25, "CRO"),
    "gnosis": EvmChain("gnosis", 100, "xDAI"),
    "celo": EvmChain("celo", 42220, "CELO"),
    "metis": EvmChain("metis", 1088, "METIS"),
    "mantle": EvmChain("mantle", 5000, "MNT"),
    "kava": EvmChain("kava", 2222, "KAVA"),
    "moonbeam": EvmChain("moonbeam", 1284, "GLMR"),
    "moonriver": EvmChain("moonriver", 1285, "MOVR"),
}


def resolve_lifi_chain_id(dexscreener_chain_key: str) -> Optional[int]:
    """
    Convert a Dexscreener chain key into a LI.FI numeric chain id (EVM-only).

    Notes:
        - Solana uses a string chain code 'SOL' with the generic /v1/quote endpoint.
          This resolver returns None for non-EVM chains by design.

    Args:
        dexscreener_chain_key: The chain key as provided by Dexscreener.

    Returns:
        The LI.FI chain id if the chain is a supported EVM network, otherwise None.
    """
    normalized_key = _normalize_chain_key(dexscreener_chain_key)
    chain = _EVM_CHAIN_REGISTRY.get(normalized_key)
    if chain is None:
        log.debug("[LI.FI][CHAIN][RESOLVE] Unsupported Dexscreener key '%s'", dexscreener_chain_key)
        return None
    return int(chain.chain_id)


def build_native_to_token_quote(
        *,
        chain_key: str,
        from_address: str,
        to_token_address: str,
        from_amount_wei: int,
        slippage: float = 0.03,
) -> LifiQuoteJson:
    """
    Build a LI.FI single-step quote to swap native asset -> ERC-20 on the same **EVM** chain.

    This uses the generic `/v1/quote` endpoint with numeric `fromChain`/`toChain`.
    """
    if not from_address.strip() or not to_token_address.strip():
        raise ValueError("from_address and to_token_address must be provided.")
    if from_amount_wei <= 0:
        raise ValueError("from_amount_wei must be greater than zero.")

    lifi_chain_id = resolve_lifi_chain_id(chain_key)
    if lifi_chain_id is None:
        raise ValueError(f"Unsupported EVM chain for LI.FI: '{chain_key}'")

    base_url = str(settings.LIFI_BASE_URL).rstrip("/")
    if not base_url:
        raise ValueError("settings.LIFI_BASE_URL must be configured.")

    url = f"{base_url}/v1/quote"
    query_params: Dict[str, object] = {
        "fromChain": lifi_chain_id,
        "toChain": lifi_chain_id,
        "fromToken": EVM_NATIVE_TOKEN_ZERO_ADDRESS,
        "toToken": to_token_address,
        "fromAmount": str(from_amount_wei),
        "fromAddress": from_address,
        "slippage": slippage,
        "allowSwitchChain": "false",
    }

    log.debug(
        "[LI.FI][QUOTE][REQUEST][EVM] chain_key=%s chain_id=%s to_token=%s amount_wei=%s slippage=%.4f",
        chain_key,
        lifi_chain_id,
        to_token_address,
        from_amount_wei,
        slippage,
    )

    data = _http_get_json(url, query_params)
    typed_data = cast(LifiQuoteJson, data)

    log.info("[LI.FI][QUOTE][RECEIVE][EVM] chain_key=%s chain_id=%s to_token=%s", chain_key, lifi_chain_id, to_token_address)
    log.debug("[LI.FI][QUOTE][PAYLOAD][EVM] Raw payload received (truncated in logs).")

    return typed_data


def _build_solana_native_to_token_quote(
        *,
        from_address: str,
        to_token_mint: str,
        from_amount_lamports: int,
        slippage: float = 0.03,
) -> LifiQuoteJson:
    """
    Build a LI.FI single-step quote to swap SOL -> SPL token on **Solana**.

    Important:
        - Use the **same** generic endpoint `/v1/quote`.
        - Chain params are string codes: `fromChain=SOL`, `toChain=SOL`.
        - Tokens: `fromToken=SOL`, `toToken=<SPL mint>`.
        - Amount: `fromAmount` in lamports.
    """
    if not from_address.strip() or not to_token_mint.strip():
        raise ValueError("from_address and to_token_mint must be provided.")
    if from_amount_lamports <= 0:
        raise ValueError("from_amount_lamports must be greater than zero.")

    base_url = str(settings.LIFI_BASE_URL).rstrip("/")
    if not base_url:
        raise ValueError("settings.LIFI_BASE_URL must be configured.")

    url = f"{base_url}/v1/quote"
    query_params: Dict[str, object] = {
        "fromChain": SOLANA_CHAIN_CODE,
        "toChain": SOLANA_CHAIN_CODE,
        "fromToken": SOLANA_NATIVE_TICKER,
        "toToken": to_token_mint,
        "fromAmount": str(from_amount_lamports),
        "fromAddress": from_address,
        # Keep toAddress same as fromAddress unless you want to separate source/destination owner.
        "toAddress": from_address,
        "slippage": slippage,
        "allowSwitchChain": "false",
    }

    log.debug(
        "[LI.FI][QUOTE][REQUEST][SOL] from=%s to_mint=%s amount_lamports=%s slippage=%.4f",
        from_address,
        to_token_mint,
        from_amount_lamports,
        slippage,
    )

    data = _http_get_json(url, query_params)
    typed_data = cast(LifiQuoteJson, data)

    log.info("[LI.FI][QUOTE][RECEIVE][SOL] to_mint=%s", to_token_mint)
    log.debug("[LI.FI][QUOTE][PAYLOAD][SOL] Raw payload received (truncated in logs).")

    return typed_data


def _normalize_quote_to_route(quote: LifiQuoteJson) -> Optional[LifiRoute]:
    """
    Validate that the LI.FI quote contains an executable payload and return it as a route.

    Accepts the main shapes observed for:
        - EVM: presence of a `transactionRequest` object at the root or in the first step/item.
        - Solana: presence of either `transaction.serializedTransaction` or `transactionRequest.data` (base64).
    """
    # EVM shapes
    if isinstance(_read_path(quote, ("transactionRequest",)), Mapping):
        return cast(LifiRoute, quote)
    if isinstance(_read_path(quote, ("items", 0, "data", "transactionRequest")), Mapping):
        return cast(LifiRoute, quote)
    if isinstance(_read_path(quote, ("steps", 0, "items", 0, "data", "transactionRequest")), Mapping):
        return cast(LifiRoute, quote)

    # Solana shapes
    serialized = _read_path(quote, ("transaction", "serializedTransaction"))
    if isinstance(serialized, str) and len(serialized) > 0:
        return cast(LifiRoute, quote)
    serialized = _read_path(quote, ("transactions", 0, "serializedTransaction"))
    if isinstance(serialized, str) and len(serialized) > 0:
        return cast(LifiRoute, quote)
    # Some SOL flows embed base64 into transactionRequest.data (for EVM-style executor wrappers)
    data_field = _read_path(quote, ("transactionRequest", "data"))
    if isinstance(data_field, str) and len(data_field) > 0:
        return cast(LifiRoute, quote)

    return None


def build_native_to_token_route(
        *,
        chain_key: str,
        from_address: str,
        to_token_address: str,
        from_amount_wei: int,
        slippage: float,
) -> Optional[LifiRoute]:
    """
    Build a LI.FI same-chain route ready for execution.

    Behavior:
        - **EVM**: native -> ERC-20 using numeric chain ids.
        - **Solana**: SOL -> SPL using chain code 'SOL' on the same `/v1/quote` endpoint.

    Args:
        chain_key: Canonical Dexscreener chain key (e.g. 'ethereum', 'base', 'polygon', 'solana').
        from_address: Sender address that will sign/broadcast.
        to_token_address: ERC-20 contract (EVM) or SPL mint (Solana).
        from_amount_wei: Amount in smallest unit (wei for EVM, lamports for Solana).
        slippage: Allowed slippage (0.0 - 1.0).

    Returns:
        A typed `LifiRoute` if a valid executable payload is present; otherwise None.
    """
    normalized_chain = _normalize_chain_key(chain_key)

    if normalized_chain == "solana":
        quote = _build_solana_native_to_token_quote(
            from_address=from_address,
            to_token_mint=to_token_address,
            from_amount_lamports=from_amount_wei,
            slippage=slippage,
        )
    else:
        quote = build_native_to_token_quote(
            chain_key=normalized_chain,
            from_address=from_address,
            to_token_address=to_token_address,
            from_amount_wei=from_amount_wei,
            slippage=slippage,
        )

    route = _normalize_quote_to_route(quote)
    if route is None:
        log.warning(
            "[LI.FI][ROUTE][NORMALIZE] Missing executable payload in quote — chain=%s token=%s",
            chain_key,
            to_token_address,
        )
        return None

    network_tag = "SOL" if normalized_chain == "solana" else "EVM"
    log.debug("[LI.FI][ROUTE][READY][%s] Normalized LI.FI quote to route.", network_tag)
    return route
