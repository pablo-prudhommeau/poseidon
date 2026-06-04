from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.core.structures.structures import BlockchainNetwork, Token
from src.core.trading.execution.evm.trading_execution_evm_handler import TradingExecutionEvmHandler
from src.core.trading.execution.trading_execution_blockchain_route_service import (
    build_route_for_live_execution,
    build_route_for_live_sell,
)
from src.core.trading.execution.solana.trading_execution_solana_service import (
    build_solana_buy_route,
    build_solana_sell_route,
)
from src.core.trading.screener.trading_screener_structures import TradingScreenerEnvelope
from src.core.trading.trading_structures import (
    TradingCandidate,
    TradingCandidateAiAnalysis,
    TradingDexMarketSnapshot,
)
from src.integrations.blockchain.blockchain_exceptions import (
    BlockchainExecutionRouteBuildError,
    BlockchainTradingNotSupportedError,
)
from src.integrations.jupiter.jupiter_structures import JupiterApiFailureReason, JupiterApiUnavailableError


def _build_market_snapshot() -> TradingDexMarketSnapshot:
    return TradingDexMarketSnapshot(
        price_usd=1.0,
        price_native=1.0,
        token_age_hours=2.0,
        volume_m5_usd=10000.0,
        volume_h1_usd=10000.0,
        volume_h6_usd=10000.0,
        volume_h24_usd=10000.0,
        liquidity_usd=10000.0,
        price_change_percentage_m5=1.0,
        price_change_percentage_h1=1.0,
        price_change_percentage_h6=1.0,
        price_change_percentage_h24=1.0,
        transaction_count_m5=10,
        transaction_count_h1=10,
        transaction_count_h6=10,
        transaction_count_h24=10,
        buy_to_sell_ratio=1.0,
        market_cap_usd=100000.0,
        fully_diluted_valuation_usd=100000.0,
    )


def _build_candidate() -> TradingCandidate:
    return TradingCandidate(
        token=Token(
            symbol="TEST",
            chain=BlockchainNetwork.SOLANA,
            token_address="token-mint-address",
            pair_address="pair-address",
            dex_id="raydium",
        ),
        market_snapshot=_build_market_snapshot(),
        screener_envelope=TradingScreenerEnvelope(provider_id="test"),
        ai_analysis=TradingCandidateAiAnalysis(adjusted_quality_score=80.0),
    )


def test_evm_build_buy_route_raises_not_supported() -> None:
    handler = TradingExecutionEvmHandler(blockchain_network=BlockchainNetwork.BSC)

    with pytest.raises(BlockchainTradingNotSupportedError):
        handler.build_buy_route(_build_candidate(), 10.0)


def test_evm_build_sell_route_raises_not_supported() -> None:
    handler = TradingExecutionEvmHandler(blockchain_network=BlockchainNetwork.BASE)

    with pytest.raises(BlockchainTradingNotSupportedError):
        handler.build_sell_route("token-mint", 1.0, 6)


def test_evm_resolve_sell_token_decimals_raises_not_supported() -> None:
    handler = TradingExecutionEvmHandler(blockchain_network=BlockchainNetwork.AVALANCHE)

    with pytest.raises(BlockchainTradingNotSupportedError):
        handler.resolve_sell_token_decimals("token-mint")


@patch("src.core.trading.execution.trading_execution_blockchain_route_service.resolve_execution_chain_handler_for_blockchain")
def test_build_route_for_live_execution_raises_when_handler_missing(
        resolve_handler_mock: MagicMock,
) -> None:
    resolve_handler_mock.return_value = None
    candidate = _build_candidate()

    with pytest.raises(BlockchainTradingNotSupportedError):
        build_route_for_live_execution(candidate, 10.0)


@patch("src.core.trading.execution.trading_execution_blockchain_route_service.resolve_execution_chain_handler_for_blockchain")
def test_build_route_for_live_sell_raises_when_handler_missing(
        resolve_handler_mock: MagicMock,
) -> None:
    resolve_handler_mock.return_value = None

    with pytest.raises(BlockchainTradingNotSupportedError):
        build_route_for_live_sell("token-mint", BlockchainNetwork.BSC, 1.0, 6)


def test_build_solana_buy_route_raises_when_token_mint_missing() -> None:
    candidate = _build_candidate()
    candidate.token.token_address = ""

    with pytest.raises(BlockchainExecutionRouteBuildError):
        build_solana_buy_route(candidate, 10.0)


def test_build_solana_sell_route_raises_when_token_mint_missing() -> None:
    with pytest.raises(BlockchainExecutionRouteBuildError):
        build_solana_sell_route("", 1.0, 6)


@patch("src.core.trading.execution.solana.trading_execution_solana_service._get_stablecoin_address_for_blockchain")
@patch("src.core.trading.execution.solana.trading_execution_solana_service.build_default_solana_signer")
@patch("src.core.trading.execution.solana.trading_execution_solana_service.generate_jupiter_swap_transaction")
def test_build_solana_sell_route_maps_jupiter_rate_limit_without_error_log(
        generate_jupiter_mock: MagicMock,
        build_signer_mock: MagicMock,
        get_stablecoin_mock: MagicMock,
        caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    get_stablecoin_mock.return_value = "stablecoin-mint"
    build_signer_mock.return_value.address = "wallet-address"
    generate_jupiter_mock.side_effect = JupiterApiUnavailableError(
        "rate limited",
        failure_reason=JupiterApiFailureReason.RATE_LIMITED,
        http_status_code=429,
    )

    with pytest.raises(BlockchainExecutionRouteBuildError) as route_build_error:
        build_solana_sell_route("token-mint", 1.0, 6)

    assert route_build_error.value.is_transient is True
    error_log_records = [log_record for log_record in caplog.records if log_record.levelno >= logging.ERROR]
    assert error_log_records == []
