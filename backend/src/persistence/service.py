from __future__ import annotations

from typing import List

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.logging.logger import get_logger
from src.persistence.dao import trades
from src.persistence.dao.trades import _compute_open_quantity_from_trades
from src.persistence.db import _session
from src.persistence.models import Position, PortfolioSnapshot, Trade, Status, Phase, Analytics

log = get_logger(__name__)


def reset_paper(database_session: Session) -> None:
    """
    Reset paper mode state by deleting all trades, positions and snapshots.

    Note:
        The provided 'database_session' parameter is ignored by design;
        a fresh transactional session is created to guarantee atomic cleanup.
    """
    with _session() as session:
        session.execute(delete(Trade))
        session.execute(delete(Position))
        session.execute(delete(PortfolioSnapshot))
        session.execute(delete(Analytics))
        session.commit()
        log.info("Paper state has been reset (trades, positions, snapshots, analytics removed).")


def _evaluate_position_thresholds_and_execute(
        database_session: Session,
        position: Position,
        last_price: float,
) -> List[Trade]:
    """
    Evaluate TP1 / TP2 / SL for a single ACTIVE position and execute at most one action.

    Order of checks (exclusive):
        1) STOP (<= last_price) → full exit
        2) TP2  (>= last_price) → full exit
        3) TP1  (>= last_price) → partial exit (fraction TRENDING_TP1_TAKE_PROFIT_FRACTION)
           TP1 only fires once per lifecycle: if phase is already PARTIAL, it is skipped.
    """
    created_trades: List[Trade] = []

    last_price_value = float(last_price or 0.0)
    if last_price_value <= 0.0:
        log.debug(
            "Skip threshold evaluation due to non-positive last price — address=%s price=%s",
            position.address,
            last_price_value,
        )
        return created_trades

    position_quantity = float(position.qty or 0.0)
    if position_quantity <= 0.0:
        log.debug(
            "Skip threshold evaluation due to non-positive position quantity — address=%s qty=%s",
            position.address,
            position_quantity,
        )
        return created_trades

    tp1 = float(position.tp1 or 0.0)
    tp2 = float(position.tp2 or 0.0)
    stop = float(position.stop or 0.0)

    if settings.PAPER_MODE:
        fee = 0.0
        status = Status.PAPER
    else:
        raise NotImplementedError("Live mode is not implemented yet.")

    # 1) STOP ⇒ full exit
    if stop > 0.0 and last_price_value <= stop:
        sell_quantity = _compute_open_quantity_from_trades(database_session, position.address)
        if sell_quantity <= 0.0:
            log.debug("[AUTOSELL][SL] Ignored because open quantity is zero — address=%s", position.address)
            return created_trades

        trade = trades.sell(
            database_session,
            symbol=position.symbol,
            chain=position.chain,
            address=position.address,
            price=last_price_value,
            qty=sell_quantity,
            fee=fee,
            status=status,
            phase=Phase.CLOSED,
        )
        created_trades.append(trade)
        log.info(
            "[AUTOSELL][SL] %s (%s) sold_qty=%.8f price=%.10f",
            position.symbol,
            (position.address or "")[-6:],
            sell_quantity,
            last_price_value,
        )
        return created_trades

    # 2) TP2 ⇒ full exit
    if tp2 > 0.0 and last_price_value >= tp2 and position_quantity > 0.0:
        sell_quantity = _compute_open_quantity_from_trades(database_session, position.address)
        if sell_quantity <= 0.0:
            log.debug("[AUTOSELL][TP2] Ignored because open quantity is zero — address=%s", position.address)
            return created_trades

        trade = trades.sell(
            database_session,
            symbol=position.symbol,
            chain=position.chain,
            address=position.address,
            price=last_price_value,
            qty=sell_quantity,
            fee=fee,
            status=status,
            phase=Phase.CLOSED,
        )
        created_trades.append(trade)
        log.info(
            "[AUTOSELL][TP2] %s (%s) sold_qty=%.8f price=%.10f",
            position.symbol,
            (position.address or "")[-6:],
            sell_quantity,
            last_price_value,
        )
        return created_trades

    # 3) TP1 ⇒ partial exit (only once)
    if tp1 > 0.0 and last_price_value >= tp1 and position_quantity > 0.0 and position.phase == Phase.OPEN:
        take_profit_fraction = max(0.0, min(1.0, float(settings.TRENDING_TP1_TAKE_PROFIT_FRACTION)))
        partial_quantity = max(0.0, min(position_quantity, position_quantity * take_profit_fraction))
        if partial_quantity > 0.0:
            trade = trades.sell(
                database_session,
                symbol=position.symbol,
                chain=position.chain,
                address=position.address,
                price=last_price_value,
                qty=partial_quantity,
                fee=fee,
                status=status,
                phase=Phase.PARTIAL,
            )
            created_trades.append(trade)

            # Keep tp1 unchanged by design; mark lifecycle as PARTIAL.
            position.phase = Phase.PARTIAL

            remaining_estimated = float((position.qty or 0.0) - partial_quantity)
            log.info(
                "[AUTOSELL][TP1] %s (%s) sold_qty=%.8f price=%.10f remaining_est=%.8f",
                position.symbol,
                (position.address or "")[-6:],
                partial_quantity,
                last_price_value,
                remaining_estimated,
            )

    return created_trades


def check_thresholds_and_autosell(database_session: Session, symbol: str, last_price: float) -> List[Trade]:
    """
    Autosell positions for a symbol based on tp1/tp2/stop thresholds and last price.

    Evaluates ACTIVE positions only (OPEN and PARTIAL).
    Executes at most one action per position per invocation (SL > TP2 > TP1).
    """
    created_trades: List[Trade] = []
    last_price_value = float(last_price or 0.0)
    if last_price_value <= 0.0:
        return created_trades

    positions = (
        database_session.execute(
            select(Position).where(
                Position.symbol == symbol,
                Position.phase.in_([Phase.OPEN, Phase.PARTIAL]),
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


def check_thresholds_and_autosell_for_address(
        database_session: Session,
        address: str,
        last_price: float,
) -> List[Trade]:
    """
    Autosell for a specific address based on thresholds and last price.

    Evaluates ACTIVE position only (OPEN or PARTIAL) for the address.
    """
    created_trades: List[Trade] = []
    last_price_value = float(last_price or 0.0)
    if not address or last_price_value <= 0.0:
        return created_trades

    position = (
        database_session.execute(
            select(Position).where(
                Position.address == address,
                Position.phase.in_([Phase.OPEN, Phase.PARTIAL]),
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
