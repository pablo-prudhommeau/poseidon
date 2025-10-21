from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.configuration.config import settings
from src.core.structures.structures import EquityCurve, EquityCurvePoint
from src.logging.logger import get_logger
from src.persistence.models import PortfolioSnapshot

log = get_logger(__name__)


def ensure_initial_cash(db: Session) -> PortfolioSnapshot:
    """Create an initial portfolio snapshot using PAPER_STARTING_CASH."""
    starting_cash = float(settings.PAPER_STARTING_CASH)
    snapshot = PortfolioSnapshot(equity=starting_cash, cash=starting_cash, holdings=0.0)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_portfolio_snapshot(db: Session, create_if_missing: bool = False) -> Optional[PortfolioSnapshot]:
    """Return the latest portfolio snapshot; optionally create an initial one."""
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
    """Return a simplified equity curve as (timestamp, equity) points."""
    snapshots = list(
        db.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.created_at.asc())).scalars().all()
    )
    if not snapshots:
        return EquityCurve(points=[])

    if len(snapshots) > points:
        step = max(1, len(snapshots) // points)
        snapshots = snapshots[::step]

    out = EquityCurve(points=[])
    for s in snapshots:
        equity_curve_point = EquityCurvePoint(
            timestamp=int(s.created_at.timestamp()),
            equity=float(s.equity or 0.0),
        )
        out.points.append(equity_curve_point)
    return out


def snapshot_portfolio(db: Session, equity: float, cash: float, holdings: float) -> PortfolioSnapshot:
    """Persist a portfolio snapshot with values already computed by the orchestrator."""
    snapshot = PortfolioSnapshot(
        equity=float(equity or 0.0),
        cash=float(cash or 0.0),
        holdings=float(holdings or 0.0),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot
