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
from src.core.trading.execution.trading_execution_structures import TradingPositionThresholdEvaluationResult
from src.core.trading.trading_structures import PositionExitTriggerReason
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.models import TradingPosition, TradingTrade, PositionPhase

logger = get_application_logger(__name__)


def clamp_breakeven_stop_pnl_fraction(breakeven_stop_pnl_fraction: float) -> float:
    maximum_pnl_fraction = max(0.0, min(1.0, settings.TRADING_BREAKEVEN_ARM_FRACTION))
    exclusive_upper_bound = maximum_pnl_fraction
    exclusive_lower_bound = -1.0
    if exclusive_upper_bound <= 0.0:
        return max(exclusive_lower_bound + 1e-12, min(0.0, breakeven_stop_pnl_fraction))
    return max(exclusive_lower_bound + 1e-12, min(exclusive_upper_bound - 1e-12, breakeven_stop_pnl_fraction))


def compute_breakeven_stop_price(entry_price: float) -> float:
    breakeven_stop_pnl_fraction = clamp_breakeven_stop_pnl_fraction(settings.TRADING_EXIT_BREAKEVEN_STOP_PNL_FRACTION)
    return entry_price * (1.0 + breakeven_stop_pnl_fraction)


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

    evaluation_result = _evaluate_position_thresholds(database_session, position, last_price)
    created_trades = evaluation_result.created_trades

    if created_trades or evaluation_result.position_mutated:
        database_session.commit()

    return created_trades


def _evaluate_position_thresholds(
        database_session: Session,
        position: TradingPosition,
        last_price_value: float,
) -> TradingPositionThresholdEvaluationResult:
    created_trades: List[TradingTrade] = []
    position_quantity = position.current_quantity or 0.0

    if position_quantity <= 0.0:
        return TradingPositionThresholdEvaluationResult(created_trades=created_trades, position_mutated=False)

    breakeven_arm_price: float = position.breakeven_arm_price or 0.0
    take_profit_price: float = position.take_profit_price or 0.0
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
        return TradingPositionThresholdEvaluationResult(created_trades=created_trades, position_mutated=False)

    if take_profit_price > 0.0 and last_price_value >= take_profit_price:
        logger.info(
            "[TRADING][EXECUTION][GUARD][TP] Triggered for %s @ %.12f (take_profit=%.12f)",
            position.token_symbol,
            last_price_value,
            take_profit_price,
        )
        closing_sell_result = execute_position_exit_sell(
            database_session,
            position,
            last_price_value,
            position_quantity,
            PositionExitTriggerReason.TAKE_PROFIT,
        )
        if closing_sell_result.trading_trade is not None:
            created_trades.append(closing_sell_result.trading_trade)
            _invalidate_trading_realms_after_closing_sell(
                stablecoin_swap_settled_on_chain=closing_sell_result.stablecoin_swap_settled_on_chain,
            )
        return TradingPositionThresholdEvaluationResult(created_trades=created_trades, position_mutated=False)

    if (
            breakeven_arm_price > 0.0
            and last_price_value >= breakeven_arm_price
            and position.position_phase == PositionPhase.OPEN
    ):
        breakeven_stop_armed: bool = _arm_breakeven_stop(position, last_price_value, breakeven_arm_price)
        return TradingPositionThresholdEvaluationResult(created_trades=created_trades, position_mutated=breakeven_stop_armed)

    return TradingPositionThresholdEvaluationResult(created_trades=created_trades, position_mutated=False)


def _arm_breakeven_stop(position: TradingPosition, last_price_value: float, breakeven_arm_price: float) -> bool:
    if position.breakeven_stop_armed_at is not None:
        return False

    breakeven_stop_price: float = compute_breakeven_stop_price(position.entry_price)
    previous_stop_loss_price: float = position.stop_loss_price

    if breakeven_stop_price <= previous_stop_loss_price:
        logger.debug(
            "[TRADING][EXECUTION][GUARD][BE_ARM] %s already protected above breakeven (stop=%.12f breakeven=%.12f)",
            position.token_symbol,
            previous_stop_loss_price,
            breakeven_stop_price,
        )
        return False

    position.stop_loss_price = breakeven_stop_price
    position.breakeven_stop_armed_at = get_current_local_datetime()

    logger.info(
        "[TRADING][EXECUTION][GUARD][BE_ARM] Armed for %s @ %.12f (arm=%.12f) — stop raised %.12f -> %.12f (entry=%.12f, be_pnl=%+.2f%%)",
        position.token_symbol,
        last_price_value,
        breakeven_arm_price,
        previous_stop_loss_price,
        breakeven_stop_price,
        position.entry_price,
        clamp_breakeven_stop_pnl_fraction(settings.TRADING_EXIT_BREAKEVEN_STOP_PNL_FRACTION) * 100.0,
    )
    return True
