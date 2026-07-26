from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork, Token
from src.integrations.blockchain.blockchain_exceptions import BlockchainPriceUnavailableError
from src.integrations.blockchain.blockchain_price_structures import (
    OnchainPricesByPairAddress,
    OnchainPricesFetchResult,
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
from src.integrations.blockchain.solana.solana_structures import SolanaPoolPriceRequest
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

    price_usd: float | None = None
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
            f"[BLOCKCHAIN][PRICE][SERVICE] No valid on-chain price for {token.symbol} "
            f"({pair_address[:10]}) on {chain.value}",
            blockchain_network=chain,
        )

    logger.debug(
        "[BLOCKCHAIN][PRICE][SERVICE] %s (%s) = %.12f USD",
        token.symbol,
        pair_address[:10],
        price_usd,
    )
    return price_usd


SOLANA_PRICE_BATCH_FALLBACK_CHUNK_SIZE = 20


def _fetch_solana_pool_prices_resilient(
        pool_price_requests: list[SolanaPoolPriceRequest],
) -> tuple[dict[str, float], bool]:
    if not pool_price_requests:
        return {}, False

    encountered_infrastructure_failure = False

    try:
        return read_solana_pool_prices_usd_batch(pool_price_requests), False
    except BlockchainPriceUnavailableError:
        encountered_infrastructure_failure = True
        logger.warning(
            "[BLOCKCHAIN][PRICE][SERVICE] Batch Solana price fetch failed — falling back to chunked/per-token fetch (%d pools)",
            len(pool_price_requests),
        )

    resolved_prices_by_token_address: dict[str, float] = {}
    chunk_size = SOLANA_PRICE_BATCH_FALLBACK_CHUNK_SIZE

    for chunk_start_index in range(0, len(pool_price_requests), chunk_size):
        chunk = pool_price_requests[chunk_start_index:chunk_start_index + chunk_size]
        try:
            chunk_prices = read_solana_pool_prices_usd_batch(chunk)
            resolved_prices_by_token_address.update(chunk_prices)
            continue
        except BlockchainPriceUnavailableError:
            encountered_infrastructure_failure = True

        for pool_price_request in chunk:
            if pool_price_request.token_address in resolved_prices_by_token_address:
                continue
            try:
                price_usd = read_solana_pool_price_usd(
                    pool_price_request.pair_address,
                    pool_price_request.token_address,
                    pool_price_request.dex_id,
                )
            except BlockchainPriceUnavailableError:
                encountered_infrastructure_failure = True
                continue
            if price_usd is not None and price_usd > 0.0:
                resolved_prices_by_token_address[pool_price_request.token_address] = price_usd

    had_infrastructure_failure = encountered_infrastructure_failure and not resolved_prices_by_token_address
    return resolved_prices_by_token_address, had_infrastructure_failure


def fetch_onchain_prices_for_tokens_with_metadata(
        tokens: list[Token],
        *,
        require_all_prices: bool = True,
) -> OnchainPricesFetchResult:
    onchain_prices = _build_onchain_prices_for_tokens(
        tokens,
        require_all_prices=require_all_prices,
    )
    return onchain_prices


def fetch_onchain_prices_for_tokens(
        tokens: list[Token],
        *,
        require_all_prices: bool = True,
) -> OnchainPricesByPairAddress:
    return fetch_onchain_prices_for_tokens_with_metadata(
        tokens,
        require_all_prices=require_all_prices,
    ).onchain_prices


def _build_onchain_prices_for_tokens(
        tokens: list[Token],
        *,
        require_all_prices: bool = True,
) -> OnchainPricesFetchResult:
    if not tokens:
        return OnchainPricesFetchResult(
            onchain_prices=OnchainPricesByPairAddress.empty(),
            had_infrastructure_failure=False,
        )

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
        return OnchainPricesFetchResult(
            onchain_prices=OnchainPricesByPairAddress.empty(),
            had_infrastructure_failure=False,
        )

    logger.info("[BLOCKCHAIN][PRICE][SERVICE] Fetching on-chain prices for %d tokens", len(tokens_requiring_price))

    resolved_pair_address_prices: list[PairAddressOnchainPrice] = []
    seen_pair_addresses: set[str] = set()
    had_infrastructure_failure = False

    solana_tokens = [
        token for token in tokens_requiring_price if token.chain == BlockchainNetwork.SOLANA
    ]
    other_tokens = [
        token for token in tokens_requiring_price if token.chain != BlockchainNetwork.SOLANA
    ]

    if solana_tokens:
        seen_solana_pair_addresses: set[str] = set()
        pool_price_requests: list[SolanaPoolPriceRequest] = []
        for solana_token in solana_tokens:
            if solana_token.pair_address not in seen_solana_pair_addresses:
                seen_solana_pair_addresses.add(solana_token.pair_address)
                pool_price_requests.append(
                    SolanaPoolPriceRequest(
                        token_address=solana_token.token_address,
                        pair_address=solana_token.pair_address,
                        dex_id=solana_token.dex_id,
                    ),
                )

        solana_prices_by_token_address, solana_had_infrastructure_failure = _fetch_solana_pool_prices_resilient(
            pool_price_requests,
        )
        had_infrastructure_failure = had_infrastructure_failure or solana_had_infrastructure_failure

        for solana_token in solana_tokens:
            if solana_token.pair_address in seen_pair_addresses:
                continue
            price_usd = solana_prices_by_token_address.get(solana_token.token_address)
            if price_usd is None or price_usd <= 0.0:
                if require_all_prices:
                    raise BlockchainPriceUnavailableError(
                        f"[BLOCKCHAIN][PRICE][SERVICE] No valid Solana on-chain price for {solana_token.symbol}",
                        blockchain_network=BlockchainNetwork.SOLANA,
                    )
                continue
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

        if token.chain not in get_supported_evm_chains():
            if require_all_prices:
                raise BlockchainPriceUnavailableError(
                    f"[BLOCKCHAIN][PRICE][SERVICE] Unsupported chain {token.chain.value} for token {token.symbol}",
                    blockchain_network=token.chain,
                )
            continue

        web3_provider = resolve_web3_provider_for_chain(token.chain)
        if web3_provider is None:
            if require_all_prices:
                raise BlockchainPriceUnavailableError(
                    f"[BLOCKCHAIN][PRICE][SERVICE] No RPC provider for chain {token.chain.value}",
                    blockchain_network=token.chain,
                )
            had_infrastructure_failure = True
            continue

        price_usd = read_evm_pair_price_usd(
            web3_provider,
            token.chain,
            token.pair_address,
            token.token_address,
        )
        if price_usd is None or price_usd <= 0.0:
            if require_all_prices:
                raise BlockchainPriceUnavailableError(
                    f"[BLOCKCHAIN][PRICE][SERVICE] No valid on-chain price for {token.symbol} "
                    f"({token.pair_address[:10]}) on {token.chain.value}",
                    blockchain_network=token.chain,
                )
            continue

        resolved_pair_address_prices.append(
            PairAddressOnchainPrice(
                pair_address=token.pair_address,
                price_usd=price_usd,
            ),
        )
        seen_pair_addresses.add(token.pair_address)
        logger.debug(
            "[BLOCKCHAIN][PRICE][SERVICE] %s (%s) = %.12f USD",
            token.symbol,
            token.pair_address[:10],
            price_usd,
        )

    logger.debug(
        "[BLOCKCHAIN][PRICE][SERVICE] Resolved %d / %d token prices",
        len(resolved_pair_address_prices),
        len(tokens_requiring_price),
    )
    return OnchainPricesFetchResult(
        onchain_prices=OnchainPricesByPairAddress(pair_address_prices=resolved_pair_address_prices),
        had_infrastructure_failure=had_infrastructure_failure,
    )
