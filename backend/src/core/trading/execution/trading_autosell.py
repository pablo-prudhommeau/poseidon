from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.structures.structures import Token
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_application_logger
from src.persistence.dao import trades
from src.persistence.dao.trades import compute_open_quantity_for_position
from src.persistence.models import Position, PositionPhase, ExecutionStatus, Trade

logger = get_application_logger(__name__)


def _evaluate_position_thresholds(
        database_session: Session,
        position: Position,
        last_price_value: float,
) -> List[Trade]:
    created_trades: List[Trade] = []
    position_quantity = position.current_quantity or 0.0

    if position_quantity <= 0.0:
        logger.debug(
            "[TRADING][AUTOSELL] Ignored because current quantity is zero — token=%s pair=%s",
            position.token_address, position.pair_address,
        )
        return created_trades

    tp1 = position.take_profit_tier_1_price or 0.0
    tp2 = position.take_profit_tier_2_price or 0.0
    stop = position.stop_loss_price or 0.0

    fee = 0.0
    status = ExecutionStatus.PAPER if settings.PAPER_MODE else ExecutionStatus.LIVE

    token = Token(
        symbol=position.token_symbol,
        chain=position.blockchain_network,
        token_address=position.token_address,
        pair_address=position.pair_address,
    )

    if stop > 0.0 and last_price_value <= stop:
        sell_quantity = compute_open_quantity_for_position(database_session, position)
        if sell_quantity <= 0.0:
            logger.debug("[TRADING][AUTOSELL][SL] Ignored because open quantity is zero — token=%s pair=%s", position.token_address, position.pair_address)
            return created_trades

        trade = trades.sell(database_session, token=token, price=last_price_value, qty=sell_quantity, fee=fee, status=status, phase=PositionPhase.CLOSED)
        created_trades.append(trade)
        logger.info("[TRADING][AUTOSELL][SL] %s token=%s pair=%s sold_qty=%.8f price=%.10f", position.token_symbol, position.token_address, position.pair_address, sell_quantity, last_price_value)
        return created_trades

    if tp2 > 0.0 and last_price_value >= tp2 and position_quantity > 0.0:
        sell_quantity = compute_open_quantity_for_position(database_session, position)
        if sell_quantity <= 0.0:
            logger.debug("[TRADING][AUTOSELL][TP2] Ignored because open quantity is zero — token=%s pair=%s", position.token_address, position.pair_address)
            return created_trades

        trade = trades.sell(database_session, token=token, price=last_price_value, qty=sell_quantity, fee=fee, status=status, phase=PositionPhase.CLOSED)
        created_trades.append(trade)
        logger.info("[TRADING][AUTOSELL][TP2] %s token=%s pair=%s sold_qty=%.8f price=%.10f", position.token_symbol, position.token_address, position.pair_address, sell_quantity, last_price_value)
        return created_trades

    if tp1 > 0.0 and last_price_value >= tp1 and position_quantity > 0.0 and position.position_phase == PositionPhase.OPEN:
        take_profit_fraction = max(0.0, min(1.0, settings.TRADING_TP1_TAKE_PROFIT_FRACTION))
        partial_quantity = max(0.0, min(position_quantity, position_quantity * take_profit_fraction))
        if partial_quantity > 0.0:
            trade = trades.sell(database_session, token=token, price=last_price_value, qty=partial_quantity, fee=fee, status=status, phase=PositionPhase.PARTIAL)
            created_trades.append(trade)

            remaining_estimated = (position.open_quantity or 0.0) - partial_quantity
            logger.info(
                "[TRADING][AUTOSELL][TP1] %s token=%s pair=%s sold_qty=%.8f price=%.10f remaining_est=%.8f",
                position.token_symbol, position.token_address, position.pair_address, partial_quantity, last_price_value, remaining_estimated,
            )

    return created_trades


def check_thresholds_and_autosell(database_session: Session, dexscreener_token_information: DexscreenerTokenInformation) -> List[Trade]:
    created_trades: List[Trade] = []
    last_price_value = dexscreener_token_information.price_usd or 0.0
    if last_price_value <= 0.0:
        return created_trades

    token_address = dexscreener_token_information.base_token.address
    pair_address = dexscreener_token_information.pair_address
    chain_id = dexscreener_token_information.chain_id

    positions = (
        database_session.execute(
            select(Position).where(
                Position.token_address == token_address,
                Position.pair_address == pair_address,
                Position.blockchain_network == chain_id,
                Position.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
            )
        )
        .scalars()
        .all()
    )

    for position in positions:
        created_trades.extend(_evaluate_position_thresholds(database_session, position, last_price_value))

    if created_trades:
        database_session.commit()
    return created_trades


def check_thresholds_and_autosell_for_token_address(
        database_session: Session,
        token: Token,
        last_price: float,
) -> List[Trade]:
    created_trades: List[Trade] = []
    if not token or last_price <= 0.0:
        return created_trades

    position = (
        database_session.execute(
            select(Position).where(
                Position.blockchain_network == token.chain,
                Position.token_symbol == token.symbol,
                Position.token_address == token.token_address,
                Position.pair_address == token.pair_address,
                Position.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
            )
        )
        .scalars()
        .first()
    )
    if not position:
        return created_trades

    created_trades = _evaluate_position_thresholds(database_session, position, last_price)

    if created_trades:
        database_session.commit()
    return created_trades
