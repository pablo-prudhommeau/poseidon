from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, desc, asc
from sqlalchemy.orm import Session

from src.core.trading.trading_structures import TradingPortfolioEquityCurvePoint
from src.core.utils.date_utils import get_current_local_datetime
from src.persistence.models import TradingPortfolioSnapshot


class TradingPortfolioSnapshotDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def retrieve_initial_snapshot(self) -> Optional[TradingPortfolioSnapshot]:
        database_query = select(TradingPortfolioSnapshot).order_by(asc(TradingPortfolioSnapshot.created_at)).limit(1)
        return self.database_session.execute(database_query).scalar_one_or_none()

    def retrieve_latest_snapshot(self) -> Optional[TradingPortfolioSnapshot]:
        database_query = select(TradingPortfolioSnapshot).order_by(desc(TradingPortfolioSnapshot.created_at)).limit(1)
        return self.database_session.execute(database_query).scalar_one_or_none()

    def retrieve_snapshot_history(self, limit: int = 100) -> List[TradingPortfolioSnapshot]:
        database_query = select(TradingPortfolioSnapshot).order_by(desc(TradingPortfolioSnapshot.created_at)).limit(limit)
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_snapshots_in_window(
            self,
            start_datetime: datetime,
            end_datetime: datetime,
    ) -> List[TradingPortfolioSnapshot]:
        database_query = (
            select(TradingPortfolioSnapshot)
            .where(TradingPortfolioSnapshot.created_at >= start_datetime)
            .where(TradingPortfolioSnapshot.created_at <= end_datetime)
            .order_by(asc(TradingPortfolioSnapshot.created_at))
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_equity_curve_points(self, limit_count: int = 100) -> list[TradingPortfolioEquityCurvePoint]:
        database_query = (
            select(TradingPortfolioSnapshot)
            .order_by(desc(TradingPortfolioSnapshot.created_at))
            .limit(limit_count)
        )
        equity_snapshots = list(self.database_session.execute(database_query).scalars().all())

        return [
            TradingPortfolioEquityCurvePoint(
                timestamp_milliseconds=int(snapshot.created_at.timestamp() * 1000),
                total_equity_value=snapshot.total_equity_value,
            )
            for snapshot in reversed(equity_snapshots)
        ]

    def create_snapshot(
            self,
            total_equity_value: float,
            deployable_cash_usd: float,
            holdings_mark_to_market_usd: float,
            wallet_auxiliary_assets_usd: float,
            sizing_capital_usd: float,
    ) -> TradingPortfolioSnapshot:
        new_snapshot = TradingPortfolioSnapshot(
            total_equity_value=total_equity_value,
            deployable_cash_usd=deployable_cash_usd,
            holdings_mark_to_market_usd=holdings_mark_to_market_usd,
            wallet_auxiliary_assets_usd=wallet_auxiliary_assets_usd,
            sizing_capital_usd=sizing_capital_usd,
            created_at=get_current_local_datetime(),
        )
        self.save(new_snapshot)
        return new_snapshot

    def save(self, portfolio_snapshot: TradingPortfolioSnapshot) -> TradingPortfolioSnapshot:
        self.database_session.add(portfolio_snapshot)
        self.database_session.flush()
        return portfolio_snapshot
