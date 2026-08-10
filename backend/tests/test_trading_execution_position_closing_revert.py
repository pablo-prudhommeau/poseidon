from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.trading_execution_position_service import (
    execute_closing_sell,
    execute_position_exit_sell,
)
from src.core.trading.trading_structures import PositionExitTriggerReason
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.solana.solana_structures import SolanaRpcFailureReason
from src.persistence.models import PositionPhase, TradingPosition


def _build_closing_position() -> TradingPosition:
    return TradingPosition(
        id=1,
        evaluation_id=10,
        token_symbol="TEST",
        blockchain_network="solana",
        token_address="token-address",
        pair_address="pair-address",
        dex_id="raydium",
        open_quantity=100.0,
        current_quantity=100.0,
        entry_price=1.0,
        breakeven_arm_price=1.2,
        take_profit_price=1.5,
        stop_loss_price=0.8,
        initial_stop_loss_price=0.8,
        position_phase=PositionPhase.CLOSING,
        exit_reason=PositionExitTriggerReason.TAKE_PROFIT.value,
        opened_at=MagicMock(),
        updated_at=MagicMock(),
    )


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.resolve_execution_chain_handler_for_blockchain")
def test_execute_closing_sell_reverts_on_rpc_unavailable(
        resolve_execution_chain_handler_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.TRADING_PAPER_MODE = False
    position = _build_closing_position()
    chain_handler = MagicMock()
    chain_handler.resolve_sell_token_decimals.side_effect = BlockchainRpcUnavailableError(
        "[BLOCKCHAIN][RPC][REGISTRY] No reachable RPC endpoint found for chain solana",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="getAccountInfo",
        failure_reason=SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
    )
    resolve_execution_chain_handler_mock.return_value = chain_handler
    database_session = MagicMock()

    trade = execute_closing_sell(
        database_session=database_session,
        position=position,
        execution_price=1.25,
        sell_quantity=50.0,
        reason=PositionExitTriggerReason.TAKE_PROFIT,
        previous_phase=PositionPhase.OPEN,
    )

    assert trade.trading_trade is None
    assert position.position_phase == PositionPhase.OPEN
    assert position.exit_reason is None


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.resolve_execution_chain_handler_for_blockchain")
def test_execute_closing_sell_reverts_on_unexpected_exception(
        resolve_execution_chain_handler_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.TRADING_PAPER_MODE = False
    position = _build_closing_position()
    chain_handler = MagicMock()
    chain_handler.resolve_sell_token_decimals.side_effect = RuntimeError("unexpected failure")
    resolve_execution_chain_handler_mock.return_value = chain_handler
    database_session = MagicMock()

    trade = execute_closing_sell(
        database_session=database_session,
        position=position,
        execution_price=1.25,
        sell_quantity=50.0,
        reason=PositionExitTriggerReason.TAKE_PROFIT,
        previous_phase=PositionPhase.OPEN,
    )

    assert trade.trading_trade is None
    assert position.position_phase == PositionPhase.OPEN
    assert position.exit_reason is None


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.TradingEvaluationDao")
@patch("src.core.trading.execution.trading_execution_position_service.TradingTradeDao")
def test_execute_closing_sell_paper_mode_completes_take_profit(
        trading_trade_dao_mock: MagicMock,
        trading_evaluation_dao_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.TRADING_PAPER_MODE = True
    position = _build_closing_position()
    database_session = MagicMock()
    trading_trade_dao_mock.return_value.save.side_effect = lambda trade: setattr(trade, "id", 99) or trade

    trade = execute_closing_sell(
        database_session=database_session,
        position=position,
        execution_price=1.25,
        sell_quantity=100.0,
        reason=PositionExitTriggerReason.TAKE_PROFIT,
        previous_phase=PositionPhase.OPEN,
    )

    assert trade.trading_trade is not None
    assert position.position_phase == PositionPhase.CLOSED
    assert position.exit_reason == PositionExitTriggerReason.TAKE_PROFIT.value
    assert position.current_quantity == 0.0


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.mark_position_closing")
@patch("src.core.trading.execution.trading_execution_position_service.resolve_execution_chain_handler_for_blockchain")
def test_execute_position_exit_sell_reverts_when_mark_closing_then_rpc_fails(
        resolve_execution_chain_handler_mock: MagicMock,
        mark_position_closing_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.TRADING_PAPER_MODE = False
    position = _build_closing_position()
    position.position_phase = PositionPhase.OPEN
    position.exit_reason = None

    def _mark_closing(database_session: MagicMock, closing_position: TradingPosition, reason: PositionExitTriggerReason) -> PositionPhase:
        closing_position.position_phase = PositionPhase.CLOSING
        closing_position.exit_reason = reason.value
        return PositionPhase.OPEN

    mark_position_closing_mock.side_effect = _mark_closing
    chain_handler = MagicMock()
    chain_handler.resolve_sell_token_decimals.side_effect = BlockchainRpcUnavailableError(
        "no rpc",
        blockchain_network=BlockchainNetwork.SOLANA,
        rpc_method="getAccountInfo",
        failure_reason=SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
    )
    resolve_execution_chain_handler_mock.return_value = chain_handler
    database_session = MagicMock()

    trade = execute_position_exit_sell(
        database_session=database_session,
        position=position,
        execution_price=1.25,
        sell_quantity=50.0,
        reason=PositionExitTriggerReason.TAKE_PROFIT,
    )

    assert trade.trading_trade is None
    assert position.position_phase == PositionPhase.OPEN
    assert position.exit_reason is None
