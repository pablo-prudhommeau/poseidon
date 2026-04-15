from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.websocket.telemetry import TelemetryService
from src.configuration.config import settings
from src.core.structures.structures import Token
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
from src.persistence.models import TradingPosition, TradingTrade, ExecutionStatus, PositionPhase, TradeSide

logger = get_application_logger(__name__)


def _execute_sell_operation(
        database_session: Session,
        position: TradingPosition,
        execution_price: float,
        sell_quantity: float,
        reason: str,
) -> TradingTrade:
    trade_dao = TradingTradeDao(database_session)
    execution_status = ExecutionStatus.PAPER if settings.PAPER_MODE else ExecutionStatus.LIVE
    sell_trade = TradingTrade(
        trade_side=TradeSide.SELL,
        token_symbol=position.token_symbol,
        blockchain_network=position.blockchain_network,
        execution_price=execution_price,
        execution_quantity=sell_quantity,
        transaction_fee=0.0,
        realized_profit_and_loss=0.0,
        execution_status=execution_status,
        token_address=position.token_address,
        pair_address=position.pair_address,
        dex_id=position.dex_id,
    )
    trade_dao.save(sell_trade)

    previous_quantity = position.current_quantity
    position.current_quantity -= sell_quantity

    exit_notional = sell_quantity * execution_price
    entry_notional = sell_quantity * position.entry_price
    trade_pnl_usd = exit_notional - entry_notional
    sell_trade.realized_profit_and_loss = trade_pnl_usd

    if position.current_quantity <= 0.0:
        position.position_phase = PositionPhase.CLOSED
    else:
        position.position_phase = PositionPhase.PARTIAL

    database_session.flush()

    pnl_percentage = ((execution_price / position.entry_price) - 1) * 100

    current_time = get_current_local_datetime().replace(tzinfo=None)
    opened_time = position.opened_at.replace(tzinfo=None) if position.opened_at else current_time
    holding_duration = (current_time - opened_time).total_seconds() / 60.0

    TelemetryService.link_trade_outcome(
        token_address=position.token_address,
        trade_id=sell_trade.id,
        closed_at=get_current_local_datetime(),
        realized_profit_and_loss_percentage=pnl_percentage,
        realized_profit_and_loss_usd=trade_pnl_usd,
        holding_duration_minutes=holding_duration,
        was_profitable=(trade_pnl_usd > 0),
        exit_reason=reason,
        database_session=database_session,
    )

    return sell_trade


def _evaluate_position_thresholds(
        database_session: Session,
        position: TradingPosition,
        last_price_value: float,
) -> List[TradingTrade]:
    created_trades: List[TradingTrade] = []
    position_quantity = position.current_quantity or 0.0

    if position_quantity <= 0.0:
        return created_trades

    tp1 = position.take_profit_tier_1_price or 0.0
    tp2 = position.take_profit_tier_2_price or 0.0
    stop = position.stop_loss_price or 0.0

    if stop > 0.0 and last_price_value <= stop:
        logger.info("[TRADING][AUTOSELL][SL] Triggered for %s @ %.12f (stop=%.12f)", position.token_symbol, last_price_value, stop)
        trade = _execute_sell_operation(database_session, position, last_price_value, position_quantity, "STOP_LOSS")
        created_trades.append(trade)
        return created_trades

    if tp2 > 0.0 and last_price_value >= tp2:
        logger.info("[TRADING][AUTOSELL][TP2] Triggered for %s @ %.12f (tp2=%.12f)", position.token_symbol, last_price_value, tp2)
        trade = _execute_sell_operation(database_session, position, last_price_value, position_quantity, "TAKE_PROFIT_2")
        created_trades.append(trade)
        return created_trades

    if tp1 > 0.0 and last_price_value >= tp1 and position.position_phase == PositionPhase.OPEN:
        take_profit_fraction = max(0.0, min(1.0, settings.TRADING_TP1_TAKE_PROFIT_FRACTION))
        partial_quantity = position_quantity * take_profit_fraction
        if partial_quantity > 0.0:
            logger.info("[TRADING][AUTOSELL][TP1] Triggered for %s @ %.12f (tp1=%.12f)", position.token_symbol, last_price_value, tp1)
            trade = _execute_sell_operation(database_session, position, last_price_value, partial_quantity, "TAKE_PROFIT_1")
            created_trades.append(trade)

    return created_trades


def check_thresholds_and_autosell_for_token_address(
        database_session: Session,
        token: Token,
        last_price: float,
) -> List[TradingTrade]:
    created_trades: List[TradingTrade] = []
    if not token or last_price <= 0.0:
        return created_trades

    database_query = select(TradingPosition).where(
        TradingPosition.blockchain_network == token.chain,
        TradingPosition.token_address == token.token_address,
        TradingPosition.pair_address == token.pair_address,
        TradingPosition.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
    )
    position = database_session.execute(database_query).scalars().first()

    if not position:
        return created_trades

    created_trades = _evaluate_position_thresholds(database_session, position, last_price)

    if created_trades:
        database_session.commit()

    return created_trades
