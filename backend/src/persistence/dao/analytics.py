from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import desc, select, and_
from sqlalchemy.orm import Session

from src.logging.logger import get_logger
from src.persistence.models import Analytics

logger = get_logger(__name__)


def insert_analytics_record(database_session: Session, analytics_record: Analytics) -> Analytics:
    logger.debug("[DATABASE][DAO][ANALYTICS][INSERT] Inserting new analytics record into database")
    database_session.add(analytics_record)
    database_session.flush()
    logger.debug("[DATABASE][DAO][ANALYTICS][INSERT] Successfully flushed new analytics record")
    return analytics_record


def retrieve_recent_analytics(database_session: Session, maximum_results_limit: int = 2000) -> list[Analytics]:
    logger.debug("[DATABASE][DAO][ANALYTICS][RETRIEVE] Fetching up to %d recent analytics records", maximum_results_limit)
    database_query = (
        select(Analytics)
        .order_by(desc(Analytics.evaluated_at), desc(Analytics.id))
        .limit(maximum_results_limit)
    )
    retrieved_analytics_records = list(database_session.execute(database_query).scalars().all())
    logger.info("[DATABASE][DAO][ANALYTICS][RETRIEVE] Successfully retrieved %d analytics records", len(retrieved_analytics_records))
    return retrieved_analytics_records


def attach_trade_outcome_to_analytics(
        database_session: Session,
        token_address: str,
        closed_at_timestamp: datetime,
        trade_identifier: int,
        profit_and_loss_percentage: float,
        profit_and_loss_usd: float,
        holding_duration_minutes: float,
        was_profitable: bool,
        exit_reason: Optional[str] = None,
) -> Optional[Analytics]:
    logger.debug("[DATABASE][DAO][ANALYTICS][OUTCOME] Attempting to attach trade outcome for token %s with trade identifier %d", token_address, trade_identifier)

    database_query = (
        select(Analytics)
        .where(
            and_(
                Analytics.token_address == token_address,
                Analytics.evaluated_at <= closed_at_timestamp,
                Analytics.has_outcome == False
            )
        )
        .order_by(desc(Analytics.evaluated_at), desc(Analytics.id))
        .limit(1)
    )

    target_analytics_record: Optional[Analytics] = database_session.execute(database_query).scalars().first()

    if target_analytics_record is None:
        logger.warning("[DATABASE][DAO][ANALYTICS][OUTCOME] No pending analytics record found for token %s to attach trade %d", token_address, trade_identifier)
        return None

    target_analytics_record.has_outcome = True
    target_analytics_record.outcome_trade_id = trade_identifier
    target_analytics_record.outcome_closed_at = closed_at_timestamp
    target_analytics_record.outcome_holding_minutes = holding_duration_minutes
    target_analytics_record.outcome_pnl_pct = profit_and_loss_percentage
    target_analytics_record.outcome_pnl_usd = profit_and_loss_usd
    target_analytics_record.outcome_was_profit = was_profitable
    target_analytics_record.outcome_exit_reason = exit_reason

    database_session.flush()
    logger.info("[DATABASE][DAO][ANALYTICS][OUTCOME] Successfully attached trade outcome to analytics record %d for token %s", target_analytics_record.id, token_address)

    return target_analytics_record
