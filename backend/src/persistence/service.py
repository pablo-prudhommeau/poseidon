from __future__ import annotations

from typing import List

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.logging.logger import get_logger
from src.persistence.dao import trades
from src.persistence.db import _session
from src.persistence.models import Position, PortfolioSnapshot, Trade, Status, Phase

log = get_logger(__name__)


def reset_paper(db: Session) -> None:
    """Delete all trades, positions, and snapshots (paper reset)."""
    with _session() as db:
        db.execute(delete(Trade))
        db.execute(delete(Position))
        db.execute(delete(PortfolioSnapshot))
        db.commit()


def _evaluate_position_thresholds_and_execute(db: Session, position: Position, last_price: float) -> List[Trade]:
    """
    Evaluate TP1 / TP2 / SL for a single position and execute corresponding trades.

    Behavior (identical to the previous duplicated logic)
    ----------------------------------------------------
    - Order of checks: STOP (<=) -> TP2 (>=) -> TP1 (>=).
    - STOP: full exit on current quantity, then tp1/tp2/stop reset to 0.0.
    - TP2: full exit on current quantity, then tp1/tp2/stop reset to 0.0.
    - TP1: partial exit with fraction TRENDING_TAKE_PROFIT_TP1_FRACTION and tp1 set to 0.0.
    - At most one action is performed per invocation for a given position.
    - `record_trade` performs its own commit; this helper does not commit.

    Returns
    -------
    List[Trade]
        The list of trades created (0 or 1 item in practice).
    """
    created: List[Trade] = []

    last_price_f = float(last_price or 0.0)
    if last_price_f <= 0.0:
        return created

    position_quantity = float(position.qty or 0.0)
    if position_quantity <= 0.0:
        return created

    tp1 = float(position.tp1 or 0.0)
    tp2 = float(position.tp2 or 0.0)
    stop = float(position.stop or 0.0)

    if settings.PAPER_MODE:
        fee = 0.0
        status = Status.PAPER
    else:
        raise NotImplementedError("Live mode is not implemented yet.")

    # Stop-loss → full exit
    if stop > 0.0 and last_price_f <= stop:
        trade = trades.sell(
            db,
            symbol=position.symbol,
            chain=position.chain,
            address=position.address,
            price=last_price_f,
            qty=position_quantity,
            fee=fee,
            status=status,
            phase=Phase.CLOSED
        )
        position.tp1 = 0.0
        position.tp2 = 0.0
        position.stop = 0.0
        created.append(trade)
        log.info(
            "[AUTOSELL][SL] %s (%s) sold_qty=%.8f price=%.10f",
            position.symbol,
            (position.address or "")[-6:],
            position_quantity,
            last_price_f,
        )
        return created

    # TP2 → full exit
    if tp2 > 0.0 and last_price_f >= tp2 and position_quantity > 0.0:
        trade = trades.sell(
            db,
            symbol=position.symbol,
            chain=position.chain,
            address=position.address,
            price=last_price_f,
            qty=position_quantity,
            fee=fee,
            status=status,
            phase=Phase.CLOSED
        )
        position.tp1 = 0.0
        position.tp2 = 0.0
        position.stop = 0.0
        created.append(trade)
        log.info(
            "[AUTOSELL][TP2] %s (%s) sold_qty=%.8f price=%.10f",
            position.symbol,
            (position.address or "")[-6:],
            position_quantity,
            last_price_f,
        )
        return created

    # TP1 → partial exit (fraction defined by TRENDING_TAKE_PROFIT_TP1_FRACTION)
    if tp1 > 0.0 and last_price_f >= tp1 and position_quantity > 0.0:
        tp1_sell_fraction = max(0.0, min(1.0, float(settings.TRENDING_TAKE_PROFIT_TP1_FRACTION)))
        partial_quantity = max(0.0, min(position_quantity, position_quantity * tp1_sell_fraction))
        if partial_quantity > 0.0:
            trade = trades.sell(
                db,
                symbol=position.symbol,
                chain=position.chain,
                address=position.address,
                price=last_price_f,
                qty=partial_quantity,
                fee=fee,
                status=status,
                phase=Phase.PARTIAL
            )
            created.append(trade)
            position.tp1 = 0.0
            log.info(
                "[AUTOSELL][TP1] %s (%s) sold_qty=%.8f price=%.10f remaining_est=%.8f",
                position.symbol,
                (position.address or "")[-6:],
                partial_quantity,
                last_price_f,
                float((position.qty or 0.0) - partial_quantity),
            )

    return created


def check_thresholds_and_autosell(db: Session, symbol: str, last_price: float) -> List[Trade]:
    """
    Autosell positions for a symbol based on tp1/tp2/stop thresholds and last price.

    Notes
    -----
    Behavior preserved from original implementation:
    - Iterates all open positions for the given symbol.
    - Invokes a single action per position per call (SL > TP2 > TP1).
    - Performs an extra `db.commit()` at the end if any trade occurred (redundant
      with `record_trade` internal commit but intentionally kept to avoid regression).
    """
    created: List[Trade] = []
    last_price_f = float(last_price or 0.0)
    if last_price_f <= 0.0:
        return created
    positions = db.execute(
        select(Position).where(Position.phase == Phase.OPEN, Position.symbol == symbol)
    ).scalars().all()
    for position in positions:
        created.extend(_evaluate_position_thresholds_and_execute(db, position, last_price_f))
    if created:
        db.commit()
    return created


def check_thresholds_and_autosell_for_address(db: Session, address: str, last_price: float) -> List[Trade]:
    """
    Autosell for a specific address based on thresholds and last price.

    Notes
    -----
    Behavior preserved from original implementation:
    - Evaluates SL > TP2 > TP1 for the addressed open position.
    - Keeps the explicit `db.commit()` if any trade occurred (even though
      `record_trade` already commits) to avoid any regression in side effects.
    """
    created: List[Trade] = []
    if not address or float(last_price or 0.0) <= 0.0:
        return created

    position = db.execute(
        select(Position).where(Position.address == address, Position.phase == Phase.OPEN)
    ).scalars().first()
    if not position:
        return created

    created = _evaluate_position_thresholds_and_execute(db, position, float(last_price))

    if created:
        db.commit()
    return created
