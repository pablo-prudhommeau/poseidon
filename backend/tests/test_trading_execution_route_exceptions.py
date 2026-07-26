from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

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
    TradingConfigurationError,
    TradingDexMarketSnapshot,
)
from src.integrations.blockchain.blockchain_exceptions import (
    BlockchainExecutionRouteBuildError,
    BlockchainRpcUnavailableError,
)
from src.integrations.blockchain.blockchain_structures import BlockchainExecutionRoute, BlockchainSolanaRoute
from src.integrations.blockchain.solana.solana_structures import SolanaRpcFailureReason
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


@patch("src.core.trading.execution.evm.trading_execution_evm_handler.build_evm_buy_route")
def test_evm_handler_build_buy_route_delegates_to_service(
        build_evm_buy_route_mock: MagicMock,
) -> None:
    expected_route = BlockchainExecutionRoute()
    build_evm_buy_route_mock.return_value = expected_route
    handler = TradingExecutionEvmHandler(blockchain_network=BlockchainNetwork.BSC)
    candidate = _build_candidate()
    candidate.token.chain = BlockchainNetwork.BSC

    result = handler.build_buy_route(candidate, 10.0)

    assert result is expected_route
    build_evm_buy_route_mock.assert_called_once_with(
        blockchain_network=BlockchainNetwork.BSC,
        candidate=candidate,
        order_notional_usd=10.0,
    )


@patch("src.core.trading.execution.evm.trading_execution_evm_handler.build_evm_sell_route")
def test_evm_handler_build_sell_route_delegates_to_service(
        build_evm_sell_route_mock: MagicMock,
) -> None:
    expected_route = BlockchainExecutionRoute()
    build_evm_sell_route_mock.return_value = expected_route
    handler = TradingExecutionEvmHandler(blockchain_network=BlockchainNetwork.BASE)

    result = handler.build_sell_route("token-mint", 1.0, 6)

    assert result is expected_route
    build_evm_sell_route_mock.assert_called_once_with(
        blockchain_network=BlockchainNetwork.BASE,
        token_address="token-mint",
        token_quantity=1.0,
        token_decimals=6,
    )


@patch("src.core.trading.execution.evm.trading_execution_evm_handler.build_evm_buy_route")
def test_evm_handler_build_buy_route_propagates_route_build_error(
        build_evm_buy_route_mock: MagicMock,
) -> None:
    build_evm_buy_route_mock.side_effect = BlockchainExecutionRouteBuildError(
        "LiFi quote unavailable",
        blockchain_network=BlockchainNetwork.BSC,
        is_transient=True,
    )
    handler = TradingExecutionEvmHandler(blockchain_network=BlockchainNetwork.BSC)
    candidate = _build_candidate()
    candidate.token.chain = BlockchainNetwork.BSC

    with pytest.raises(BlockchainExecutionRouteBuildError) as route_build_error:
        handler.build_buy_route(candidate, 10.0)

    assert route_build_error.value.is_transient is True


@patch("src.core.trading.execution.evm.trading_execution_evm_handler.resolve_evm_sell_token_decimals")
def test_evm_handler_resolve_sell_token_decimals_delegates_to_service(
        resolve_evm_sell_token_decimals_mock: MagicMock,
) -> None:
    resolve_evm_sell_token_decimals_mock.return_value = 18
    handler = TradingExecutionEvmHandler(blockchain_network=BlockchainNetwork.AVALANCHE)

    result = handler.resolve_sell_token_decimals("token-mint")

    assert result == 18
    resolve_evm_sell_token_decimals_mock.assert_called_once_with(
        BlockchainNetwork.AVALANCHE,
        "token-mint",
    )


@patch("src.core.trading.execution.trading_execution_blockchain_route_service.resolve_execution_chain_handler_for_blockchain")
def test_build_route_for_live_execution_raises_when_handler_missing(
        resolve_handler_mock: MagicMock,
) -> None:
    resolve_handler_mock.side_effect = TradingConfigurationError(
        "No execution chain handler registered for configured blockchain 'solana'",
    )
    candidate = _build_candidate()

    with pytest.raises(TradingConfigurationError):
        build_route_for_live_execution(candidate, 10.0)


@patch("src.core.trading.execution.trading_execution_blockchain_route_service.resolve_execution_chain_handler_for_blockchain")
def test_build_route_for_live_sell_raises_when_handler_missing(
        resolve_handler_mock: MagicMock,
) -> None:
    resolve_handler_mock.side_effect = TradingConfigurationError(
        "No execution chain handler registered for configured blockchain 'bsc'",
    )

    with pytest.raises(TradingConfigurationError):
        build_route_for_live_sell("token-mint", BlockchainNetwork.BSC, 1.0, 6)


def test_build_solana_buy_route_raises_when_token_mint_missing() -> None:
    candidate = _build_candidate()
    candidate.token.token_address = ""

    with pytest.raises(BlockchainExecutionRouteBuildError):
        build_solana_buy_route(candidate, 10.0)


def test_build_solana_sell_route_raises_when_token_mint_missing() -> None:
    with pytest.raises(BlockchainExecutionRouteBuildError):
        build_solana_sell_route("", 1.0, 6)


@patch("src.core.trading.trading_configuration_service.resolve_stablecoin_address_for_blockchain")
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


@patch("src.core.trading.execution.solana.trading_execution_solana_service.cache_invalidator")
@patch("src.core.trading.execution.solana.trading_execution_solana_service.poll_deployable_stablecoin_until_swap_settled")
@patch("src.core.trading.execution.solana.trading_execution_solana_service.BlockchainExecutionService")
@patch("src.core.trading.execution.solana.trading_execution_solana_service.resolve_total_deployable_stablecoin_cash_usd")
@patch("src.core.trading.execution.solana.trading_execution_solana_service._fetch_onchain_price_for_token")
def test_run_solana_live_buy_returns_false_on_transient_rpc_without_error_log(
        fetch_price_mock: MagicMock,
        resolve_deployable_mock: MagicMock,
        live_execution_service_mock: MagicMock,
        poll_deployable_mock: MagicMock,
        cache_invalidator_mock: MagicMock,
        caplog: pytest.LogCaptureFixture,
) -> None:
    from src.core.trading.execution.solana.trading_execution_solana_service import run_solana_live_buy_blocking

    caplog.set_level(logging.ERROR)
    fetch_price_mock.return_value = 1.0
    resolve_deployable_mock.return_value = 20.0
    poll_deployable_mock.return_value = MagicMock(swap_settled_on_chain=True, deployable_cash_usd=18.0)
    execution_service = live_execution_service_mock.return_value
    execution_service.solana_execute_route = AsyncMock(
        side_effect=BlockchainRpcUnavailableError(
            "rate limited",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method="sendTransaction",
            failure_reason=SolanaRpcFailureReason.RATE_LIMITED,
        ),
    )
    execution_service.close = AsyncMock()

    token = _build_candidate().token
    execution_route = BlockchainExecutionRoute(
        solana_route=BlockchainSolanaRoute(serialized_transaction_base64="dGVzdA=="),
    )

    result = run_solana_live_buy_blocking(
        token=token,
        quantity=100.0,
        price_usd=1.0,
        stop_loss_usd=0.8,
        take_profit_tp1_usd=1.1,
        take_profit_tp2_usd=1.2,
        execution_route=execution_route,
        origin_evaluation_id=1,
    )

    assert result is False
    cache_invalidator_mock.mark_dirty.assert_not_called()
    error_log_records = [log_record for log_record in caplog.records if log_record.levelno >= logging.ERROR]
    assert error_log_records == []
