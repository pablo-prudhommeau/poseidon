from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.cache.cache_protocols import CacheRealmRebuildSkipped
from src.core.trading.cache.trading_cache_payload_builders import (
    _skip_live_portfolio_rebuild_when_cache_warm,
    build_trading_liquidity_payload,
)
from src.core.trading.cache.trading_cache_rebuilders import _AvailableCashRebuilder
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.solana.solana_structures import SolanaRpcFailureReason
from src.core.structures.structures import BlockchainNetwork


@patch("src.core.trading.cache.trading_cache_payload_builders.trading_cache")
def test_skip_live_portfolio_rebuild_raises_when_cache_warm(trading_cache_mock: MagicMock) -> None:
    trading_cache_mock.get_trading_state.return_value.portfolio = MagicMock()

    with pytest.raises(CacheRealmRebuildSkipped):
        _skip_live_portfolio_rebuild_when_cache_warm("test skip reason")


@patch("src.core.trading.cache.trading_cache_payload_builders.trading_cache")
def test_skip_live_portfolio_rebuild_returns_none_when_cache_cold(trading_cache_mock: MagicMock) -> None:
    trading_cache_mock.get_trading_state.return_value.portfolio = None

    result = _skip_live_portfolio_rebuild_when_cache_warm("test skip reason")

    assert result is None


@patch("src.core.trading.cache.trading_cache_payload_builders.settings")
@patch("src.core.trading.cache.trading_cache_payload_builders.has_any_closing_positions")
@patch("src.core.trading.cache.trading_cache_payload_builders.fetch_stablecoin_balances_for_allowed_chains")
@patch(
    "src.core.trading.cache.trading_cache_payload_builders.resolve_gas_reserve_chain_handlers_for_liquidity_payload",
)
def test_build_trading_liquidity_payload_raises_when_solana_context_missing(
        resolve_chain_handlers_mock: MagicMock,
        fetch_balances_mock: MagicMock,
        has_any_closing_positions_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.TRADING_PAPER_MODE = False
    has_any_closing_positions_mock.return_value = False
    fetch_balances_mock.return_value = []
    resolve_chain_handlers_mock.side_effect = BlockchainRpcUnavailableError(
        "wallet context unavailable",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="wallet_context",
        failure_reason=SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
    )

    with pytest.raises(BlockchainRpcUnavailableError):
        build_trading_liquidity_payload()


@patch("src.core.trading.cache.trading_cache_rebuilders.trading_cache")
@patch("src.core.trading.cache.trading_cache_rebuilders.build_trading_liquidity_payload")
def test_available_cash_rebuilder_skips_when_cached_liquidity_exists(
        build_liquidity_mock: MagicMock,
        trading_cache_mock: MagicMock,
) -> None:
    build_liquidity_mock.side_effect = BlockchainRpcUnavailableError(
        "wallet context unavailable",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="wallet_context",
        failure_reason=SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
    )
    trading_cache_mock.get_trading_liquidity_state.return_value = MagicMock()
    rebuilder = _AvailableCashRebuilder()

    with pytest.raises(CacheRealmRebuildSkipped):
        rebuilder.rebuild()
