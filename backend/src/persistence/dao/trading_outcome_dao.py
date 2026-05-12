from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import TradingOutcome

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
