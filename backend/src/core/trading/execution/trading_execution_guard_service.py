from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.structures.structures import Token
from src.core.trading.execution.trading_execution_position_service import (
    _invalidate_trading_realms_after_closing_sell,
    execute_position_exit_sell,
)
from src.core.trading.trading_structures import PositionExitTriggerReason
from src.logging.logger import get_application_logger
from src.persistence.models import TradingPosition, TradingTrade, PositionPhase

logger = get_application_logger(__name__)


def check_thresholds_and_exit_for_token_address(
        database_session: Session,
        token: Token,
        last_price: float,
) -> List[TradingTrade]:
    created_trades: List[TradingTrade] = []
    if not token or last_price <= 0.0:
        return created_trades

    database_query = select(TradingPosition).where(
        TradingPosition.blockchain_network == token.chain.value,
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


def _evaluate_position_thresholds(
        database_session: Session,
        position: TradingPosition,
        last_price_value: float,
) -> List[TradingTrade]:
    created_trades: List[TradingTrade] = []
    position_quantity = position.current_quantity or 0.0

    if position_quantity <= 0.0:
        return created_trades

    take_profit_1_price: float = position.take_profit_tier_1_price or 0.0
    take_profit_2_price: float = position.take_profit_tier_2_price or 0.0
    stop_loss_price: float = position.stop_loss_price or 0.0

    if stop_loss_price > 0.0 and last_price_value <= stop_loss_price:
        logger.info(
            "[TRADING][EXECUTION][GUARD][SL] Triggered for %s @ %.12f (stop=%.12f)",
            position.token_symbol,
            last_price_value,
            stop_loss_price,
        )
        closing_sell_result = execute_position_exit_sell(
            database_session,
            position,
            last_price_value,
            position_quantity,
            PositionExitTriggerReason.STOP_LOSS,
        )
        if closing_sell_result.trading_trade is not None:
            created_trades.append(closing_sell_result.trading_trade)
            _invalidate_trading_realms_after_closing_sell(
                stablecoin_swap_settled_on_chain=closing_sell_result.stablecoin_swap_settled_on_chain,
            )
        return created_trades

    if take_profit_2_price > 0.0 and last_price_value >= take_profit_2_price:
        logger.info(
            "[TRADING][EXECUTION][GUARD][TP2] Triggered for %s @ %.12f (tp2=%.12f)",
            position.token_symbol,
            last_price_value,
            take_profit_2_price,
        )
        closing_sell_result = execute_position_exit_sell(
            database_session,
            position,
            last_price_value,
            position_quantity,
            PositionExitTriggerReason.TAKE_PROFIT_2,
        )
        if closing_sell_result.trading_trade is not None:
            created_trades.append(closing_sell_result.trading_trade)
            _invalidate_trading_realms_after_closing_sell(
                stablecoin_swap_settled_on_chain=closing_sell_result.stablecoin_swap_settled_on_chain,
            )
        return created_trades

    if take_profit_1_price > 0.0 and last_price_value >= take_profit_1_price and position.position_phase == PositionPhase.OPEN:
        take_profit_fraction = max(0.0, min(1.0, settings.TRADING_TP1_TAKE_PROFIT_FRACTION))
        partial_quantity = position_quantity * take_profit_fraction
        if partial_quantity > 0.0:
            logger.info(
                "[TRADING][EXECUTION][GUARD][TP1] Triggered for %s @ %.12f (tp1=%.12f)",
                position.token_symbol,
                last_price_value,
                take_profit_1_price,
            )
            closing_sell_result = execute_position_exit_sell(
                database_session,
                position,
                last_price_value,
                partial_quantity,
                PositionExitTriggerReason.TAKE_PROFIT_1,
            )
            if closing_sell_result.trading_trade is not None:
                created_trades.append(closing_sell_result.trading_trade)
                _invalidate_trading_realms_after_closing_sell(
                    stablecoin_swap_settled_on_chain=closing_sell_result.stablecoin_swap_settled_on_chain,
                )

    return created_trades
