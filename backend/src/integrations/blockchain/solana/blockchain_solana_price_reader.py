from __future__ import annotations

from typing import Optional

import requests

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_configuration_service import resolve_stablecoin_address_for_blockchain
from src.core.trading.trading_dex_capability_service import is_supported_trading_solana_dex_id
from src.integrations.blockchain.blockchain_exceptions import (
    BlockchainPriceUnavailableError,
    BlockchainRpcUnavailableError,
)
from src.integrations.blockchain.solana.solana_dex_pool_parser_registry import (
    has_onchain_pool_price_parser_for_dex_id,
    resolve_onchain_pool_price_parser_for_dex_id,
)
from src.integrations.blockchain.solana.solana_rpc_client import (
    decode_account_data,
    extract_owner_program,
    get_solana_rpc_url,
    rpc_get_account_info,
    rpc_get_multiple_accounts,
)
from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_WRAPPED_SOL_MINT,
    SolanaPoolParsedPrice,
    SolanaPoolPriceRequest,
)
from src.integrations.jupiter.jupiter_client import resolve_sol_usd_price
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SOLANA_USD_STABLECOIN_MINTS: frozenset[str] = frozenset(
    {
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    },
)


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
) -> Optional[SolanaPoolParsedPrice]:
    account_data = decode_account_data(account_info)
    if account_data is None:
        return None

    owner_program = extract_owner_program(account_info)
    parser = resolve_onchain_pool_price_parser_for_dex_id(dex_id)
    if parser is None:
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

    if not has_onchain_pool_price_parser_for_dex_id(normalized_dex):
        logger.debug(
            "[BLOCKCHAIN][PRICE][SOL] No on-chain pool parser for DEX %s — skipping %s",
            normalized_dex,
            target_token_address[:8],
        )
        return None

    rpc_url = _resolve_solana_rpc_url_for_price_fetch()

    try:
        account_info = rpc_get_account_info(rpc_url, pool_address)
        if account_info is None:
            logger.debug(
                "[BLOCKCHAIN][PRICE][SOL] No account data for pool %s (%s)",
                pool_address[:12],
                normalized_dex,
            )
            return None

        parsed_price = _parse_pool_price_by_dex(
            rpc_url,
            normalized_dex,
            account_info,
            target_token_address,
        )
        if parsed_price is None:
            logger.debug(
                "[BLOCKCHAIN][PRICE][SOL] Failed to parse pool %s via %s",
                pool_address[:12],
                normalized_dex,
            )
            return None

        price_usd = convert_price_to_usd(
            parsed_price.price_in_quote_token,
            parsed_price.quote_token_mint,
        )
        if price_usd is None or price_usd <= 0:
            logger.debug(
                "[BLOCKCHAIN][PRICE][SOL] Cannot resolve USD price for %s (%s)",
                target_token_address[:8],
                normalized_dex,
            )
            return None

        logger.debug(
            "[BLOCKCHAIN][PRICE][SOL] %s (%s) = %.10f USD via pool RPC (%s)",
            target_token_address[:8],
            normalized_dex,
            price_usd,
            normalized_dex,
        )
        return price_usd

    except (ConnectionError, requests.RequestException, BlockchainRpcUnavailableError) as infrastructure_failure:
        _raise_solana_price_unavailable_from_infrastructure_failure(infrastructure_failure)


def read_solana_pool_prices_usd_batch(
        pool_price_requests: list[SolanaPoolPriceRequest],
) -> dict[str, float]:
    if not pool_price_requests:
        return {}

    eligible_requests: list[SolanaPoolPriceRequest] = []
    for pool_price_request in pool_price_requests:
        normalized_dex = pool_price_request.dex_id.lower().strip()
        if not is_supported_trading_solana_dex_id(normalized_dex):
            logger.debug(
                "[BLOCKCHAIN][PRICE][SOL] Batch DEX %s not in application supported list, skipping %s",
                normalized_dex,
                pool_price_request.token_address[:8],
            )
            continue
        if not has_onchain_pool_price_parser_for_dex_id(normalized_dex):
            logger.debug(
                "[BLOCKCHAIN][PRICE][SOL] Batch DEX %s has no on-chain parser, skipping %s",
                normalized_dex,
                pool_price_request.token_address[:8],
            )
            continue
        eligible_requests.append(
            SolanaPoolPriceRequest(
                token_address=pool_price_request.token_address,
                pair_address=pool_price_request.pair_address,
                dex_id=normalized_dex,
            ),
        )

    if not eligible_requests:
        return {}

    results: dict[str, float] = {}
    rpc_url = _resolve_solana_rpc_url_for_price_fetch()
    pool_addresses = [request.pair_address for request in eligible_requests]

    try:
        account_infos = rpc_get_multiple_accounts(rpc_url, pool_addresses)

        for request_index, pool_price_request in enumerate(eligible_requests):
            account_info = account_infos[request_index] if request_index < len(account_infos) else None
            if account_info is None:
                continue

            try:
                parsed_price = _parse_pool_price_by_dex(
                    rpc_url,
                    pool_price_request.dex_id,
                    account_info,
                    pool_price_request.token_address,
                )
                if parsed_price is None:
                    continue

                price_usd = convert_price_to_usd(
                    parsed_price.price_in_quote_token,
                    parsed_price.quote_token_mint,
                )
                if price_usd is not None and price_usd > 0:
                    results[pool_price_request.token_address] = price_usd
            except Exception:
                logger.exception(
                    "[BLOCKCHAIN][PRICE][SOL] Batch parse error for %s (%s)",
                    pool_price_request.token_address[:8],
                    pool_price_request.dex_id,
                )

    except (ConnectionError, requests.RequestException, BlockchainRpcUnavailableError) as infrastructure_failure:
        _raise_solana_price_unavailable_from_infrastructure_failure(infrastructure_failure)

    logger.debug(
        "[BLOCKCHAIN][PRICE][SOL] Batch resolved %d / %d pool prices via RPC",
        len(results),
        len(eligible_requests),
    )
    return results


def convert_price_to_usd(
        price_in_quote: float,
        quote_token_mint: str,
) -> Optional[float]:
    if quote_token_mint in SOLANA_USD_STABLECOIN_MINTS:
        return price_in_quote

    configured_stablecoin_mint = resolve_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    if configured_stablecoin_mint and quote_token_mint == configured_stablecoin_mint:
        return price_in_quote

    if quote_token_mint == SOLANA_WRAPPED_SOL_MINT:
        sol_usd = resolve_sol_usd_price()
        if sol_usd is None or sol_usd <= 0:
            return None
        return price_in_quote * sol_usd

    logger.debug("[BLOCKCHAIN][PRICE][SOL] Unknown quote mint %s, cannot convert to USD", quote_token_mint[:12])
    return None
