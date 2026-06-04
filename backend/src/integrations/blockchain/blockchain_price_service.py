from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork, Token
from src.integrations.blockchain.blockchain_exceptions import BlockchainPriceUnavailableError
from src.integrations.blockchain.blockchain_price_structures import (
    OnchainPricesByPairAddress,
    PairAddressOnchainPrice,
)
from src.integrations.blockchain.blockchain_rpc_registry import (
    get_supported_evm_chains,
    resolve_web3_provider_for_chain,
)
from src.integrations.blockchain.evm.blockchain_evm_price_reader import read_evm_pair_price_usd
from src.integrations.blockchain.solana.blockchain_solana_price_reader import (
    read_solana_pool_price_usd,
    read_solana_pool_prices_usd_batch,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def fetch_onchain_price_for_token(token: Token) -> float:
    chain = token.chain
    pair_address = token.pair_address
    token_address = token.token_address

    if chain is None or not pair_address or not token_address:
        raise BlockchainPriceUnavailableError(
            f"[BLOCKCHAIN][PRICE][SERVICE] Missing chain/pair/token for {token.symbol}",
            blockchain_network=chain or BlockchainNetwork.SOLANA,
        )

    if chain == BlockchainNetwork.SOLANA:
        price_usd = read_solana_pool_price_usd(pair_address, token_address, token.dex_id)
    elif chain in get_supported_evm_chains():
        web3_provider = resolve_web3_provider_for_chain(chain)
        if web3_provider is None:
            raise BlockchainPriceUnavailableError(
                f"[BLOCKCHAIN][PRICE][SERVICE] No RPC provider for chain {chain.value}",
                blockchain_network=chain,
            )
        price_usd = read_evm_pair_price_usd(web3_provider, chain, pair_address, token_address)
    else:
        raise BlockchainPriceUnavailableError(
            f"[BLOCKCHAIN][PRICE][SERVICE] Unsupported chain {chain.value} for token {token.symbol}",
            blockchain_network=chain,
        )

    if price_usd is None or price_usd <= 0.0:
        raise BlockchainPriceUnavailableError(
            f"[BLOCKCHAIN][PRICE][SERVICE] No valid on-chain price for {token.symbol} ({pair_address[:10]}) on {chain.value}",
            blockchain_network=chain,
        )

    logger.debug(
        "[BLOCKCHAIN][PRICE][SERVICE] %s (%s) = %.12f USD",
        token.symbol,
        pair_address[:10],
        price_usd,
    )
    return price_usd


def fetch_onchain_prices_for_tokens(tokens: list[Token]) -> OnchainPricesByPairAddress:
    if not tokens:
        return OnchainPricesByPairAddress.empty()

    tokens_requiring_price: list[Token] = []
    for token in tokens:
        if not token.pair_address or not token.token_address:
            continue
        if token.chain is None:
            raise BlockchainPriceUnavailableError(
                f"[BLOCKCHAIN][PRICE][SERVICE] Missing chain for {token.symbol}",
                blockchain_network=BlockchainNetwork.SOLANA,
            )
        tokens_requiring_price.append(token)

    if not tokens_requiring_price:
        return OnchainPricesByPairAddress.empty()

    logger.info("[BLOCKCHAIN][PRICE][SERVICE] Fetching on-chain prices for %d tokens", len(tokens_requiring_price))

    resolved_pair_address_prices: list[PairAddressOnchainPrice] = []
    seen_pair_addresses: set[str] = set()

    solana_tokens = [
        token for token in tokens_requiring_price if token.chain == BlockchainNetwork.SOLANA
    ]
    other_tokens = [
        token for token in tokens_requiring_price if token.chain != BlockchainNetwork.SOLANA
    ]

    if solana_tokens:
        seen_solana_pair_addresses: set[str] = set()
        pool_descriptors: list[tuple[str, str, str]] = []
        for solana_token in solana_tokens:
            if solana_token.pair_address not in seen_solana_pair_addresses:
                seen_solana_pair_addresses.add(solana_token.pair_address)
                pool_descriptors.append((
                    solana_token.token_address,
                    solana_token.pair_address,
                    solana_token.dex_id,
                ))

        solana_prices_by_token_address = read_solana_pool_prices_usd_batch(pool_descriptors)

        for solana_token in solana_tokens:
            if solana_token.pair_address in seen_pair_addresses:
                continue
            if solana_token.token_address not in solana_prices_by_token_address:
                raise BlockchainPriceUnavailableError(
                    f"[BLOCKCHAIN][PRICE][SERVICE] No valid Solana on-chain price for {solana_token.symbol}",
                    blockchain_network=BlockchainNetwork.SOLANA,
                )
            price_usd = solana_prices_by_token_address[solana_token.token_address]
            if price_usd <= 0.0:
                raise BlockchainPriceUnavailableError(
                    f"[BLOCKCHAIN][PRICE][SERVICE] Non-positive Solana on-chain price for {solana_token.symbol}",
                    blockchain_network=BlockchainNetwork.SOLANA,
                )
            resolved_pair_address_prices.append(
                PairAddressOnchainPrice(
                    pair_address=solana_token.pair_address,
                    price_usd=price_usd,
                ),
            )
            seen_pair_addresses.add(solana_token.pair_address)
            logger.debug(
                "[BLOCKCHAIN][PRICE][SERVICE] %s (%s) = %.12f USD",
                solana_token.symbol,
                solana_token.pair_address[:10],
                price_usd,
            )

    for token in other_tokens:
        if token.pair_address in seen_pair_addresses:
            continue
        price_usd = fetch_onchain_price_for_token(token)
        resolved_pair_address_prices.append(
            PairAddressOnchainPrice(
                pair_address=token.pair_address,
                price_usd=price_usd,
            ),
        )
        seen_pair_addresses.add(token.pair_address)

    logger.info(
        "[BLOCKCHAIN][PRICE][SERVICE] Resolved %d / %d token prices",
        len(resolved_pair_address_prices),
        len(tokens_requiring_price),
    )
    return OnchainPricesByPairAddress(pair_address_prices=resolved_pair_address_prices)
