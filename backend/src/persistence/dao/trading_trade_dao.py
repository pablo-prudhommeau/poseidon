from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from src.persistence.models import TradingTrade


class TradingTradeDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def retrieve_recent_trades(self, limit_count: int) -> List[TradingTrade]:
        database_query = select(TradingTrade).order_by(desc(TradingTrade.created_at)).limit(limit_count)
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_by_id(self, trade_id: int) -> Optional[TradingTrade]:
        database_query = select(TradingTrade).where(TradingTrade.id == trade_id)
        return self.database_session.execute(database_query).scalar_one_or_none()

    def retrieve_by_evaluation_id(self, evaluation_id: int) -> List[TradingTrade]:
        database_query = select(TradingTrade).where(TradingTrade.evaluation_id == evaluation_id)
        return list(self.database_session.execute(database_query).scalars().all())

    def save(self, trading_trade: TradingTrade) -> TradingTrade:
        self.database_session.add(trading_trade)
        self.database_session.flush()
        return trading_trade
