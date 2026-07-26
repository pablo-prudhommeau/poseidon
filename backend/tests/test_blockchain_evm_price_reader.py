from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.evm.blockchain_evm_price_reader import (
    NATIVE_CURRENCY_ADDRESS,
    _fetch_pool_price_in_quote,
    _is_uniswap_v4_pool_identifier,
    read_evm_pair_price_usd,
)
from src.integrations.blockchain.evm.blockchain_evm_structures import (
    EVM_CHAIN_PRICE_METADATA_REGISTRY,
    EvmPoolPriceInQuote,
)

ROBINHOOD_USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
ROBINHOOD_WETH = "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"
ROBINHOOD_PAIR = "0xe22DB3a8a0000000000000000000000000000001"
ROBINHOOD_TARGET_TOKEN = "0x839b8bd800000000000000000000000000000001"
ROBINHOOD_LAUNCH_POOL_IDENTIFIER = (
    "0x379c011a6df9bbac370a2789693a0cc1bcc089ff4ad38a0b0827a68292f4d6a3"
)
ROBINHOOD_LAUNCH_TOKEN_ADDRESS = "0x63575bCC0000000000000000000000000000C0de"


def test_robinhood_chain_price_metadata_is_configured() -> None:
    robinhood_metadata = EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(BlockchainNetwork.ROBINHOOD)
    assert ROBINHOOD_USDG.lower() in robinhood_metadata.stablecoin_addresses
    assert robinhood_metadata.native_wrapped_token_address == ROBINHOOD_WETH.lower()
    assert robinhood_metadata.native_token_reference_stablecoin_pair_address == (
        "0x69bfaf19c9f377bb306a89aed9f6b07e2c1a8d9a"
    )
    assert robinhood_metadata.uniswap_v4_state_view_contract_address is not None
    assert robinhood_metadata.uniswap_v4_position_manager_contract_address is not None


def test_is_uniswap_v4_pool_identifier_detects_bytes32_pool_id() -> None:
    assert _is_uniswap_v4_pool_identifier(ROBINHOOD_LAUNCH_POOL_IDENTIFIER) is True
    assert _is_uniswap_v4_pool_identifier(ROBINHOOD_PAIR) is False
    assert _is_uniswap_v4_pool_identifier(ROBINHOOD_WETH) is False


@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._fetch_pool_price_in_quote",
    return_value=EvmPoolPriceInQuote(
        price_in_quote_token=0.0025,
        quote_token_address=ROBINHOOD_USDG,
    ),
)
def test_read_evm_pair_price_usd_robinhood_stablecoin_quote(
        _fetch_pool_price_in_quote_mock: MagicMock,
) -> None:
    price_usd = read_evm_pair_price_usd(
        web3_provider=MagicMock(),
        chain=BlockchainNetwork.ROBINHOOD,
        pair_address=ROBINHOOD_PAIR,
        target_token_address=ROBINHOOD_TARGET_TOKEN,
    )

    assert price_usd == 0.0025


@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._read_native_token_usd_price",
    return_value=3000.0,
)
@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._fetch_pool_price_in_quote",
    return_value=EvmPoolPriceInQuote(
        price_in_quote_token=0.0001,
        quote_token_address=ROBINHOOD_WETH,
    ),
)
def test_read_evm_pair_price_usd_robinhood_weth_quote(
        _fetch_pool_price_in_quote_mock: MagicMock,
        _read_native_token_usd_price_mock: MagicMock,
) -> None:
    price_usd = read_evm_pair_price_usd(
        web3_provider=MagicMock(),
        chain=BlockchainNetwork.ROBINHOOD,
        pair_address=ROBINHOOD_PAIR,
        target_token_address=ROBINHOOD_TARGET_TOKEN,
    )

    assert price_usd == 0.3


@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._read_native_token_usd_price",
    return_value=2000.0,
)
@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._fetch_pool_price_in_quote",
    return_value=EvmPoolPriceInQuote(
        price_in_quote_token=0.00015,
        quote_token_address=NATIVE_CURRENCY_ADDRESS,
    ),
)
def test_read_evm_pair_price_usd_robinhood_native_currency_quote(
        _fetch_pool_price_in_quote_mock: MagicMock,
        _read_native_token_usd_price_mock: MagicMock,
) -> None:
    price_usd = read_evm_pair_price_usd(
        web3_provider=MagicMock(),
        chain=BlockchainNetwork.ROBINHOOD,
        pair_address=ROBINHOOD_LAUNCH_POOL_IDENTIFIER,
        target_token_address=ROBINHOOD_LAUNCH_TOKEN_ADDRESS,
    )

    assert price_usd == 0.3


@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._fetch_uniswap_v4_pool_price_in_quote",
)
def test_fetch_pool_price_in_quote_routes_bytes32_to_uniswap_v4(
        fetch_uniswap_v4_pool_price_in_quote_mock: MagicMock,
) -> None:
    expected = EvmPoolPriceInQuote(
        price_in_quote_token=0.0002,
        quote_token_address=NATIVE_CURRENCY_ADDRESS,
    )
    fetch_uniswap_v4_pool_price_in_quote_mock.return_value = expected

    result = _fetch_pool_price_in_quote(
        web3_provider=MagicMock(),
        chain=BlockchainNetwork.ROBINHOOD,
        pair_address=ROBINHOOD_LAUNCH_POOL_IDENTIFIER,
        target_token_address=ROBINHOOD_LAUNCH_TOKEN_ADDRESS,
    )

    assert result == expected
    fetch_uniswap_v4_pool_price_in_quote_mock.assert_called_once()


@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._fetch_token_decimals",
    side_effect=lambda _web3_provider, token_address: 18,
)
def test_fetch_uniswap_v4_pool_price_in_quote_resolves_native_quote_when_target_is_currency_zero(
        _fetch_token_decimals_mock: MagicMock,
) -> None:
    from src.integrations.blockchain.evm.blockchain_evm_price_reader import (
        _fetch_uniswap_v4_pool_price_in_quote,
    )

    robinhood_metadata = EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(BlockchainNetwork.ROBINHOOD)
    assert robinhood_metadata is not None
    assert robinhood_metadata.uniswap_v4_position_manager_contract_address is not None

    web3_provider = MagicMock()
    position_manager_functions = MagicMock()
    position_manager_functions.poolKeys.return_value.call.return_value = (
        ROBINHOOD_LAUNCH_TOKEN_ADDRESS,
        NATIVE_CURRENCY_ADDRESS,
        3000,
        60,
        "0x2380aBf72C17aABAb76480244759AC7E2932EEcC",
    )
    state_view_functions = MagicMock()
    square_root_price_x96 = int((0.0002 ** 0.5) * (2 ** 96))
    state_view_functions.getSlot0.return_value.call.return_value = (
        square_root_price_x96,
        0,
        0,
        3000,
    )

    def contract_factory(*_args: object, **kwargs: object) -> MagicMock:
        contract = MagicMock()
        contract_address = str(kwargs["address"])
        if contract_address.lower() == robinhood_metadata.uniswap_v4_position_manager_contract_address.lower():
            contract.functions = position_manager_functions
        else:
            contract.functions = state_view_functions
        return contract

    web3_provider.eth.contract.side_effect = contract_factory

    result = _fetch_uniswap_v4_pool_price_in_quote(
        web3_provider=web3_provider,
        chain=BlockchainNetwork.ROBINHOOD,
        pool_identifier=ROBINHOOD_LAUNCH_POOL_IDENTIFIER,
        target_token_address=ROBINHOOD_LAUNCH_TOKEN_ADDRESS,
    )

    assert result is not None
    assert result.quote_token_address == NATIVE_CURRENCY_ADDRESS
    assert abs(result.price_in_quote_token - 0.0002) < 1e-9


@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._fetch_token_decimals",
    side_effect=lambda _web3_provider, token_address: 18,
)
def test_fetch_uniswap_v4_pool_price_in_quote_inverts_ratio_when_target_is_currency_one(
        _fetch_token_decimals_mock: MagicMock,
) -> None:
    from src.integrations.blockchain.evm.blockchain_evm_price_reader import (
        _fetch_uniswap_v4_pool_price_in_quote,
    )

    robinhood_metadata = EVM_CHAIN_PRICE_METADATA_REGISTRY.resolve(BlockchainNetwork.ROBINHOOD)
    assert robinhood_metadata is not None
    assert robinhood_metadata.uniswap_v4_position_manager_contract_address is not None

    web3_provider = MagicMock()
    position_manager_functions = MagicMock()
    position_manager_functions.poolKeys.return_value.call.return_value = (
        NATIVE_CURRENCY_ADDRESS,
        ROBINHOOD_LAUNCH_TOKEN_ADDRESS,
        3000,
        60,
        "0x2380aBf72C17aABAb76480244759AC7E2932EEcC",
    )
    state_view_functions = MagicMock()
    square_root_price_x96 = int((5000.0 ** 0.5) * (2 ** 96))
    state_view_functions.getSlot0.return_value.call.return_value = (
        square_root_price_x96,
        0,
        0,
        3000,
    )

    def contract_factory(*_args: object, **kwargs: object) -> MagicMock:
        contract = MagicMock()
        contract_address = str(kwargs["address"])
        if contract_address.lower() == robinhood_metadata.uniswap_v4_position_manager_contract_address.lower():
            contract.functions = position_manager_functions
        else:
            contract.functions = state_view_functions
        return contract

    web3_provider.eth.contract.side_effect = contract_factory

    result = _fetch_uniswap_v4_pool_price_in_quote(
        web3_provider=web3_provider,
        chain=BlockchainNetwork.ROBINHOOD,
        pool_identifier=ROBINHOOD_LAUNCH_POOL_IDENTIFIER,
        target_token_address=ROBINHOOD_LAUNCH_TOKEN_ADDRESS,
    )

    assert result is not None
    assert result.quote_token_address == NATIVE_CURRENCY_ADDRESS
    assert abs(result.price_in_quote_token - 0.0002) < 1e-9


@patch(
    "src.integrations.blockchain.evm.blockchain_evm_price_reader._fetch_token_decimals",
    return_value=18,
)
def test_fetch_uniswap_v4_pool_price_in_quote_returns_none_when_tick_spacing_is_zero(
        _fetch_token_decimals_mock: MagicMock,
) -> None:
    from src.integrations.blockchain.evm.blockchain_evm_price_reader import (
        _fetch_uniswap_v4_pool_price_in_quote,
    )

    web3_provider = MagicMock()
    position_manager_functions = MagicMock()
    position_manager_functions.poolKeys.return_value.call.return_value = (
        NATIVE_CURRENCY_ADDRESS,
        ROBINHOOD_LAUNCH_TOKEN_ADDRESS,
        3000,
        0,
        "0x0000000000000000000000000000000000000000",
    )
    contract = MagicMock()
    contract.functions = position_manager_functions
    web3_provider.eth.contract.return_value = contract

    result = _fetch_uniswap_v4_pool_price_in_quote(
        web3_provider=web3_provider,
        chain=BlockchainNetwork.ROBINHOOD,
        pool_identifier=ROBINHOOD_LAUNCH_POOL_IDENTIFIER,
        target_token_address=ROBINHOOD_LAUNCH_TOKEN_ADDRESS,
    )

    assert result is None
