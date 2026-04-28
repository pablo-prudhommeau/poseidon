from __future__ import annotations

from typing import Optional

from web3 import Web3

from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

UNISWAP_V2_PAIR_ABI = [
    {
        "name": "getReserves",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "reserve0", "type": "uint112"},
            {"name": "reserve1", "type": "uint112"},
            {"name": "blockTimestampLast", "type": "uint32"},
        ],
    },
    {
        "name": "token0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
    {
        "name": "token1",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "address"}],
    },
]

ERC20_DECIMALS_ABI = [
    {
        "name": "decimals",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint8"}],
    },
]

UNISWAP_V3_POOL_ABI = [
    {
        "name": "slot0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"}
        ],
    },
]

KNOWN_STABLECOINS: dict[str, set[str]] = {
    "bsc": {
        "0x55d398326f99059ff775485246999027b3197955",
        "0xe9e7cea3dedca5984780bafc599bd69add087d56",
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",
    },
    "ethereum": {
        "0xdac17f958d2ee523a2206206994597c13d831ec7",
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "0x6b175474e89094c44da98b954eedeac495271d0f",
    },
    "base": {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
    },
    "arbitrum": {
        "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
        "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",
    },
}

KNOWN_NATIVE_WRAPPED_TOKENS: dict[str, str] = {
    "bsc": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
    "ethereum": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "base": "0x4200000000000000000000000000000000000006",
    "arbitrum": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
}

NATIVE_TOKEN_REFERENCE_STABLECOIN_PAIRS: dict[str, str] = {
    "bsc": "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae",
    "ethereum": "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852",
    "base": "0xd0b53d9277642d899df5c87a3966a349a798f224",
}

_decimals_cache: dict[str, int] = {}


def _is_stablecoin(chain_identifier: str, token_address: str) -> bool:
    normalized_address = token_address.lower()
    chain_stablecoins = KNOWN_STABLECOINS.get(chain_identifier.lower(), set())
    return normalized_address in chain_stablecoins


def _is_native_wrapped_token(chain_identifier: str, token_address: str) -> bool:
    normalized_address = token_address.lower()
    known_native = KNOWN_NATIVE_WRAPPED_TOKENS.get(chain_identifier.lower())
    return known_native is not None and normalized_address == known_native


def _fetch_token_decimals(web3_provider: Web3, token_address: str) -> int:
    cache_key = f"{web3_provider.eth.chain_id}:{token_address.lower()}"
    cached_value = _decimals_cache.get(cache_key)
    if cached_value is not None:
        return cached_value

    if not Web3.is_address(token_address):
        return 18

    checksum_address = Web3.to_checksum_address(token_address)
    token_contract = web3_provider.eth.contract(address=checksum_address, abi=ERC20_DECIMALS_ABI)
    decimals_value = token_contract.functions.decimals().call()
    _decimals_cache[cache_key] = decimals_value
    logger.debug("[BLOCKCHAIN][PRICE][EVM] Fetched decimals for %s = %d", token_address[:10], decimals_value)
    return decimals_value


def _fetch_pool_price_in_quote(
        web3_provider: Web3,
        chain_identifier: str,
        pair_address: str,
        target_token_address: str,
) -> tuple[Optional[float], Optional[str]]:
    if not Web3.is_address(pair_address) or not Web3.is_address(target_token_address):
        logger.debug("[BLOCKCHAIN][PRICE][EVM] Invalid address format for pair=%s token=%s on %s", pair_address[:10], target_token_address[:10], chain_identifier)
        return None, None

    checksum_pair = Web3.to_checksum_address(pair_address)
    pair_contract = web3_provider.eth.contract(address=checksum_pair, abi=UNISWAP_V2_PAIR_ABI)

    token0_address = pair_contract.functions.token0().call()
    token1_address = pair_contract.functions.token1().call()

    token0_decimals = _fetch_token_decimals(web3_provider, token0_address)
    token1_decimals = _fetch_token_decimals(web3_provider, token1_address)

    target_is_token0 = token0_address.lower() == target_token_address.lower()
    quote_address = token1_address if target_is_token0 else token0_address

    try:
        reserves = pair_contract.functions.getReserves().call()
        reserve0 = reserves[0]
        reserve1 = reserves[1]

        if reserve0 <= 0 or reserve1 <= 0:
            return None, None

        adjusted_reserve0 = reserve0 / (10 ** token0_decimals)
        adjusted_reserve1 = reserve1 / (10 ** token1_decimals)

        if target_is_token0:
            base_reserve = adjusted_reserve0
            quote_reserve = adjusted_reserve1
        else:
            base_reserve = adjusted_reserve1
            quote_reserve = adjusted_reserve0

        if base_reserve <= 0.0:
            return None, None

        price_in_quote = quote_reserve / base_reserve
        return price_in_quote, quote_address

    except Exception as exception:
        from web3.exceptions import ContractLogicError
        if not isinstance(exception, ContractLogicError):
            raise

    v3_contract = web3_provider.eth.contract(address=checksum_pair, abi=UNISWAP_V3_POOL_ABI)
    slot0 = v3_contract.functions.slot0().call()
    sqrt_price_x96 = slot0[0]

    if sqrt_price_x96 <= 0:
        return None, None

    raw_ratio_1_over_0 = (sqrt_price_x96 / (2 ** 96)) ** 2

    if target_is_token0:
        price_in_quote = raw_ratio_1_over_0 * (10 ** (token0_decimals - token1_decimals))
    else:
        price_in_quote = (1.0 / raw_ratio_1_over_0) * (10 ** (token1_decimals - token0_decimals))

    return price_in_quote, quote_address


def _read_native_token_usd_price(web3_provider: Web3, chain_identifier: str) -> Optional[float]:
    reference_pair_address = NATIVE_TOKEN_REFERENCE_STABLECOIN_PAIRS.get(chain_identifier.lower())
    if reference_pair_address is None:
        logger.debug("[BLOCKCHAIN][PRICE][EVM] No reference pair configured for native token on chain %s", chain_identifier)
        return None

    try:
        native_address = KNOWN_NATIVE_WRAPPED_TOKENS.get(chain_identifier.lower(), "")
        if not native_address:
            return None

        price_in_quote, quote_address = _fetch_pool_price_in_quote(
            web3_provider, chain_identifier, reference_pair_address, native_address
        )
        if price_in_quote is None or price_in_quote <= 0.0:
            return None

        logger.debug("[BLOCKCHAIN][PRICE][EVM] Native token price on %s = %.4f USD", chain_identifier, price_in_quote)
        return price_in_quote
    except Exception as exception:
        logger.exception("[BLOCKCHAIN][PRICE][EVM] Failed to read native token price on %s", chain_identifier)
        return None


def read_evm_pair_price_usd(
        web3_provider: Web3,
        chain_identifier: str,
        pair_address: str,
        target_token_address: str,
) -> Optional[float]:
    try:
        price_in_quote, quote_address = _fetch_pool_price_in_quote(
            web3_provider, chain_identifier, pair_address, target_token_address
        )
        if price_in_quote is None or quote_address is None:
            return None

        if _is_stablecoin(chain_identifier, quote_address):
            logger.debug(
                "[BLOCKCHAIN][PRICE][EVM] Pair %s — price %.12f (quote is stablecoin)",
                pair_address[:10], price_in_quote,
            )
            return price_in_quote

        if _is_native_wrapped_token(chain_identifier, quote_address):
            native_usd_price = _read_native_token_usd_price(web3_provider, chain_identifier)
            if native_usd_price is None or native_usd_price <= 0.0:
                logger.debug("[BLOCKCHAIN][PRICE][EVM] Cannot resolve native USD price on %s for pair %s", chain_identifier, pair_address[:10])
                return None
            price_usd = price_in_quote * native_usd_price
            logger.debug(
                "[BLOCKCHAIN][PRICE][EVM] Pair %s — price %.12f USD (via native at %.2f)",
                pair_address[:10], price_usd, native_usd_price,
            )
            return price_usd

        logger.debug(
            "[BLOCKCHAIN][PRICE][EVM] Pair %s — unknown quote token %s, cannot convert to USD",
            pair_address[:10], quote_address[:10],
        )
        return None

    except Exception as exception:
        logger.exception("[BLOCKCHAIN][PRICE][EVM] Failed to read price for pair %s on %s", pair_address[:10], chain_identifier)
        return None
