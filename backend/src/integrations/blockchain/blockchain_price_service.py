from __future__ import annotations

from typing import Dict, List, Optional

from src.integrations.blockchain.blockchain_rpc_registry import (
    get_supported_evm_chains,
    resolve_web3_provider_for_chain,
)
from src.integrations.blockchain.evm.blockchain_evm_price_reader import read_evm_pair_price_usd
from src.integrations.blockchain.solana.blockchain_solana_price_reader import read_solana_pool_price_usd
from src.logging.logger import get_application_logger
from src.persistence.models import TradingPosition

logger = get_application_logger(__name__)


def _is_solana_chain(chain_identifier: str) -> bool:
    return chain_identifier.lower() in {"solana", "sol"}


def _is_supported_evm_chain(chain_identifier: str) -> bool:
    return chain_identifier.lower() in get_supported_evm_chains()


def fetch_onchain_price_for_position(position: TradingPosition) -> Optional[float]:
    chain_identifier = position.blockchain_network
    pair_address = position.pair_address
    token_address = position.token_address

    if not chain_identifier or not pair_address or not token_address:
        logger.debug("[BLOCKCHAIN][PRICE][SERVICE] Skipping position %s — missing chain/pair/token", position.token_symbol)
        return None

    if _is_solana_chain(chain_identifier):
        return read_solana_pool_price_usd(pair_address, token_address, position.dex_id)

    if _is_supported_evm_chain(chain_identifier):
        web3_provider = resolve_web3_provider_for_chain(chain_identifier)
        if web3_provider is None:
            return None
        return read_evm_pair_price_usd(web3_provider, chain_identifier, pair_address, token_address)

    logger.debug("[BLOCKCHAIN][PRICE][SERVICE] Unsupported chain %s for position %s", chain_identifier, position.token_symbol)
    return None


def fetch_onchain_prices_for_positions(positions: List[TradingPosition]) -> Dict[str, float]:
    prices_by_pair_address: Dict[str, float] = {}

    if not positions:
        return prices_by_pair_address

    logger.info("[BLOCKCHAIN][PRICE][SERVICE] Fetching on-chain prices for %d positions", len(positions))

    solana_positions = []
    other_positions = []

    for position in positions:
        if not position.pair_address or not position.token_address:
            continue
        if _is_solana_chain(position.blockchain_network):
            solana_positions.append(position)
        else:
            other_positions.append(position)

    if solana_positions:
        try:
            from src.integrations.blockchain.solana.blockchain_solana_price_reader import read_solana_pool_prices_usd_batch
            token_addresses = list(set([p.token_address for p in solana_positions]))
            solana_prices = read_solana_pool_prices_usd_batch(token_addresses)

            for position in solana_positions:
                if position.token_address in solana_prices:
                    price_usd = solana_prices[position.token_address]
                    prices_by_pair_address[position.pair_address] = price_usd
                    logger.debug(
                        "[BLOCKCHAIN][PRICE][SERVICE] %s (%s) = %.12f USD",
                        position.token_symbol, position.pair_address[:10], price_usd,
                    )
                else:
                    logger.debug(
                        "[BLOCKCHAIN][PRICE][SERVICE] No valid price for %s (%s) on solana",
                        position.token_symbol, position.pair_address[:10],
                    )
        except Exception:
            logger.exception("[BLOCKCHAIN][PRICE][SERVICE] Unhandled error fetching batched solana prices")

    failed_pair_addresses: set[str] = set()

    for position in other_positions:
        pair_address = position.pair_address
        if pair_address in prices_by_pair_address or pair_address in failed_pair_addresses:
            continue

        try:
            price_usd = fetch_onchain_price_for_position(position)
            if price_usd is not None and price_usd > 0.0:
                prices_by_pair_address[pair_address] = price_usd
                logger.debug(
                    "[BLOCKCHAIN][PRICE][SERVICE] %s (%s) = %.12f USD",
                    position.token_symbol, pair_address[:10], price_usd,
                )
            else:
                failed_pair_addresses.add(pair_address)
                logger.debug(
                    "[BLOCKCHAIN][PRICE][SERVICE] No valid price for %s (%s) on %s",
                    position.token_symbol, pair_address[:10], position.blockchain_network,
                )
        except Exception:
            failed_pair_addresses.add(pair_address)
            logger.exception(
                "[BLOCKCHAIN][PRICE][SERVICE] Unhandled error fetching price for %s (%s)",
                position.token_symbol, pair_address[:10],
            )

    logger.info(
        "[BLOCKCHAIN][PRICE][SERVICE] Resolved %d / %d position prices",
        len(prices_by_pair_address), len(positions),
    )
    return prices_by_pair_address
