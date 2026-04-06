from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.websocket.telemetry import TelemetryService
from src.configuration.config import settings
from src.core.structures.structures import Token
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger
from src.persistence.dao.trading.trading_trade_dao import TradingTradeDao
from src.persistence.dao.trading.trading_position_dao import TradingPositionDao
from src.persistence.models import TradingPosition, TradingTrade, ExecutionStatus, PositionPhase

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
        token_address=position.token_address,
        token_symbol=position.token_symbol,
        blockchain_network=position.blockchain_network,
        quantity=sell_quantity,
        entry_price_usd=execution_price,
        execution_status=execution_status,
        is_buy=False,
        exit_reason=reason,
    )
    trade_dao.save(sell_trade)

    previous_quantity = position.current_quantity
    position.current_quantity -= sell_quantity

    exit_notional = sell_quantity * execution_price
    entry_notional = sell_quantity * position.average_entry_price_usd
    trade_pnl_usd = exit_notional - entry_notional
    
    position.realized_pnl_usd += trade_pnl_usd
    position.latest_price_usd = execution_price
    
    if position.current_quantity <= 0.0:
        position.is_open = False
        position.position_phase = PositionPhase.CLOSED
    else:
        position.position_phase = PositionPhase.PARTIAL
        
    database_session.flush()
    
    pnl_percentage = ((execution_price / position.average_entry_price_usd) - 1) * 100
    
    holding_duration = 0.0
    
    TelemetryService.link_trade_outcome(
        token_address=position.token_address,
        trade_id=sell_trade.id,
        closed_at=get_current_local_datetime(),
        profit_and_loss_percentage=pnl_percentage,
        profit_and_loss_usd=trade_pnl_usd,
        holding_duration_minutes=holding_duration,
        was_profitable=(trade_pnl_usd > 0),
        exit_reason=reason
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


def check_thresholds_and_autosell(database_session: Session, dexscreener_token_information: DexscreenerTokenInformation) -> List[TradingTrade]:
    created_trades: List[TradingTrade] = []
    last_price_value = dexscreener_token_information.price_usd or 0.0
    if last_price_value <= 0.0:
        return created_trades

    token_address = dexscreener_token_information.base_token.address
    pair_address = dexscreener_token_information.pair_address
    chain_id = str(dexscreener_token_information.chain_id)

    position_dao = TradingPositionDao(database_session)
    
    database_query = select(TradingPosition).where(
        TradingPosition.token_address == token_address,
        TradingPosition.pair_address == pair_address,
        TradingPosition.blockchain_network == chain_id,
        TradingPosition.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
    )
    positions = list(database_session.execute(database_query).scalars().all())

    for position in positions:
        position.latest_price_usd = last_price_value
        created_trades.extend(_evaluate_position_thresholds(database_session, position, last_price_value))

    if created_trades:
        database_session.commit()
        
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
        TradingPosition.token_address == token.address,
        TradingPosition.pair_address == token.pair_address,
        TradingPosition.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
    )
    position = database_session.execute(database_query).scalars().first()
    
    if not position:
        return created_trades

    position.latest_price_usd = last_price
    created_trades = _evaluate_position_thresholds(database_session, position, last_price)

    if created_trades:
        database_session.commit()
        
    return created_trades
