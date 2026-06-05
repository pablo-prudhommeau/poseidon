from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.trading.execution.trading_execution_position_service import (
    execute_closing_sell,
    kill_staled_position,
    mark_position_staled,
    reopen_staled_position,
)
from src.core.trading.trading_structures import PositionExitTriggerReason
from src.persistence.models import PositionPhase, TradingPosition


def _build_position(phase: PositionPhase) -> TradingPosition:
    return TradingPosition(
        id=7,
        evaluation_id=10,
        token_symbol="REY",
        blockchain_network="solana",
        token_address="token-address",
        pair_address="pair-address",
        dex_id="raydium",
        open_quantity=100.0,
        current_quantity=100.0,
        entry_price=1.0,
        take_profit_tier_1_price=1.2,
        take_profit_tier_2_price=1.5,
        stop_loss_price=0.8,
        position_phase=phase,
        exit_reason=None,
        opened_at=MagicMock(),
        updated_at=MagicMock(),
    )


def test_mark_position_staled_only_changes_phase_and_exit_reason() -> None:
    position = _build_position(PositionPhase.CLOSING)
    position.current_quantity = 55.0
    database_session = MagicMock()

    mark_position_staled(database_session, position, PositionExitTriggerReason.CIRCUIT_BREAKER)

    assert position.position_phase == PositionPhase.STALED
    assert position.exit_reason == PositionExitTriggerReason.CIRCUIT_BREAKER.value
    assert position.current_quantity == 55.0
    database_session.commit.assert_called_once()


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.TradingEvaluationDao")
@patch("src.core.trading.execution.trading_execution_position_service.TradingTradeDao")
def test_kill_staled_position_records_negative_hundred_percent_outcome(
        trading_trade_dao_mock: MagicMock,
        trading_evaluation_dao_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.PAPER_MODE = True
    position = _build_position(PositionPhase.STALED)
    database_session = MagicMock()
    database_session.get.return_value = position
    saved_trade = MagicMock()
    saved_trade.id = 501
    trading_trade_dao_mock.return_value.save.side_effect = lambda trade: setattr(trade, "id", 501) or trade

    kill_staled_position(database_session, 7)

    assert position.position_phase == PositionPhase.CLOSED
    assert position.current_quantity == 0.0
    assert position.exit_reason == PositionExitTriggerReason.KILLED.value
    trading_evaluation_dao_mock.return_value.link_trade_outcome.assert_called_once()
    outcome_call = trading_evaluation_dao_mock.return_value.link_trade_outcome.call_args.kwargs
    assert outcome_call["realized_profit_and_loss_percentage"] == -100.0
    assert outcome_call["realized_profit_and_loss_usd"] == -100.0
    assert outcome_call["was_profitable"] is False


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.resolve_execution_chain_handler_for_blockchain")
def test_execute_closing_sell_marks_staled_when_wallet_balance_is_zero(
        resolve_execution_chain_handler_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.PAPER_MODE = False
    position = _build_position(PositionPhase.CLOSING)
    position.token_symbol = "SPEC"
    position.current_quantity = 689.303435
    chain_handler = MagicMock()
    chain_handler.resolve_sell_token_decimals.return_value = 6
    chain_handler.cap_sell_quantity_to_wallet_balance.return_value = 0.0
    resolve_execution_chain_handler_mock.return_value = chain_handler
    database_session = MagicMock()

    closing_sell_result = execute_closing_sell(
        database_session=database_session,
        position=position,
        execution_price=0.000088141787,
        sell_quantity=689.303435,
        reason=PositionExitTriggerReason.STOP_LOSS,
        previous_phase=PositionPhase.PARTIAL,
    )

    assert closing_sell_result.trading_trade is None
    assert closing_sell_result.stablecoin_swap_settled_on_chain is False
    assert position.position_phase == PositionPhase.STALED
    assert position.exit_reason == PositionExitTriggerReason.WALLET_BALANCE_EMPTY.value
    assert position.current_quantity == 689.303435


def test_reopen_staled_position_reopens_partial_when_quantity_reduced() -> None:
    position = _build_position(PositionPhase.STALED)
    position.open_quantity = 100.0
    position.current_quantity = 40.0
    database_session = MagicMock()
    database_session.get.return_value = position

    reopen_staled_position(database_session, 7)

    assert position.position_phase == PositionPhase.PARTIAL
    assert position.exit_reason is None
    assert position.current_quantity == 40.0
