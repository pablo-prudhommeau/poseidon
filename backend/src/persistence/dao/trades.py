from __future__ import annotations

from collections import deque
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.api.websocket.telemetry import TelemetryService
from src.core.structures.structures import Token
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_logger
from src.persistence.models import PositionPhase, Position, TradeSide, ExecutionStatus, Trade

logger = get_logger(__name__)

MINIMUM_QUANTITY_THRESHOLD = 1e-12


class InventoryLot(BaseModel):
    quantity: float
    price: float
    fee_per_unit: float


class ProfitAndCostBasis(BaseModel):
    realized_profit_and_loss: float
    cost_basis: float


def get_active_position_by_address(database_session: Session, token_address: str) -> Optional[Position]:
    database_query = (
        select(Position)
        .where(
            Position.token_address == token_address,
            Position.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
        )
        .order_by(desc(Position.opened_at), desc(Position.id))
        .limit(1)
    )
    return database_session.execute(database_query).scalars().first()


def get_last_closed_position_for_cooldown(database_session: Session, token_address: str) -> Optional[Position]:
    database_query = (
        select(Position)
        .where(
            Position.token_address == token_address,
            Position.position_phase == PositionPhase.CLOSED,
            Position.closed_at.isnot(None),
        )
        .order_by(desc(Position.closed_at), desc(Position.id))
        .limit(1)
    )
    return database_session.execute(database_query).scalars().first()


def calculate_fifo_realized_profit_and_cost_basis_for_sell(
        database_session: Session,
        token_address: str,
        sell_quantity: float,
        sell_price: float,
        sell_fee: float,
        pair_address: Optional[str] = None,
) -> ProfitAndCostBasis:
    if sell_quantity <= 0.0 or sell_price <= 0.0:
        return ProfitAndCostBasis(
            realized_profit_and_loss=(0.0 - sell_fee),
            cost_basis=0.0
        )

    database_query = (
        select(Trade)
        .where(Trade.token_address == token_address)
        .order_by(Trade.created_at.asc(), Trade.id.asc())
    )
    if isinstance(pair_address, str) and pair_address:
        database_query = database_query.where(Trade.pair_address == pair_address)

    historical_trades: list[Trade] = list(database_session.execute(database_query).scalars().all())
    inventory_lots: deque[InventoryLot] = deque()

    for trade_record in historical_trades:
        if trade_record.execution_quantity is None or trade_record.execution_price is None:
            continue

        trade_quantity = trade_record.execution_quantity
        trade_price = trade_record.execution_price
        trade_fee = trade_record.transaction_fee or 0.0

        if trade_quantity <= 0.0 or trade_price <= 0.0:
            continue

        if trade_record.trade_side == TradeSide.BUY:
            fee_per_unit = trade_fee / trade_quantity if trade_quantity > 0.0 else 0.0
            inventory_lots.append(InventoryLot(quantity=trade_quantity, price=trade_price, fee_per_unit=fee_per_unit))

        elif trade_record.trade_side == TradeSide.SELL:
            remaining_to_consume = trade_quantity
            while remaining_to_consume > MINIMUM_QUANTITY_THRESHOLD and len(inventory_lots) > 0:
                oldest_lot = inventory_lots[0]
                matched_quantity = min(remaining_to_consume, oldest_lot.quantity)

                oldest_lot.quantity -= matched_quantity
                remaining_to_consume -= matched_quantity

                if oldest_lot.quantity <= MINIMUM_QUANTITY_THRESHOLD:
                    inventory_lots.popleft()

    remaining_quantity_to_sell = sell_quantity
    accumulated_realized_profit_and_loss = 0.0
    accumulated_cost_basis = 0.0
    sell_fee_per_unit = sell_fee / sell_quantity if sell_quantity > 0.0 else 0.0

    while remaining_quantity_to_sell > MINIMUM_QUANTITY_THRESHOLD and len(inventory_lots) > 0:
        oldest_lot = inventory_lots[0]
        matched_quantity = min(remaining_quantity_to_sell, oldest_lot.quantity)

        proceeds_from_sale = (sell_price - sell_fee_per_unit) * matched_quantity
        cost_of_purchase = (oldest_lot.price + oldest_lot.fee_per_unit) * matched_quantity

        accumulated_realized_profit_and_loss += (proceeds_from_sale - cost_of_purchase)
        accumulated_cost_basis += cost_of_purchase

        oldest_lot.quantity -= matched_quantity
        remaining_quantity_to_sell -= matched_quantity

        if oldest_lot.quantity <= MINIMUM_QUANTITY_THRESHOLD:
            inventory_lots.popleft()

    if remaining_quantity_to_sell > MINIMUM_QUANTITY_THRESHOLD:
        resolved_pair_address = pair_address or ""
        logger.warning(
            "[DATABASE][DAO][TRADES][FIFO] Sell quantity exceeds available inventory lots for token %s on pair %s with residual quantity %f",
            token_address,
            resolved_pair_address[-6:],
            remaining_quantity_to_sell,
        )

    return ProfitAndCostBasis(
        realized_profit_and_loss=round(accumulated_realized_profit_and_loss, 8),
        cost_basis=round(accumulated_cost_basis, 8)
    )


def compute_open_quantity_from_trades(database_session: Session, token_address: str) -> float:
    database_query = select(Trade).where(Trade.token_address == token_address)
    historical_trades: list[Trade] = list(database_session.execute(database_query).scalars().all())

    open_quantity = 0.0
    for trade_record in historical_trades:
        if trade_record.execution_quantity is None:
            continue
        if trade_record.trade_side == TradeSide.BUY:
            open_quantity += trade_record.execution_quantity
        elif trade_record.trade_side == TradeSide.SELL:
            open_quantity -= trade_record.execution_quantity

    return max(0.0, open_quantity)


def compute_open_quantity_for_position(database_session: Session, position: Position) -> float:
    database_query = select(Trade).where(Trade.token_address == position.token_address)
    if isinstance(position.pair_address, str) and position.pair_address:
        database_query = database_query.where(Trade.pair_address == position.pair_address)

    historical_trades: list[Trade] = list(database_session.execute(database_query).scalars().all())
    open_quantity = 0.0

    for trade_record in historical_trades:
        if trade_record.execution_quantity is None:
            continue
        if trade_record.trade_side == TradeSide.BUY:
            open_quantity += trade_record.execution_quantity
        elif trade_record.trade_side == TradeSide.SELL:
            open_quantity -= trade_record.execution_quantity

    open_quantity = max(0.0, open_quantity)

    logger.debug(
        "[DATABASE][DAO][TRADES][QUANTITY] Computed open quantity for token %s on pair %s is %f",
        position.token_address,
        position.pair_address,
        open_quantity,
    )
    return open_quantity


def buy(
        db: Session,
        token: Token,
        qty: float,
        price: float,
        stop: float,
        tp1: float,
        tp2: float,
        fee: float,
        status: ExecutionStatus,
) -> Trade:
    if price <= 0.0:
        logger.error("[DATABASE][DAO][TRADES][BUY] Buy order rejected due to invalid price %f", price)
        raise ValueError("Buy rejected: price must be strictly positive")

    trade_record = Trade(
        trade_side=TradeSide.BUY,
        token_symbol=token.symbol,
        blockchain_network=token.chain,
        token_address=token.token_address,
        pair_address=token.pair_address,
        execution_price=price,
        execution_quantity=qty,
        transaction_fee=fee,
        execution_status=status
    )
    db.add(trade_record)

    position_record = Position(
        token_symbol=token.symbol,
        blockchain_network=token.chain,
        token_address=token.token_address,
        pair_address=token.pair_address,
        open_quantity=qty,
        current_quantity=qty,
        entry_price=price,
        take_profit_tier_1_price=tp1,
        take_profit_tier_2_price=tp2,
        stop_loss_price=stop,
        position_phase=PositionPhase.OPEN,
    )
    db.add(position_record)

    logger.info(
        "[DATABASE][DAO][TRADES][BUY] Buy snapshot created for token %s %s/%s with quantity %f, entry %f, take profit tier 1 %f, take profit tier 2 %f, stop loss %f",
        token.symbol, token.token_address, token.pair_address, qty, price, tp1, tp2, stop,
    )
    db.commit()
    db.refresh(trade_record)
    return trade_record


def sell(
        db: Session,
        token: Token,
        qty: float,
        price: float,
        fee: float,
        status: ExecutionStatus,
        phase: PositionPhase,
) -> Trade:
    if price <= 0.0:
        logger.error("[DATABASE][DAO][TRADES][SELL] Sell order rejected due to invalid price %f", price)
        raise ValueError("Sell rejected: price must be strictly positive")

    active_position = get_active_position_by_address(database_session=db, token_address=token.token_address)

    if active_position is not None:
        open_quantity_before_sell = compute_open_quantity_for_position(database_session=db, position=active_position)
    else:
        open_quantity_before_sell = compute_open_quantity_from_trades(database_session=db, token_address=token.token_address)

    if qty > open_quantity_before_sell + MINIMUM_QUANTITY_THRESHOLD:
        logger.error(
            "[DATABASE][DAO][TRADES][SELL] Sell order exceeds open quantity for token %s on pair %s. Sell quantity: %f, Open quantity: %f",
            token.token_address, token.pair_address, qty, open_quantity_before_sell,
        )
        raise ValueError("Sell rejected: quantity exceeds currently open quantity")

    profit_and_basis_result = calculate_fifo_realized_profit_and_cost_basis_for_sell(
        database_session=db,
        token_address=token.token_address,
        sell_quantity=qty,
        sell_price=price,
        sell_fee=fee,
        pair_address=token.pair_address,
    )

    trade_record = Trade(
        trade_side=TradeSide.SELL,
        token_symbol=token.symbol,
        blockchain_network=token.chain,
        execution_price=price,
        execution_quantity=qty,
        transaction_fee=fee,
        execution_status=status,
        token_address=token.token_address,
        pair_address=token.pair_address,
        realized_profit_and_loss=profit_and_basis_result.realized_profit_and_loss,
    )
    db.add(trade_record)

    is_position_closed_now = False

    if active_position is not None:
        open_quantity_after_sell = max(0.0, open_quantity_before_sell - qty)
        if open_quantity_after_sell <= MINIMUM_QUANTITY_THRESHOLD:
            active_position.position_phase = phase
            active_position.closed_at = get_current_local_datetime()
            active_position.current_quantity = 0.0
            is_position_closed_now = True
        else:
            active_position.position_phase = PositionPhase.PARTIAL
            active_position.current_quantity = open_quantity_after_sell

        logger.info(
            "[DATABASE][DAO][POSITION][UPDATE] Position phase updated for token %s on pair %s to %s with remaining quantity %f",
            token.token_address, token.pair_address, active_position.position_phase, open_quantity_after_sell,
        )
        logger.debug(
            "[DATABASE][DAO][TRADES][SELL][LIFECYCLE] Trade processed for token %s %s/%s with quantity %f, price %f, realized profit %f",
            token.symbol, token.token_address, token.pair_address, qty, price, profit_and_basis_result.realized_profit_and_loss,
        )

    db.commit()
    db.refresh(trade_record)

    try:
        if active_position is not None and is_position_closed_now:
            position_start_time = active_position.opened_at

            lifecycle_database_query = (
                select(Trade)
                .where(Trade.token_address == token.token_address, Trade.created_at >= position_start_time)
                .order_by(Trade.created_at.asc(), Trade.id.asc())
            )
            lifecycle_database_query = lifecycle_database_query.where(Trade.pair_address == token.pair_address)
            lifecycle_trades: list[Trade] = list(db.execute(lifecycle_database_query).scalars().all())

            total_invested_usd = sum(
                (trade.execution_quantity or 0.0) * (trade.execution_price or 0.0) + (trade.transaction_fee or 0.0)
                for trade in lifecycle_trades
                if trade.trade_side == TradeSide.BUY
            )
            total_realized_profit_usd = sum(
                (trade.realized_profit_and_loss or 0.0)
                for trade in lifecycle_trades
                if trade.trade_side == TradeSide.SELL
            )

            final_profit_usd = round(total_realized_profit_usd, 8)
            final_profit_percentage = round((final_profit_usd / total_invested_usd) * 100.0, 6) if total_invested_usd > 0 else 0.0
            holding_duration_minutes = 0.0

            if active_position.closed_at is not None and active_position.opened_at is not None:
                holding_duration_minutes = max(
                    0.0,
                    (active_position.closed_at - active_position.opened_at).total_seconds() / 60.0,
                )

            exit_reason = "MANUAL"
            if price <= (active_position.stop_loss_price or 0.0) + MINIMUM_QUANTITY_THRESHOLD:
                exit_reason = "SL"
            elif price >= (active_position.take_profit_tier_2_price or 0.0) - MINIMUM_QUANTITY_THRESHOLD:
                exit_reason = "TP2"
            elif price >= (active_position.take_profit_tier_1_price or 0.0) - MINIMUM_QUANTITY_THRESHOLD:
                exit_reason = "TP1"

            TelemetryService.link_trade_outcome(
                token_address=token.token_address,
                trade_id=trade_record.id,
                closed_at=active_position.closed_at,
                pnl_pct=final_profit_percentage,
                pnl_usd=final_profit_usd,
                holding_minutes=holding_duration_minutes,
                was_profit=final_profit_usd > 0.0,
                exit_reason=exit_reason,
            )

        elif active_position is not None and active_position.position_phase == PositionPhase.PARTIAL:
            partial_profit_usd = trade_record.realized_profit_and_loss or 0.0
            partial_basis_usd = profit_and_basis_result.cost_basis
            partial_profit_percentage = (partial_profit_usd / partial_basis_usd * 100.0) if partial_basis_usd > 0.0 else 0.0

            holding_duration_minutes_partial = 0.0
            if trade_record.created_at is not None and active_position.opened_at is not None:
                holding_duration_minutes_partial = max(
                    0.0,
                    (trade_record.created_at - active_position.opened_at).total_seconds() / 60.0,
                )

            TelemetryService.link_trade_outcome(
                token_address=token.token_address,
                trade_id=trade_record.id,
                closed_at=trade_record.created_at,
                pnl_pct=round(partial_profit_percentage, 6),
                pnl_usd=round(partial_profit_usd, 8),
                holding_minutes=round(holding_duration_minutes_partial, 4),
                was_profit=partial_profit_usd > 0.0,
                exit_reason="TP1",
            )
    except Exception as exception:
        logger.error(
            "[DATABASE][DAO][TRADES][TELEMETRY] Failed to link trade outcome for token %s and trade %s with error: %s",
            token.symbol,
            trade_record.id,
            exception,
        )

    return trade_record


def get_recent_trades(database_session: Session, limit_count: int = 100) -> list[Trade]:
    database_query = select(Trade).order_by(Trade.created_at.desc(), Trade.id.desc()).limit(limit_count)
    return list(database_session.execute(database_query).scalars().all())


def get_all_trades(database_session: Session) -> list[Trade]:
    database_query = select(Trade).order_by(Trade.created_at.asc(), Trade.id.asc())
    return list(database_session.execute(database_query).scalars().all())
