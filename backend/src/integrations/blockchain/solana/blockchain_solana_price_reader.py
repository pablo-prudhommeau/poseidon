from __future__ import annotations

from typing import Optional, Protocol

import requests

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_configuration_service import resolve_stablecoin_address_for_blockchain
from src.core.trading.trading_dex_capability_service import (
    TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS,
    is_supported_trading_solana_dex_id,
)
from src.integrations.blockchain.blockchain_exceptions import (
    BlockchainPriceUnavailableError,
    BlockchainRpcUnavailableError,
)
from src.integrations.blockchain.solana.dex_parsers.pumpfun_pool_parser import PumpfunPoolParser
from src.integrations.blockchain.solana.dex_parsers.pumpswap_pool_parser import PumpswapPoolParser
from src.integrations.blockchain.solana.solana_rpc_client import (
    decode_account_data,
    extract_owner_program,
    get_solana_rpc_url,
    rpc_get_account_info,
    rpc_get_multiple_accounts,
)
from src.integrations.blockchain.solana.solana_structures import SOLANA_WRAPPED_SOL_MINT
from src.integrations.jupiter.jupiter_client import resolve_sol_usd_price
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class SolanaDexPoolPriceParser(Protocol):
    def parse_pool_price(
            self,
            rpc_url: str,
            account_data: bytes,
            target_token_address: str,
            owner_program: str,
    ) -> Optional[tuple[float, str]]:
        ...


def _build_dex_parser_registry() -> dict[str, SolanaDexPoolPriceParser]:
    parser_implementations_by_dex_id: dict[str, SolanaDexPoolPriceParser] = {
        "pumpfun": PumpfunPoolParser(),
        "pumpswap": PumpswapPoolParser(),
    }
    dex_parser_registry: dict[str, SolanaDexPoolPriceParser] = {}
    for application_supported_dex_id in TRADING_APPLICATION_SUPPORTED_SOLANA_DEX_IDS:
        parser = parser_implementations_by_dex_id.get(application_supported_dex_id)
        if parser is None:
            raise RuntimeError(
                f"Missing RPC pool parser for application-supported Solana dex '{application_supported_dex_id}'",
            )
        dex_parser_registry[application_supported_dex_id] = parser
    return dex_parser_registry


_DEX_PARSER_REGISTRY: dict[str, SolanaDexPoolPriceParser] = _build_dex_parser_registry()


def _raise_solana_price_unavailable_from_infrastructure_failure(
        infrastructure_failure: BaseException,
) -> None:
    raise BlockchainPriceUnavailableError(
        str(infrastructure_failure),
        blockchain_network=BlockchainNetwork.SOLANA,
    ) from infrastructure_failure


def _resolve_solana_rpc_url_for_price_fetch() -> str:
    try:
        return get_solana_rpc_url()
    except ConnectionError as connection_error:
        _raise_solana_price_unavailable_from_infrastructure_failure(connection_error)


def _parse_pool_price_by_dex(
        rpc_url: str,
        dex_id: str,
        account_info: dict,
        target_token_address: str,
) -> Optional[tuple[float, str]]:
    account_data = decode_account_data(account_info)
    if account_data is None:
        return None

    owner_program = extract_owner_program(account_info)
    normalized_dex = dex_id.lower().strip()

    parser = _DEX_PARSER_REGISTRY.get(normalized_dex)
    if parser is None:
        logger.debug("[BLOCKCHAIN][PRICE][SOL] Unsupported DEX %s for pool parsing", normalized_dex)
        return None

    return parser.parse_pool_price(rpc_url, account_data, target_token_address, owner_program)


def read_solana_pool_price_usd(
        pool_address: str,
        target_token_address: str,
        dex_id: str,
) -> Optional[float]:
    normalized_dex = dex_id.lower().strip()

    if not is_supported_trading_solana_dex_id(normalized_dex):
        logger.debug(
            "[BLOCKCHAIN][PRICE][SOL] DEX %s not in application supported list, skipping %s",
            normalized_dex,
            target_token_address[:8],
        )
        return None

    rpc_url = _resolve_solana_rpc_url_for_price_fetch()

    try:
        account_info = rpc_get_account_info(rpc_url, pool_address)
        if account_info is None:
            logger.debug("[BLOCKCHAIN][PRICE][SOL] No account data for pool %s (%s)", pool_address[:12], normalized_dex)
            return None

        price_result = _parse_pool_price_by_dex(rpc_url, normalized_dex, account_info, target_token_address)
        if price_result is None:
            logger.debug("[BLOCKCHAIN][PRICE][SOL] Failed to parse pool %s via %s", pool_address[:12], normalized_dex)
            return None

        price_in_quote, quote_mint = price_result
        price_usd = convert_price_to_usd(price_in_quote, quote_mint)

        if price_usd is None or price_usd <= 0:
            logger.debug("[BLOCKCHAIN][PRICE][SOL] Cannot resolve USD price for %s (%s)", target_token_address[:8], normalized_dex)
            return None

        logger.debug(
            "[BLOCKCHAIN][PRICE][SOL] %s (%s) = %.10f USD via RPC (%s)",
            target_token_address[:8],
            normalized_dex,
            price_usd,
            normalized_dex,
        )
        return price_usd

    except (ConnectionError, requests.RequestException, BlockchainRpcUnavailableError) as infrastructure_failure:
        _raise_solana_price_unavailable_from_infrastructure_failure(infrastructure_failure)


def read_solana_pool_prices_usd_batch(
        pool_descriptors: list[tuple[str, str, str]],
) -> dict[str, float]:
    if not pool_descriptors:
        return {}

    eligible_descriptors: list[tuple[str, str, str]] = []
    for token_address, pair_address, dex_id in pool_descriptors:
        normalized_dex = dex_id.lower().strip()
        if is_supported_trading_solana_dex_id(normalized_dex):
            eligible_descriptors.append((token_address, pair_address, normalized_dex))
        else:
            logger.debug(
                "[BLOCKCHAIN][PRICE][SOL] Batch DEX %s not in application supported list, skipping %s",
                normalized_dex,
                token_address[:8],
            )

    if not eligible_descriptors:
        return {}

    rpc_url = _resolve_solana_rpc_url_for_price_fetch()
    results: dict[str, float] = {}

    pool_addresses = [pair_address for _, pair_address, _ in eligible_descriptors]

    try:
        account_infos = rpc_get_multiple_accounts(rpc_url, pool_addresses)

        for descriptor_index, (token_address, pair_address, dex_id) in enumerate(eligible_descriptors):
            account_info = account_infos[descriptor_index] if descriptor_index < len(account_infos) else None
            if account_info is None:
                continue

            try:
                price_result = _parse_pool_price_by_dex(
                    rpc_url,
                    dex_id,
                    account_info,
                    token_address,
                )
                if price_result is None:
                    continue

                price_in_quote, quote_mint = price_result
                price_usd = convert_price_to_usd(price_in_quote, quote_mint)
                if price_usd is not None and price_usd > 0:
                    results[token_address] = price_usd
            except Exception as parse_exception:
                logger.debug(
                    "[BLOCKCHAIN][PRICE][SOL] Batch parse error for %s (%s) — %s",
                    token_address[:8],
                    dex_id,
                    parse_exception,
                )

    except (ConnectionError, requests.RequestException, BlockchainRpcUnavailableError) as infrastructure_failure:
        _raise_solana_price_unavailable_from_infrastructure_failure(infrastructure_failure)

    logger.debug("[BLOCKCHAIN][PRICE][SOL] Batch resolved %d / %d pool prices via RPC", len(results), len(eligible_descriptors))
    return results


def convert_price_to_usd(
        price_in_quote: float,
        quote_token_mint: str,
) -> Optional[float]:
    stablecoin_mint = resolve_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    if stablecoin_mint and quote_token_mint == stablecoin_mint:
        return price_in_quote

    if quote_token_mint == SOLANA_WRAPPED_SOL_MINT:
        sol_usd = resolve_sol_usd_price()
        if sol_usd is None or sol_usd <= 0:
            return None
        return price_in_quote * sol_usd

    logger.debug("[BLOCKCHAIN][PRICE][SOL] Unknown quote mint %s, cannot convert to USD", quote_token_mint[:12])
    return None
