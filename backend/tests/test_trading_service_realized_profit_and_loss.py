from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from src.api.http.api_schemas import TradingTradePayload
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_service import compute_realized_profit_and_loss_totals
from src.core.utils.date_utils import format_datetime_to_local_iso, get_current_local_datetime


def _build_trade_payload(
        *,
        trade_id: int,
        trade_side: str,
        token_symbol: str,
        token_address: str,
        pair_address: str,
        execution_price: float,
        execution_quantity: float,
        created_at: datetime,
        realized_profit_and_loss: Optional[float] = None,
) -> TradingTradePayload:
    created_at_iso: Optional[str] = format_datetime_to_local_iso(created_at)
    if created_at_iso is None:
        raise ValueError("created_at must produce a local iso timestamp")
    return TradingTradePayload(
        id=trade_id,
        evaluation_id=trade_id,
        trade_side=trade_side,
        token_symbol=token_symbol,
        blockchain_network=BlockchainNetwork.SOLANA,
        execution_price=execution_price,
        execution_quantity=execution_quantity,
        transaction_fee=0.0,
        execution_status="LIVE",
        token_address=token_address,
        pair_address=pair_address,
        created_at=created_at_iso,
        dex_id="raydium",
        realized_profit_and_loss=realized_profit_and_loss,
        transaction_hash=None,
        linked_position_id=trade_id,
    )


def test_compute_realized_profit_and_loss_totals_includes_synthetic_ledger_write_off() -> None:
    reference_time: datetime = get_current_local_datetime()
    buy_time: datetime = reference_time - timedelta(hours=4)
    synthetic_sell_time: datetime = reference_time - timedelta(hours=1)
    trades: list[TradingTradePayload] = [
        _build_trade_payload(
            trade_id=1,
            trade_side="BUY",
            token_symbol="$CFK",
            token_address="cfk-token-address",
            pair_address="cfk-pair-address",
            execution_price=0.00001,
            execution_quantity=100_000.0,
            created_at=buy_time,
        ),
        _build_trade_payload(
            trade_id=2,
            trade_side="SELL",
            token_symbol="$CFK",
            token_address="cfk-token-address",
            pair_address="cfk-pair-address",
            execution_price=0.0,
            execution_quantity=0.0,
            created_at=synthetic_sell_time,
            realized_profit_and_loss=-1.0,
        ),
    ]

    (
        realized_profit_and_loss_total,
        realized_profit_and_loss_24_hours,
        realized_profit_and_loss_7_days,
        realized_profit_and_loss_30_days,
    ) = compute_realized_profit_and_loss_totals(trades)

    assert realized_profit_and_loss_total == -1.0
    assert realized_profit_and_loss_24_hours == -1.0
    assert realized_profit_and_loss_7_days == -1.0
    assert realized_profit_and_loss_30_days == -1.0


def test_compute_realized_profit_and_loss_totals_keeps_tokens_isolated() -> None:
    reference_time: datetime = get_current_local_datetime()
    trades: list[TradingTradePayload] = [
        _build_trade_payload(
            trade_id=1,
            trade_side="BUY",
            token_symbol="$CFK",
            token_address="cfk-token-address",
            pair_address="cfk-pair-address",
            execution_price=1.0,
            execution_quantity=10.0,
            created_at=reference_time - timedelta(hours=8),
        ),
        _build_trade_payload(
            trade_id=2,
            trade_side="SELL",
            token_symbol="$CFK",
            token_address="cfk-token-address",
            pair_address="cfk-pair-address",
            execution_price=0.0,
            execution_quantity=0.0,
            created_at=reference_time - timedelta(hours=6),
            realized_profit_and_loss=-10.0,
        ),
        _build_trade_payload(
            trade_id=3,
            trade_side="BUY",
            token_symbol="$XRPS",
            token_address="xrps-token-address",
            pair_address="xrps-pair-address",
            execution_price=1.0,
            execution_quantity=5.0,
            created_at=reference_time - timedelta(hours=7),
        ),
        _build_trade_payload(
            trade_id=4,
            trade_side="SELL",
            token_symbol="$XRPS",
            token_address="xrps-token-address",
            pair_address="xrps-pair-address",
            execution_price=2.0,
            execution_quantity=5.0,
            created_at=reference_time - timedelta(hours=5),
            realized_profit_and_loss=5.0,
        ),
    ]

    (
        realized_profit_and_loss_total,
        _realized_profit_and_loss_24_hours,
        _realized_profit_and_loss_7_days,
        _realized_profit_and_loss_30_days,
    ) = compute_realized_profit_and_loss_totals(trades)

    assert realized_profit_and_loss_total == -5.0


def test_compute_realized_profit_and_loss_totals_clears_fifo_lots_after_synthetic_write_off() -> None:
    reference_time: datetime = get_current_local_datetime()
    trades: list[TradingTradePayload] = [
        _build_trade_payload(
            trade_id=1,
            trade_side="BUY",
            token_symbol="$CFK",
            token_address="cfk-token-address",
            pair_address="cfk-pair-address",
            execution_price=1.0,
            execution_quantity=10.0,
            created_at=reference_time - timedelta(hours=10),
        ),
        _build_trade_payload(
            trade_id=2,
            trade_side="SELL",
            token_symbol="$CFK",
            token_address="cfk-token-address",
            pair_address="cfk-pair-address",
            execution_price=0.0,
            execution_quantity=0.0,
            created_at=reference_time - timedelta(hours=8),
            realized_profit_and_loss=-10.0,
        ),
        _build_trade_payload(
            trade_id=3,
            trade_side="BUY",
            token_symbol="$CFK",
            token_address="cfk-token-address",
            pair_address="cfk-pair-address",
            execution_price=1.0,
            execution_quantity=4.0,
            created_at=reference_time - timedelta(hours=6),
        ),
        _build_trade_payload(
            trade_id=4,
            trade_side="SELL",
            token_symbol="$CFK",
            token_address="cfk-token-address",
            pair_address="cfk-pair-address",
            execution_price=2.0,
            execution_quantity=4.0,
            created_at=reference_time - timedelta(hours=4),
            realized_profit_and_loss=4.0,
        ),
    ]

    (
        realized_profit_and_loss_total,
        _realized_profit_and_loss_24_hours,
        _realized_profit_and_loss_7_days,
        _realized_profit_and_loss_30_days,
    ) = compute_realized_profit_and_loss_totals(trades)

    assert realized_profit_and_loss_total == -6.0
