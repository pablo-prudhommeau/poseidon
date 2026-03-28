from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.structures.structures import EquityCurve, EquityCurvePoint
from src.logging.logger import get_logger
from src.persistence.models import PortfolioSnapshot

log = get_logger(__name__)


def ensure_initial_cash(db: Session) -> PortfolioSnapshot:
    starting_cash = float(settings.PAPER_STARTING_CASH)
    snapshot = PortfolioSnapshot(total_equity_value=starting_cash, available_cash_balance=starting_cash, active_holdings_value=0.0)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_portfolio_snapshot(db: Session, create_if_missing: bool = False) -> Optional[PortfolioSnapshot]:
    stmt = (
        select(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.created_at.desc(), PortfolioSnapshot.id.desc())
        .limit(1)
    )
    snapshot = db.execute(stmt).scalars().first()
    if snapshot is None and create_if_missing:
        snapshot = ensure_initial_cash(db)
    return snapshot


def equity_curve(db: Session, points: int = 60) -> EquityCurve:
    snapshots = list(
        db.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.created_at.asc())).scalars().all()
    )
    if not snapshots:
        return EquityCurve(curve_points=[])

    if len(snapshots) > points:
        step = max(1, len(snapshots) // points)
        snapshots = snapshots[::step]

    out = EquityCurve(curve_points=[])
    for s in snapshots:
        equity_curve_point = EquityCurvePoint(
            timestamp_milliseconds=int(s.created_at.timestamp() * 1000),
            equity=float(s.total_equity_value or 0.0),
        )
        out.curve_points.append(equity_curve_point)
    return out


def snapshot_portfolio(db: Session, equity: float, cash: float, holdings: float) -> PortfolioSnapshot:
    snapshot = PortfolioSnapshot(
        total_equity_value=float(equity or 0.0),
        available_cash_balance=float(cash or 0.0),
        active_holdings_value=float(holdings or 0.0),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot
