from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc, select, and_
from sqlalchemy.orm import Session

from src.logging.logger import get_logger
from src.persistence.models import Analytics

log = get_logger(__name__)


def insert_analytics(db: Session, row: Analytics) -> Analytics:
    db.add(row)
    db.flush()
    return row


def get_recent_analytics(db: Session, limit: int = 2000) -> List[Analytics]:
    return (
        db.execute(
            select(Analytics)
            .order_by(desc(Analytics.evaluated_at), desc(Analytics.id))
            .limit(limit)
        )
        .scalars()
        .all()
    )


def attach_outcome_for_trade(
        db: Session,
        *,
        address: str,
        closed_at: datetime,
        trade_id: int,
        pnl_pct: float,
        pnl_usd: float,
        holding_minutes: float,
        was_profit: bool,
        exit_reason: str = "",
) -> Optional[Analytics]:
    row: Optional[Analytics] = (
        db.execute(
            select(Analytics)
            .where(and_(Analytics.address == address,
                        Analytics.evaluated_at <= closed_at,
                        Analytics.has_outcome == False))
            .order_by(desc(Analytics.evaluated_at), desc(Analytics.id))
            .limit(1)
        )
        .scalars()
        .first()
    )
    if not row:
        return None

    row.has_outcome = True
    row.outcome_trade_id = int(trade_id)
    row.outcome_closed_at = closed_at
    row.outcome_holding_minutes = float(holding_minutes)
    row.outcome_pnl_pct = float(pnl_pct)
    row.outcome_pnl_usd = float(pnl_usd)
    row.outcome_was_profit = bool(was_profit)
    row.outcome_exit_reason = exit_reason

    db.flush()
    return row
