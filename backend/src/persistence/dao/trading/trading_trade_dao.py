from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from src.persistence.models import TradingTrade, ExecutionStatus


class TradingTradeDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def retrieve_all_trades(self) -> List[TradingTrade]:
        database_query = select(TradingTrade).order_by(desc(TradingTrade.created_at))
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_recent_trades(self, limit_count: int) -> List[TradingTrade]:
        database_query = select(TradingTrade).order_by(desc(TradingTrade.created_at)).limit(limit_count)
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_paper_trades(self) -> List[TradingTrade]:
        database_query = select(TradingTrade).where(TradingTrade.execution_status == ExecutionStatus.PAPER).order_by(desc(TradingTrade.created_at))
        return list(self.database_session.execute(database_query).scalars().all())

    def get_by_id(self, trade_id: int) -> Optional[TradingTrade]:
        return self.database_session.get(TradingTrade, trade_id)

    def save(self, trading_trade: TradingTrade) -> TradingTrade:
        self.database_session.add(trading_trade)
        self.database_session.flush()
        return trading_trade
