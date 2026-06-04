from __future__ import annotations

from typing import Optional

import base58
import requests

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.blockchain_exceptions import (
    BlockchainPriceUnavailableError,
    BlockchainRpcUnavailableError,
)
from src.integrations.blockchain.solana.dex_parsers.meteora_pool_parser import MeteoraPoolParser
from src.integrations.blockchain.solana.dex_parsers.orca_pool_parser import OrcaPoolParser
from src.integrations.blockchain.solana.dex_parsers.pumpfun_pool_parser import PumpfunPoolParser
from src.integrations.blockchain.solana.dex_parsers.pumpswap_pool_parser import PumpswapPoolParser
from src.integrations.blockchain.solana.dex_parsers.raydium_pool_parser import RaydiumPoolParser
from src.integrations.blockchain.solana.solana_structures import SolanaPriceParseResources
from src.integrations.blockchain.solana.solana_rpc_client import (
    convert_price_to_usd,
    decode_account_data,
    extract_owner_program,
    get_solana_rpc_url,
    prefetch_spl_token_balances_for_vault_addresses,
    prefetch_spl_token_decimals_for_mint_addresses,
    rpc_get_account_info,
    rpc_get_multiple_accounts,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_pumpfun_parser = PumpfunPoolParser()
_pumpswap_parser = PumpswapPoolParser()
_raydium_parser = RaydiumPoolParser()
_meteora_parser = MeteoraPoolParser()
_orca_parser = OrcaPoolParser()

_DEX_PARSER_REGISTRY: dict = {
    "pumpfun": _pumpfun_parser,
    "pumpswap": _pumpswap_parser,
    "raydium": _raydium_parser,
    "meteora": _meteora_parser,
    "orca": _orca_parser,
}


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


def _extract_raydium_amm_v4_resource_addresses(account_data: bytes) -> tuple[list[str], list[str]]:
    if len(account_data) < _raydium_parser.AMM_V4_MINIMUM_DATA_LENGTH:
        return [], []

    base_mint = base58.b58encode(
        account_data[_raydium_parser.AMM_V4_BASE_MINT_OFFSET:_raydium_parser.AMM_V4_BASE_MINT_OFFSET + 32],
    ).decode("ascii")
    quote_mint = base58.b58encode(
        account_data[_raydium_parser.AMM_V4_QUOTE_MINT_OFFSET:_raydium_parser.AMM_V4_QUOTE_MINT_OFFSET + 32],
    ).decode("ascii")
    base_vault = base58.b58encode(
        account_data[_raydium_parser.AMM_V4_BASE_VAULT_OFFSET:_raydium_parser.AMM_V4_BASE_VAULT_OFFSET + 32],
    ).decode("ascii")
    quote_vault = base58.b58encode(
        account_data[_raydium_parser.AMM_V4_QUOTE_VAULT_OFFSET:_raydium_parser.AMM_V4_QUOTE_VAULT_OFFSET + 32],
    ).decode("ascii")
    return [base_vault, quote_vault], [base_mint, quote_mint]


def _build_raydium_batch_parse_resources(
        rpc_url: str,
        account_infos: list[Optional[dict]],
        eligible_descriptors: list[tuple[str, str, str]],
) -> SolanaPriceParseResources:
    vault_addresses: list[str] = []
    mint_addresses: list[str] = []

    for descriptor_index, (_, _, dex_id) in enumerate(eligible_descriptors):
        if dex_id != "raydium":
            continue
        account_info = account_infos[descriptor_index] if descriptor_index < len(account_infos) else None
        if account_info is None:
            continue
        account_data = decode_account_data(account_info)
        if account_data is None:
            continue
        extracted_vault_addresses, extracted_mint_addresses = _extract_raydium_amm_v4_resource_addresses(account_data)
        vault_addresses.extend(extracted_vault_addresses)
        mint_addresses.extend(extracted_mint_addresses)

    vault_balances_by_address = prefetch_spl_token_balances_for_vault_addresses(rpc_url, vault_addresses)
    mint_decimals_by_address = prefetch_spl_token_decimals_for_mint_addresses(rpc_url, mint_addresses)
    return SolanaPriceParseResources(
        vault_balances_by_address=vault_balances_by_address,
        mint_decimals_by_address=mint_decimals_by_address,
    )


def _parse_pool_price_by_dex(
        rpc_url: str,
        dex_id: str,
        account_info: dict,
        target_token_address: str,
        parse_resources: SolanaPriceParseResources | None = None,
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

    if normalized_dex == "raydium":
        return _raydium_parser.parse_pool_price(
            rpc_url,
            account_data,
            target_token_address,
            owner_program,
            parse_resources=parse_resources,
        )

    return parser.parse_pool_price(rpc_url, account_data, target_token_address, owner_program)


def read_solana_pool_price_usd(
        pool_address: str,
        target_token_address: str,
        dex_id: str,
) -> Optional[float]:
    supported_dex_ids = settings.TRADING_SOLANA_SUPPORTED_DEX_IDS
    normalized_dex = dex_id.lower().strip()

    if normalized_dex not in supported_dex_ids:
        logger.debug("[BLOCKCHAIN][PRICE][SOL] DEX %s not in supported list, skipping %s", normalized_dex, target_token_address[:8])
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
        price_usd = convert_price_to_usd(rpc_url, price_in_quote, quote_mint)

        if price_usd is None or price_usd <= 0:
            logger.debug("[BLOCKCHAIN][PRICE][SOL] Cannot resolve USD price for %s (%s)", target_token_address[:8], normalized_dex)
            return None

        logger.debug("[BLOCKCHAIN][PRICE][SOL] %s (%s) = %.10f USD via RPC (%s)", target_token_address[:8], normalized_dex, price_usd, normalized_dex)
        return price_usd

    except (ConnectionError, requests.RequestException, BlockchainRpcUnavailableError) as infrastructure_failure:
        _raise_solana_price_unavailable_from_infrastructure_failure(infrastructure_failure)


def read_solana_pool_prices_usd_batch(
        pool_descriptors: list[tuple[str, str, str]],
) -> dict[str, float]:
    if not pool_descriptors:
        return {}

    supported_dex_ids = settings.TRADING_SOLANA_SUPPORTED_DEX_IDS
    eligible_descriptors: list[tuple[str, str, str]] = []
    for token_address, pair_address, dex_id in pool_descriptors:
        normalized_dex = dex_id.lower().strip()
        if normalized_dex in supported_dex_ids:
            eligible_descriptors.append((token_address, pair_address, normalized_dex))
        else:
            logger.debug("[BLOCKCHAIN][PRICE][SOL] Batch DEX %s not in supported list, skipping %s", normalized_dex, token_address[:8])

    if not eligible_descriptors:
        return {}

    rpc_url = _resolve_solana_rpc_url_for_price_fetch()
    results: dict[str, float] = {}

    pool_addresses = [pair_address for _, pair_address, _ in eligible_descriptors]

    try:
        account_infos = rpc_get_multiple_accounts(rpc_url, pool_addresses)
        parse_resources = _build_raydium_batch_parse_resources(
            rpc_url=rpc_url,
            account_infos=account_infos,
            eligible_descriptors=eligible_descriptors,
        )

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
                    parse_resources=parse_resources,
                )
                if price_result is None:
                    continue

                price_in_quote, quote_mint = price_result
                price_usd = convert_price_to_usd(rpc_url, price_in_quote, quote_mint)
                if price_usd is not None and price_usd > 0:
                    results[token_address] = price_usd
            except Exception as parse_exception:
                logger.warning(
                    "[BLOCKCHAIN][PRICE][SOL] Batch parse error for %s (%s) — %s",
                    token_address[:8],
                    dex_id,
                    parse_exception,
                )

    except (ConnectionError, requests.RequestException, BlockchainRpcUnavailableError) as infrastructure_failure:
        _raise_solana_price_unavailable_from_infrastructure_failure(infrastructure_failure)

    logger.info("[BLOCKCHAIN][PRICE][SOL] Batch resolved %d / %d pool prices via RPC", len(results), len(eligible_descriptors))
    return results
