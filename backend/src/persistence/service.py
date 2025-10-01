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

    Order of checks: STOP (<=) -> TP2 (>=) -> TP1 (>=).
    - STOP: full exit; thresholds reset (compat preserved).
    - TP2: full exit; thresholds reset (compat preserved).
    - TP1: partial exit by TRENDING_TP1_EXIT_FRACTION; **tp1 NOT reset**; phase -> PARTIAL.
      TP1 fires only once: if phase is already PARTIAL, we skip TP1.
    At most one action is performed per invocation.
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

    # STOP → full exit
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
            phase=Phase.CLOSED,
        )
        # Keep previous compatibility: reset thresholds on full exit
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
            phase=Phase.CLOSED,
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

    if (tp1 > 0.0 and last_price_f >= tp1 and position_quantity > 0.0 and position.phase == Phase.OPEN):
        tp1_sell_fraction = max(0.0, min(1.0, float(settings.TRENDING_TP1_TAKE_PROFIT_FRACTION)))
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
                phase=Phase.PARTIAL,
            )
            created.append(trade)

            # Do NOT reset tp1 here; user expectation: keep tp1 price.
            # Mark lifecycle as PARTIAL so subsequent checks still consider STOP/TP2.
            position.phase = Phase.PARTIAL

            remaining_est = float((position.qty or 0.0) - partial_quantity)
            log.info(
                "[AUTOSELL][TP1] %s (%s) sold_qty=%.8f price=%.10f remaining_est=%.8f",
                position.symbol,
                (position.address or "")[-6:],
                partial_quantity,
                last_price_f,
                remaining_est,
            )

    return created


def check_thresholds_and_autosell(db: Session, symbol: str, last_price: float) -> List[Trade]:
    """
    Autosell positions for a symbol based on tp1/tp2/stop thresholds and last price.

    - Evaluates positions in phase OPEN **and PARTIAL** (so STOP/TP2 remain active after TP1).
    - Invokes a single action per position per call (SL > TP2 > TP1).
    """
    created: List[Trade] = []
    last_price_f = float(last_price or 0.0)
    if last_price_f <= 0.0:
        return created

    positions = (
        db.execute(
            select(Position).where(
                Position.symbol == symbol,
                Position.phase.in_([Phase.OPEN, Phase.PARTIAL]),  # ← include PARTIAL
            )
        )
        .scalars()
        .all()
    )
    for position in positions:
        created.extend(_evaluate_position_thresholds_and_execute(db, position, last_price_f))
    if created:
        db.commit()
    return created


def check_thresholds_and_autosell_for_address(db: Session, address: str, last_price: float) -> List[Trade]:
    """
    Autosell for a specific address based on thresholds and last price.

    - Evaluates SL > TP2 > TP1 for the addressed position in phase OPEN **or PARTIAL**.
    """
    created: List[Trade] = []
    if not address or float(last_price or 0.0) <= 0.0:
        return created

    position = (
        db.execute(
            select(Position).where(
                Position.address == address,
                Position.phase.in_([Phase.OPEN, Phase.PARTIAL]),  # ← include PARTIAL
            )
        )
        .scalars()
        .first()
    )
    if not position:
        return created

    created = _evaluate_position_thresholds_and_execute(db, position, float(last_price))

    if created:
        db.commit()
    return created
