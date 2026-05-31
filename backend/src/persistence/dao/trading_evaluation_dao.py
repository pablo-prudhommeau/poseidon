from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc, select, and_
from sqlalchemy.orm import Session

from src.api.http.api_schemas import TradingEvaluationPayload
from src.api.serializers import serialize_trading_evaluation
from src.logging.logger import get_application_logger
from src.persistence.dao.trading_outcome_dao import TradingOutcomeDao
from src.persistence.models import TradingEvaluation, TradingOutcome

logger = get_application_logger(__name__)


class TradingEvaluationDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, trading_evaluation: TradingEvaluation) -> TradingEvaluation:
        logger.debug("[DATABASE][DAO][TRADING_EVALUATION][SAVE] Saving trading evaluation record")
        self.database_session.add(trading_evaluation)
        self.database_session.flush()
        return trading_evaluation

    def record_evaluation(self, trading_evaluation: TradingEvaluation) -> TradingEvaluationPayload:
        logger.debug("[DATABASE][DAO][TRADING_EVALUATION][RECORD] Recording trading evaluation")
        self.save(trading_evaluation)
        self.database_session.flush()
        logger.info("[DATABASE][DAO][TRADING_EVALUATION][RECORD] Successfully recorded trading evaluation")
        return serialize_trading_evaluation(trading_evaluation)

    def link_trade_outcome(
            self,
            token_address: str,
            trade_id: int,
            closed_at: datetime,
            realized_profit_and_loss_percentage: float,
            realized_profit_and_loss_usd: float,
            holding_duration_minutes: float,
            was_profitable: bool,
    ) -> Optional[TradingEvaluationPayload]:
        logger.debug("[DATABASE][DAO][TRADING_EVALUATION][OUTCOME] Linking trade outcome for trade id %s", trade_id)

        evaluation = self.retrieve_latest_buy_decision(token_address, closed_at.timestamp())
        if not evaluation:
            logger.warning(
                "[DATABASE][DAO][TRADING_EVALUATION][OUTCOME] No evaluation record found for token %s",
                token_address,
            )
            return None

        outcome_record = TradingOutcome(
            evaluation_id=evaluation.id,
            trade_id=trade_id,
            occurred_at=closed_at,
            realized_profit_and_loss_percentage=realized_profit_and_loss_percentage,
            realized_profit_and_loss_usd=realized_profit_and_loss_usd,
            holding_duration_minutes=holding_duration_minutes,
            is_profitable=was_profitable,
        )

        TradingOutcomeDao(self.database_session).save(outcome_record)
        self.database_session.flush()
        logger.info("[DATABASE][DAO][TRADING_EVALUATION][OUTCOME] Successfully linked outcome for trade id %s", trade_id)
        return serialize_trading_evaluation(evaluation)

    def retrieve_by_id(self, evaluation_id: int) -> Optional[TradingEvaluation]:
        from sqlalchemy.orm import joinedload
        database_query = (
            select(TradingEvaluation)
            .options(joinedload(TradingEvaluation.outcomes))
            .where(TradingEvaluation.id == evaluation_id)
        )
        return self.database_session.execute(database_query).unique().scalars().first()

    def retrieve_latest_evaluation_by_pair(self, pair_address: str) -> Optional[TradingEvaluation]:
        from sqlalchemy.orm import joinedload
        database_query = (
            select(TradingEvaluation)
            .options(joinedload(TradingEvaluation.outcomes))
            .where(TradingEvaluation.pair_address == pair_address)
            .order_by(desc(TradingEvaluation.evaluated_at), desc(TradingEvaluation.id))
            .limit(1)
        )
        return self.database_session.execute(database_query).unique().scalars().first()

    def retrieve_recent_evaluations(self, limit_count: int = 1000) -> List[TradingEvaluation]:
        from sqlalchemy.orm import joinedload
        logger.debug("[DATABASE][DAO][TRADING_EVALUATION][RETRIEVE] Fetching up to %d recent evaluations", limit_count)
        database_query = (
            select(TradingEvaluation)
            .options(joinedload(TradingEvaluation.outcomes))
            .order_by(desc(TradingEvaluation.evaluated_at), desc(TradingEvaluation.id))
            .limit(limit_count)
        )
        return list(self.database_session.execute(database_query).unique().scalars().all())

    def retrieve_latest_buy_decision(self, token_address: str, before_timestamp: float) -> Optional[TradingEvaluation]:
        database_query = (
            select(TradingEvaluation)
            .where(
                and_(
                    TradingEvaluation.token_address == token_address,
                    TradingEvaluation.evaluated_at <= datetime.fromtimestamp(before_timestamp),
                    TradingEvaluation.execution_decision == "BUY"
                )
            )
            .order_by(desc(TradingEvaluation.evaluated_at), desc(TradingEvaluation.id))
            .limit(1)
        )
        return self.database_session.execute(database_query).scalars().first()

    def count_total_evaluations(self) -> int:
        from sqlalchemy import func
        try:
            return self.database_session.execute(
                select(func.count(TradingEvaluation.id))
            ).scalar_one_or_none() or 0
        except Exception as error:
            logger.exception("[DAO][TRADING_EVALUATION] Failed to count evaluations — %s", error)
            raise
