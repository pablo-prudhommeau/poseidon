from __future__ import annotations

from typing import Optional

from web3 import Web3
from web3.exceptions import ContractLogicError

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.evm.blockchain_evm_structures import (
    EVM_CHAIN_PRICE_METADATA_REGISTRY,
    EvmPoolPriceInQuote,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

NATIVE_CURRENCY_ADDRESS = "0x0000000000000000000000000000000000000000"

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
            {"name": "unlocked", "type": "bool"},
        ],
    },
]

UNISWAP_V4_STATE_VIEW_ABI = [
    {
        "name": "getSlot0",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "poolId", "type": "bytes32"}],
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "protocolFee", "type": "uint24"},
            {"name": "lpFee", "type": "uint24"},
        ],
    },
]

UNISWAP_V4_POSITION_MANAGER_ABI = [
    {
        "name": "poolKeys",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "poolId", "type": "bytes25"}],
        "outputs": [
            {"name": "currency0", "type": "address"},
            {"name": "currency1", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "tickSpacing", "type": "int24"},
            {"name": "hooks", "type": "address"},
        ],
    },
]


def _is_native_currency_address(token_address: str) -> bool:
    return token_address.lower() == NATIVE_CURRENCY_ADDRESS


def _is_stablecoin(chain: BlockchainNetwork, token_address: str) -> bool:
    chain_price_metadata = EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(chain)
    return token_address.lower() in chain_price_metadata.stablecoin_addresses


def _is_native_wrapped_token(chain: BlockchainNetwork, token_address: str) -> bool:
    chain_price_metadata = EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(chain)
    return token_address.lower() == chain_price_metadata.native_wrapped_token_address


def _is_native_gas_token_quote(chain: BlockchainNetwork, token_address: str) -> bool:
    return _is_native_currency_address(token_address) or _is_native_wrapped_token(chain, token_address)


def is_evm_quote_token_usd_convertible(
        blockchain_network: BlockchainNetwork,
        quote_token_address: str,
) -> bool:
    normalized_quote_token_address = quote_token_address.strip()
    if not normalized_quote_token_address:
        return False

    try:
        EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(blockchain_network)
    except ValueError:
        return False

    return (
            _is_stablecoin(blockchain_network, normalized_quote_token_address)
            or _is_native_gas_token_quote(blockchain_network, normalized_quote_token_address)
    )


def _is_uniswap_v4_pool_identifier(pair_address: str) -> bool:
    normalized_pair_address = pair_address.strip().lower()
    if not normalized_pair_address.startswith("0x"):
        return False
    hexadecimal_body = normalized_pair_address[2:]
    if len(hexadecimal_body) != 64:
        return False
    try:
        int(hexadecimal_body, 16)
    except ValueError:
        return False
    return not Web3.is_address(pair_address)


def _truncate_pool_identifier_to_bytes25(pool_identifier: str) -> bytes:
    normalized_pool_identifier = pool_identifier.strip().lower()
    pool_identifier_bytes = bytes.fromhex(normalized_pool_identifier[2:])
    return pool_identifier_bytes[:25]


def _resolve_price_in_quote_from_square_root_price_x96(
        square_root_price_x96: int,
        target_is_currency_zero: bool,
        currency_zero_decimals: int,
        currency_one_decimals: int,
) -> Optional[float]:
    if square_root_price_x96 <= 0:
        return None

    price_of_currency_one_in_currency_zero = (square_root_price_x96 / (2 ** 96)) ** 2
    if price_of_currency_one_in_currency_zero <= 0.0:
        return None

    if target_is_currency_zero:
        return price_of_currency_one_in_currency_zero * (10 ** (currency_zero_decimals - currency_one_decimals))

    return (1.0 / price_of_currency_one_in_currency_zero) * (10 ** (currency_one_decimals - currency_zero_decimals))


def _fetch_token_decimals(web3_provider: Web3, token_address: str) -> int:
    if _is_native_currency_address(token_address):
        return 18

    if not Web3.is_address(token_address):
        raise ValueError(f"Invalid token address for decimals lookup: {token_address}")

    checksum_address = Web3.to_checksum_address(token_address)
    token_contract = web3_provider.eth.contract(address=checksum_address, abi=ERC20_DECIMALS_ABI)
    decimals_value = token_contract.functions.decimals().call()
    logger.debug("[BLOCKCHAIN][PRICE][EVM] Fetched decimals for %s = %d", token_address[:10], decimals_value)
    return decimals_value


def _fetch_uniswap_v4_pool_price_in_quote(
        web3_provider: Web3,
        chain: BlockchainNetwork,
        pool_identifier: str,
        target_token_address: str,
) -> Optional[EvmPoolPriceInQuote]:
    chain_price_metadata = EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(chain)
    state_view_contract_address = chain_price_metadata.uniswap_v4_state_view_contract_address
    position_manager_contract_address = chain_price_metadata.uniswap_v4_position_manager_contract_address
    if state_view_contract_address is None or position_manager_contract_address is None:
        logger.debug(
            "[BLOCKCHAIN][PRICE][EVM][V4] No StateView/PositionManager configured for chain %s",
            chain.value,
        )
        return None

    if not Web3.is_address(target_token_address):
        logger.debug(
            "[BLOCKCHAIN][PRICE][EVM][V4] Invalid target token address %s on %s",
            target_token_address[:10],
            chain.value,
        )
        return None

    try:
        position_manager_contract = web3_provider.eth.contract(
            address=Web3.to_checksum_address(position_manager_contract_address),
            abi=UNISWAP_V4_POSITION_MANAGER_ABI,
        )
        truncated_pool_identifier = _truncate_pool_identifier_to_bytes25(pool_identifier)
        pool_key = position_manager_contract.functions.poolKeys(truncated_pool_identifier).call()
        currency_zero_address = pool_key[0]
        currency_one_address = pool_key[1]
        tick_spacing = pool_key[3]

        if tick_spacing == 0:
            logger.debug(
                "[BLOCKCHAIN][PRICE][EVM][V4] PoolKey missing for pool_identifier=%s on %s",
                pool_identifier[:10],
                chain.value,
            )
            return None

        state_view_contract = web3_provider.eth.contract(
            address=Web3.to_checksum_address(state_view_contract_address),
            abi=UNISWAP_V4_STATE_VIEW_ABI,
        )
        normalized_pool_identifier = pool_identifier.strip().lower()
        pool_identifier_bytes32 = bytes.fromhex(normalized_pool_identifier[2:])
        slot0 = state_view_contract.functions.getSlot0(pool_identifier_bytes32).call()
        square_root_price_x96 = slot0[0]

        currency_zero_decimals = _fetch_token_decimals(web3_provider, currency_zero_address)
        currency_one_decimals = _fetch_token_decimals(web3_provider, currency_one_address)

        target_is_currency_zero = currency_zero_address.lower() == target_token_address.lower()
        target_is_currency_one = currency_one_address.lower() == target_token_address.lower()
        if not target_is_currency_zero and not target_is_currency_one:
            logger.debug(
                "[BLOCKCHAIN][PRICE][EVM][V4] Target token %s not in pool currencies on %s",
                target_token_address[:10],
                chain.value,
            )
            return None

        price_in_quote_token = _resolve_price_in_quote_from_square_root_price_x96(
            square_root_price_x96=square_root_price_x96,
            target_is_currency_zero=target_is_currency_zero,
            currency_zero_decimals=currency_zero_decimals,
            currency_one_decimals=currency_one_decimals,
        )
        if price_in_quote_token is None or price_in_quote_token <= 0.0:
            return None

        quote_token_address = currency_one_address if target_is_currency_zero else currency_zero_address
        logger.debug(
            "[BLOCKCHAIN][PRICE][EVM][V4] Resolved pool_identifier=%s price_in_quote=%.12f quote=%s on %s",
            pool_identifier[:10],
            price_in_quote_token,
            quote_token_address[:10],
            chain.value,
        )
        return EvmPoolPriceInQuote(
            price_in_quote_token=price_in_quote_token,
            quote_token_address=quote_token_address,
        )
    except Exception:
        logger.exception(
            "[BLOCKCHAIN][PRICE][EVM][V4] Failed to read pool_identifier=%s on %s",
            pool_identifier[:10],
            chain.value,
        )
        return None


def _fetch_uniswap_v2_or_v3_pool_price_in_quote(
        web3_provider: Web3,
        chain: BlockchainNetwork,
        pair_address: str,
        target_token_address: str,
) -> Optional[EvmPoolPriceInQuote]:
    if not Web3.is_address(pair_address) or not Web3.is_address(target_token_address):
        logger.debug(
            "[BLOCKCHAIN][PRICE][EVM] Invalid address format for pair=%s token=%s on %s",
            pair_address[:10],
            target_token_address[:10],
            chain.value,
        )
        return None

    checksum_pair = Web3.to_checksum_address(pair_address)
    pair_contract = web3_provider.eth.contract(address=checksum_pair, abi=UNISWAP_V2_PAIR_ABI)

    currency_zero_address = pair_contract.functions.token0().call()
    currency_one_address = pair_contract.functions.token1().call()

    currency_zero_decimals = _fetch_token_decimals(web3_provider, currency_zero_address)
    currency_one_decimals = _fetch_token_decimals(web3_provider, currency_one_address)

    target_is_currency_zero = currency_zero_address.lower() == target_token_address.lower()
    target_is_currency_one = currency_one_address.lower() == target_token_address.lower()
    if not target_is_currency_zero and not target_is_currency_one:
        logger.debug(
            "[BLOCKCHAIN][PRICE][EVM] Target token %s is not in V2/V3 pool %s on %s",
            target_token_address[:10],
            pair_address[:10],
            chain.value,
        )
        return None

    quote_token_address = currency_one_address if target_is_currency_zero else currency_zero_address

    try:
        reserves = pair_contract.functions.getReserves().call()
        reserve_zero = reserves[0]
        reserve_one = reserves[1]

        if reserve_zero <= 0 or reserve_one <= 0:
            return None

        adjusted_reserve_zero = reserve_zero / (10 ** currency_zero_decimals)
        adjusted_reserve_one = reserve_one / (10 ** currency_one_decimals)

        if target_is_currency_zero:
            base_reserve = adjusted_reserve_zero
            quote_reserve = adjusted_reserve_one
        else:
            base_reserve = adjusted_reserve_one
            quote_reserve = adjusted_reserve_zero

        if base_reserve <= 0.0:
            return None

        return EvmPoolPriceInQuote(
            price_in_quote_token=quote_reserve / base_reserve,
            quote_token_address=quote_token_address,
        )

    except Exception as exception:
        if not isinstance(exception, ContractLogicError):
            raise

    v3_contract = web3_provider.eth.contract(address=checksum_pair, abi=UNISWAP_V3_POOL_ABI)
    slot0 = v3_contract.functions.slot0().call()
    square_root_price_x96 = slot0[0]

    price_in_quote_token = _resolve_price_in_quote_from_square_root_price_x96(
        square_root_price_x96=square_root_price_x96,
        target_is_currency_zero=target_is_currency_zero,
        currency_zero_decimals=currency_zero_decimals,
        currency_one_decimals=currency_one_decimals,
    )
    if price_in_quote_token is None or price_in_quote_token <= 0.0:
        return None

    return EvmPoolPriceInQuote(
        price_in_quote_token=price_in_quote_token,
        quote_token_address=quote_token_address,
    )


def _fetch_pool_price_in_quote(
        web3_provider: Web3,
        chain: BlockchainNetwork,
        pair_address: str,
        target_token_address: str,
) -> Optional[EvmPoolPriceInQuote]:
    if _is_uniswap_v4_pool_identifier(pair_address):
        return _fetch_uniswap_v4_pool_price_in_quote(
            web3_provider=web3_provider,
            chain=chain,
            pool_identifier=pair_address,
            target_token_address=target_token_address,
        )

    return _fetch_uniswap_v2_or_v3_pool_price_in_quote(
        web3_provider=web3_provider,
        chain=chain,
        pair_address=pair_address,
        target_token_address=target_token_address,
    )


def _read_native_token_usd_price(web3_provider: Web3, chain: BlockchainNetwork) -> Optional[float]:
    chain_price_metadata = EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(chain)

    try:
        pool_price_in_quote = _fetch_pool_price_in_quote(
            web3_provider=web3_provider,
            chain=chain,
            pair_address=chain_price_metadata.native_token_reference_stablecoin_pair_address,
            target_token_address=chain_price_metadata.native_wrapped_token_address,
        )
        if pool_price_in_quote is None or pool_price_in_quote.price_in_quote_token <= 0.0:
            return None

        logger.debug(
            "[BLOCKCHAIN][PRICE][EVM] Native token price on %s = %.4f USD",
            chain.value,
            pool_price_in_quote.price_in_quote_token,
        )
        return pool_price_in_quote.price_in_quote_token
    except Exception:
        logger.exception("[BLOCKCHAIN][PRICE][EVM] Failed to read native token price on %s", chain.value)
        return None


def read_evm_native_token_price_usd(web3_provider: Web3, chain: BlockchainNetwork) -> Optional[float]:
    return _read_native_token_usd_price(web3_provider, chain)


def read_evm_pair_price_usd(
        web3_provider: Web3,
        chain: BlockchainNetwork,
        pair_address: str,
        target_token_address: str,
) -> Optional[float]:
    try:
        pool_price_in_quote = _fetch_pool_price_in_quote(
            web3_provider=web3_provider,
            chain=chain,
            pair_address=pair_address,
            target_token_address=target_token_address,
        )
        if pool_price_in_quote is None:
            return None

        price_in_quote_token = pool_price_in_quote.price_in_quote_token
        quote_token_address = pool_price_in_quote.quote_token_address

        if _is_stablecoin(chain, quote_token_address):
            logger.debug(
                "[BLOCKCHAIN][PRICE][EVM] Pair %s — price %.12f (quote is stablecoin)",
                pair_address[:10],
                price_in_quote_token,
            )
            return price_in_quote_token

        if _is_native_gas_token_quote(chain, quote_token_address):
            native_usd_price = _read_native_token_usd_price(web3_provider, chain)
            if native_usd_price is None or native_usd_price <= 0.0:
                logger.debug(
                    "[BLOCKCHAIN][PRICE][EVM] Cannot resolve native USD price on %s for pair %s",
                    chain.value,
                    pair_address[:10],
                )
                return None
            price_usd = price_in_quote_token * native_usd_price
            logger.debug(
                "[BLOCKCHAIN][PRICE][EVM] Pair %s — price %.12f USD (via native at %.2f)",
                pair_address[:10],
                price_usd,
                native_usd_price,
            )
            return price_usd

        logger.debug(
            "[BLOCKCHAIN][PRICE][EVM] Pair %s — unknown quote token %s, cannot convert to USD",
            pair_address[:10],
            quote_token_address[:10],
        )
        return None

    except Exception:
        logger.exception(
            "[BLOCKCHAIN][PRICE][EVM] Failed to read price for pair %s on %s",
            pair_address[:10],
            chain.value,
        )
        return None
