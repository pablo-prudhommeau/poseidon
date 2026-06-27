from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.trading.execution.trading_execution_position_service import (
    close_position_as_honeypot,
    close_position_with_synthetic_total_loss,
)
from src.core.trading.trading_structures import PositionExitTriggerReason
from src.persistence.models import PositionPhase, TradingPosition


def _build_position(phase: PositionPhase) -> TradingPosition:
    return TradingPosition(
        id=7,
        evaluation_id=10,
        token_symbol="HONEY",
        blockchain_network="solana",
        token_address="token-address",
        pair_address="pair-address",
        dex_id="pumpswap",
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


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.TradingEvaluationDao")
@patch("src.core.trading.execution.trading_execution_position_service.TradingTradeDao")
def test_close_position_as_honeypot_records_total_loss(
        trading_trade_dao_mock: MagicMock,
        trading_evaluation_dao_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.TRADING_PAPER_MODE = True
    position = _build_position(PositionPhase.CLOSING)
    database_session = MagicMock()
    trading_trade_dao_mock.return_value.save.side_effect = lambda trade: setattr(trade, "id", 901) or trade

    close_position_as_honeypot(database_session=database_session, position=position)

    assert position.position_phase == PositionPhase.CLOSED
    assert position.current_quantity == 0.0
    assert position.exit_reason == PositionExitTriggerReason.HONEYPOT.value
    outcome_call = trading_evaluation_dao_mock.return_value.link_trade_outcome.call_args.kwargs
    assert outcome_call["realized_profit_and_loss_percentage"] == -100.0
    assert outcome_call["realized_profit_and_loss_usd"] == -100.0
    assert outcome_call["was_profitable"] is False


@patch("src.core.trading.execution.trading_execution_position_service.settings")
@patch("src.core.trading.execution.trading_execution_position_service.TradingEvaluationDao")
@patch("src.core.trading.execution.trading_execution_position_service.TradingTradeDao")
def test_close_position_with_synthetic_total_loss_uses_requested_exit_reason(
        trading_trade_dao_mock: MagicMock,
        trading_evaluation_dao_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.TRADING_PAPER_MODE = True
    position = _build_position(PositionPhase.STALED)
    database_session = MagicMock()
    trading_trade_dao_mock.return_value.save.side_effect = lambda trade: setattr(trade, "id", 902) or trade

    close_position_with_synthetic_total_loss(
        database_session=database_session,
        position=position,
        exit_reason=PositionExitTriggerReason.KILLED,
    )

    assert position.exit_reason == PositionExitTriggerReason.KILLED.value
