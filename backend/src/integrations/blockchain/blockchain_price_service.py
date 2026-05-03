from __future__ import annotations

from typing import Optional

from src.core.structures.structures import Token
from src.integrations.blockchain.blockchain_rpc_registry import (
    get_supported_evm_chains,
    resolve_web3_provider_for_chain,
)
from src.integrations.blockchain.evm.blockchain_evm_price_reader import read_evm_pair_price_usd
from src.integrations.blockchain.solana.blockchain_solana_price_reader import read_solana_pool_price_usd
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _is_solana_chain(chain_identifier: str) -> bool:
    return chain_identifier.lower() in {"solana", "sol"}


def _is_supported_evm_chain(chain_identifier: str) -> bool:
    return chain_identifier.lower() in get_supported_evm_chains()


def fetch_onchain_price_for_token(token: Token) -> Optional[float]:
    chain_identifier = token.chain
    pair_address = token.pair_address
    token_address = token.token_address

    if not chain_identifier or not pair_address or not token_address:
        logger.debug("[BLOCKCHAIN][PRICE][SERVICE] Skipping %s — missing chain/pair/token", token.symbol)
        return None

    if _is_solana_chain(chain_identifier):
        return read_solana_pool_price_usd(pair_address, token_address, token.dex_id)

    if _is_supported_evm_chain(chain_identifier):
        web3_provider = resolve_web3_provider_for_chain(chain_identifier)
        if web3_provider is None:
            return None
        return read_evm_pair_price_usd(web3_provider, chain_identifier, pair_address, token_address)

    logger.debug("[BLOCKCHAIN][PRICE][SERVICE] Unsupported chain %s for token %s", chain_identifier, token.symbol)
    return None


def fetch_onchain_prices_for_tokens(tokens: list[Token]) -> dict[str, float]:
    prices_by_pair_address: dict[str, float] = {}

    if not tokens:
        return prices_by_pair_address

    logger.info("[BLOCKCHAIN][PRICE][SERVICE] Fetching on-chain prices for %d tokens", len(tokens))

    solana_tokens: list[Token] = []
    other_tokens: list[Token] = []

    for token in tokens:
        if not token.pair_address or not token.token_address:
            continue
        if _is_solana_chain(token.chain):
            solana_tokens.append(token)
        else:
            other_tokens.append(token)

    if solana_tokens:
        try:
            from src.integrations.blockchain.solana.blockchain_solana_price_reader import read_solana_pool_prices_usd_batch
            seen_pair_addresses: set[str] = set()
            pool_descriptors: list[tuple[str, str, str]] = []
            for solana_token in solana_tokens:
                if solana_token.pair_address not in seen_pair_addresses:
                    seen_pair_addresses.add(solana_token.pair_address)
                    pool_descriptors.append((
                        solana_token.token_address,
                        solana_token.pair_address,
                        solana_token.dex_id,
                    ))
            solana_prices = read_solana_pool_prices_usd_batch(pool_descriptors)

            for token in solana_tokens:
                if token.token_address in solana_prices:
                    price_usd = solana_prices[token.token_address]
                    prices_by_pair_address[token.pair_address] = price_usd
                    logger.debug(
                        "[BLOCKCHAIN][PRICE][SERVICE] %s (%s) = %.12f USD",
                        token.symbol, token.pair_address[:10], price_usd,
                    )
                else:
                    logger.debug(
                        "[BLOCKCHAIN][PRICE][SERVICE] No valid price for %s (%s) on solana",
                        token.symbol, token.pair_address[:10],
                    )
        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SERVICE] Unhandled error fetching batched solana prices")

    failed_pair_addresses: set[str] = set()

    for token in other_tokens:
        pair_address = token.pair_address
        if pair_address in prices_by_pair_address or pair_address in failed_pair_addresses:
            continue

        try:
            price_usd = fetch_onchain_price_for_token(token)
            if price_usd is not None and price_usd > 0.0:
                prices_by_pair_address[pair_address] = price_usd
                logger.debug(
                    "[BLOCKCHAIN][PRICE][SERVICE] %s (%s) = %.12f USD",
                    token.symbol, pair_address[:10], price_usd,
                )
            else:
                failed_pair_addresses.add(pair_address)
                logger.debug(
                    "[BLOCKCHAIN][PRICE][SERVICE] No valid price for %s (%s) on %s",
                    token.symbol, pair_address[:10], token.chain,
                )
        except Exception:
            failed_pair_addresses.add(pair_address)
            logger.exception(
                "[BLOCKCHAIN][PRICE][SERVICE] Unhandled error fetching price for %s (%s)",
                token.symbol, pair_address[:10],
            )

    logger.info(
        "[BLOCKCHAIN][PRICE][SERVICE] Resolved %d / %d token prices",
        len(prices_by_pair_address), len(tokens),
    )
    return prices_by_pair_address
