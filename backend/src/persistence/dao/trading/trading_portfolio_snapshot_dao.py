from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from src.core.utils.date_utils import get_current_local_datetime
from src.persistence.models import TradingPortfolioSnapshot


class TradingPortfolioSnapshotDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def retrieve_latest_snapshot(self) -> Optional[TradingPortfolioSnapshot]:
        database_query = select(TradingPortfolioSnapshot).order_by(desc(TradingPortfolioSnapshot.created_at)).limit(1)
        return self.database_session.execute(database_query).scalar_one_or_none()

    def retrieve_snapshot_history(self, limit: int = 100) -> List[TradingPortfolioSnapshot]:
        database_query = select(TradingPortfolioSnapshot).order_by(desc(TradingPortfolioSnapshot.created_at)).limit(limit)
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_equity_curve(self, limit_count: int = 100) -> List[float]:
        database_query = (
            select(TradingPortfolioSnapshot.equity_value)
            .order_by(desc(TradingPortfolioSnapshot.created_at))
            .limit(limit_count)
        )
        equity_snapshots = list(self.database_session.execute(database_query).scalars().all())
        return [float(equity) for equity in reversed(equity_snapshots)]

    def create_snapshot(self, equity: float, cash: float, holdings: float) -> TradingPortfolioSnapshot:
        new_snapshot = TradingPortfolioSnapshot(
            equity_value=equity,
            cash_value=cash,
            holdings_value=holdings,
            created_at=get_current_local_datetime()
        )
        self.save(new_snapshot)
        return new_snapshot

    def save(self, portfolio_snapshot: TradingPortfolioSnapshot) -> TradingPortfolioSnapshot:
        self.database_session.add(portfolio_snapshot)
        self.database_session.flush()
        return portfolio_snapshot
