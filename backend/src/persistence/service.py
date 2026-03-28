from __future__ import annotations

from typing import List

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.structures.structures import Token
from src.integrations.dexscreener.dexscreener_structures import DexscreenerTokenInformation
from src.logging.logger import get_logger
from src.persistence.dao import trades
from src.persistence.dao.trades import compute_open_quantity_for_position
from src.persistence.db import _session
from src.persistence.models import Position, PortfolioSnapshot, Trade, ExecutionStatus, PositionPhase, Analytics

log = get_logger(__name__)


def reset_paper(database_session: Session) -> None:
    with _session() as session:
        session.execute(delete(Trade))
        session.execute(delete(Position))
        session.execute(delete(PortfolioSnapshot))
        session.execute(delete(Analytics))
        session.commit()
        log.info("[SERVICE][RESET] Paper state has been reset (trades, positions, snapshots, analytics removed).")


def _evaluate_position_thresholds_and_execute(
        database_session: Session,
        position: Position,
        last_price: float,
) -> List[Trade]:
    created_trades: List[Trade] = []

    if position.position_phase == PositionPhase.STALED:
        log.info(
            "[AUTOSELL][SKIP][STALED] token=%s pair=%s",
            position.token_address,
            position.pair_address,
        )
        return created_trades

    last_price_value = float(last_price or 0.0)
    if last_price_value <= 0.0:
        log.debug(
            "[AUTOSELL][SKIP] Non-positive last price — token=%s pair=%s price=%s",
            position.token_address,
            position.pair_address,
            last_price_value,
        )
        return created_trades

    position_quantity = float(position.open_quantity or 0.0)
    if position_quantity <= 0.0:
        log.debug(
            "[AUTOSELL][SKIP] Non-positive position quantity — token=%s pair=%s qty=%s",
            position.token_address,
            position.pair_address,
            position_quantity,
        )
        return created_trades

    tp1 = float(position.take_profit_tier_1_price or 0.0)
    tp2 = float(position.take_profit_tier_2_price or 0.0)
    stop = float(position.stop_loss_price or 0.0)

    if settings.PAPER_MODE:
        fee = 0.0
        status = ExecutionStatus.PAPER
    else:
        fee = 0.0
        status = ExecutionStatus.LIVE

    token = Token(
        symbol=position.token_symbol,
        chain=position.blockchain_network,
        token_address=position.token_address,
        pair_address=position.pair_address,
    )

    if stop > 0.0 and last_price_value <= stop:
        sell_quantity = compute_open_quantity_for_position(database_session, position)
        if sell_quantity <= 0.0:
            log.debug(
                "[AUTOSELL][SL] Ignored because open quantity is zero — token=%s pair=%s",
                position.token_address,
                position.pair_address,
            )
            return created_trades

        trade = trades.sell(
            database_session,
            token=token,
            price=last_price_value,
            qty=sell_quantity,
            fee=fee,
            status=status,
            phase=PositionPhase.CLOSED,
        )
        created_trades.append(trade)
        log.info(
            "[AUTOSELL][SL] %s token=%s pair=%s sold_qty=%.8f price=%.10f",
            position.token_symbol,
            position.token_address,
            position.pair_address,
            sell_quantity,
            last_price_value,
        )
        return created_trades

    if tp2 > 0.0 and last_price_value >= tp2 and position_quantity > 0.0:
        sell_quantity = compute_open_quantity_for_position(database_session, position)
        if sell_quantity <= 0.0:
            log.debug(
                "[AUTOSELL][TP2] Ignored because open quantity is zero — token=%s pair=%s",
                position.token_address,
                position.pair_address,
            )
            return created_trades

        trade = trades.sell(
            database_session,
            token=token,
            price=last_price_value,
            qty=sell_quantity,
            fee=fee,
            status=status,
            phase=PositionPhase.CLOSED,
        )
        created_trades.append(trade)
        log.info(
            "[AUTOSELL][TP2] %s token=%s pair=%s sold_qty=%.8f price=%.10f",
            position.token_symbol,
            position.token_address,
            position.pair_address,
            sell_quantity,
            last_price_value,
        )
        return created_trades

    if tp1 > 0.0 and last_price_value >= tp1 and position_quantity > 0.0 and position.position_phase == PositionPhase.OPEN:
        take_profit_fraction = max(0.0, min(1.0, float(settings.TRENDING_TP1_TAKE_PROFIT_FRACTION)))
        partial_quantity = max(0.0, min(position_quantity, position_quantity * take_profit_fraction))
        if partial_quantity > 0.0:
            trade = trades.sell(
                database_session,
                token=token,
                price=last_price_value,
                qty=partial_quantity,
                fee=fee,
                status=status,
                phase=PositionPhase.PARTIAL,
            )
            created_trades.append(trade)

            remaining_estimated = float((position.open_quantity or 0.0) - partial_quantity)
            log.info(
                "[AUTOSELL][TP1] %s token=%s pair=%s sold_qty=%.8f price=%.10f remaining_est=%.8f",
                position.token_symbol,
                position.token_address,
                position.pair_address,
                partial_quantity,
                last_price_value,
                remaining_estimated,
            )

    return created_trades


def check_thresholds_and_autosell(database_session: Session, dexscreener_token_information: DexscreenerTokenInformation) -> List[Trade]:
    created_trades: List[Trade] = []
    last_price_value = float(dexscreener_token_information.price_usd or 0.0)
    if last_price_value <= 0.0:
        return created_trades

    positions = (
        database_session.execute(
            select(Position).where(
                Position.token_symbol == dexscreener_token_information.base_token.symbol,
                Position.position_phase.in_([PositionPhase.OPEN, PositionPhase.PARTIAL]),
            )
        )
        .scalars()
        .all()
    )

    for position in positions:
        created_trades.extend(_evaluate_position_thresholds_and_execute(database_session, position, last_price_value))

    if created_trades:
        database_session.commit()
    return created_trades


def check_thresholds_and_autosell_for_token_address(
        database_session: Session,
        token: Token,
        last_price: float,
) -> List[Trade]:
    created_trades: List[Trade] = []
    last_price_value = float(last_price or 0.0)
    if not token or last_price_value <= 0.0:
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

    created_trades = _evaluate_position_thresholds_and_execute(database_session, position, last_price_value)

    if created_trades:
        database_session.commit()
    return created_trades
