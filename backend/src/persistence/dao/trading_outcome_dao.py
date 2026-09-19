from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload, load_only

from src.logging.logger import get_application_logger
from src.persistence.models import TradeSide, TradingOutcome, TradingTrade

logger = get_application_logger(__name__)


class TradingOutcomeDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, trading_outcome: TradingOutcome) -> TradingOutcome:
        logger.debug("[DATABASE][DAO][TRADING_OUTCOME][SAVE] Saving trading outcome record")
        self.database_session.add(trading_outcome)
        self.database_session.flush()
        return trading_outcome

    def retrieve_by_id(self, outcome_id: int) -> Optional[TradingOutcome]:
        return self.database_session.get(TradingOutcome, outcome_id)

    def retrieve_recent(self, limit: int = 50) -> List[TradingOutcome]:
        logger.debug("[DATABASE][DAO][TRADING_OUTCOME][RETRIEVE] Fetching up to %d recent outcome records", limit)
        database_query = (
            select(TradingOutcome)
            .order_by(desc(TradingOutcome.occurred_at), desc(TradingOutcome.id))
            .limit(limit)
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_closed_sells_in_window(
            self,
            start_datetime: datetime,
            end_datetime: datetime,
    ) -> list[TradingOutcome]:
        logger.debug(
            "[DATABASE][DAO][TRADING_OUTCOME][RETRIEVE] Fetching closed SELL outcomes in range [%s, %s]",
            start_datetime,
            end_datetime,
        )
        try:
            database_query = (
                select(TradingOutcome)
                .join(TradingTrade, TradingOutcome.trade_id == TradingTrade.id)
                .options(
                    joinedload(TradingOutcome.trade).load_only(
                        TradingTrade.id,
                        TradingTrade.trade_side,
                        TradingTrade.token_symbol,
                        TradingTrade.execution_status,
                    )
                )
                .where(TradingTrade.trade_side == TradeSide.SELL)
                .where(TradingOutcome.occurred_at >= start_datetime)
                .where(TradingOutcome.occurred_at <= end_datetime)
                .order_by(TradingOutcome.occurred_at.asc(), TradingOutcome.id.asc())
            )
            return list(self.database_session.execute(database_query).unique().scalars().all())
        except Exception as error:
            logger.exception(
                "[DAO][TRADING_OUTCOME] Failed to retrieve closed SELL outcomes in range [%s, %s] — %s",
                start_datetime,
                end_datetime,
                error,
            )
            raise
