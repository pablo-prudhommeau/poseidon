from __future__ import annotations

from typing import List, Optional

from sqlalchemy import desc, select, and_
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import TradingEvaluation

logger = get_application_logger(__name__)


class TradingEvaluationDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, trading_evaluation: TradingEvaluation) -> TradingEvaluation:
        logger.debug("[DATABASE][DAO][TRADING_EVALUATION][SAVE] Saving trading evaluation record")
        self.database_session.add(trading_evaluation)
        self.database_session.flush()
        return trading_evaluation

    def retrieve_by_id(self, evaluation_id: int) -> Optional[TradingEvaluation]:
        return self.database_session.get(TradingEvaluation, evaluation_id)

    def retrieve_recent(self, limit: int = 1000) -> List[TradingEvaluation]:
        logger.debug("[DATABASE][DAO][TRADING_EVALUATION][RETRIEVE] Fetching up to %d recent evaluation records", limit)
        database_query = (
            select(TradingEvaluation)
            .order_by(desc(TradingEvaluation.evaluated_at), desc(TradingEvaluation.id))
            .limit(limit)
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_latest_buy_decision(self, token_address: str, before_timestamp: float) -> Optional[TradingEvaluation]:
        database_query = (
            select(TradingEvaluation)
            .where(
                and_(
                    TradingEvaluation.token_address == token_address,
                    TradingEvaluation.evaluated_at <= before_timestamp,
                    TradingEvaluation.execution_decision == "BUY"
                )
            )
            .order_by(desc(TradingEvaluation.evaluated_at), desc(TradingEvaluation.id))
            .limit(1)
        )
        return self.database_session.execute(database_query).scalars().first()
