from __future__ import annotations

from datetime import datetime

from src.api.serializers import serialize_trading_position
from src.persistence.models import PositionPhase, TradingPosition


def _build_partially_secured_position() -> TradingPosition:
    return TradingPosition(
        id=1,
        evaluation_id=10,
        token_symbol="TEST",
        blockchain_network="solana",
        token_address="token-address",
        pair_address="pair-address",
        dex_id="raydium",
        open_quantity=100.0,
        current_quantity=40.0,
        entry_price=1.0,
        breakeven_arm_price=1.2,
        take_profit_price=1.5,
        stop_loss_price=0.8,
        initial_stop_loss_price=0.8,
        position_phase=PositionPhase.PARTIAL,
        opened_at=datetime(2026, 6, 20, 19, 8, 39),
        updated_at=datetime(2026, 6, 20, 19, 17, 1),
    )


def test_serialize_trading_position_exposes_evaluation_order_notional_value_usd() -> None:
    position = _build_partially_secured_position()

    payload = serialize_trading_position(
        position,
        last_price=1.1,
        evaluation_order_notional_value_usd=500.0,
        realized_profit_and_loss_usd=25.53,
    )

    assert payload.evaluation_order_notional_value_usd == 500.0
    assert payload.realized_profit_and_loss_usd == 25.53
    assert payload.open_quantity == 100.0
    assert payload.current_quantity == 40.0
    assert payload.last_price == 1.1
    assert payload.initial_stop_loss_price == 0.8
    assert payload.breakeven_stop_armed_at is None
