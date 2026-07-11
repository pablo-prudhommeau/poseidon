from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import or_, select, desc
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import AaveDcaOrder

logger = get_application_logger(__name__)


class AaveDcaOrderDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, dca_order: AaveDcaOrder) -> AaveDcaOrder:
        logger.debug("[DATABASE][DAO][AAVEDCA_ORDER][SAVE] Saving DCA order record")
        self.database_session.add(dca_order)
        self.database_session.flush()
        return dca_order

    def bulk_save(self, dca_orders: List[AaveDcaOrder]) -> List[AaveDcaOrder]:
        logger.debug("[DATABASE][DAO][AAVEDCA_ORDER][BULK_SAVE] Saving %d DCA orders", len(dca_orders))
        self.database_session.add_all(dca_orders)
        self.database_session.flush()
        return dca_orders

    def retrieve_by_id(self, order_id: int) -> Optional[AaveDcaOrder]:
        return self.database_session.get(AaveDcaOrder, order_id)

    def retrieve_pending_by_strategy(self, strategy_id: int) -> List[AaveDcaOrder]:
        logger.debug("[DATABASE][DAO][AAVEDCA_ORDER][RETRIEVE] Fetching pending orders for strategy %d", strategy_id)
        database_query = (
            select(AaveDcaOrder)
            .where(AaveDcaOrder.strategy_id == strategy_id)
            .where(AaveDcaOrder.order_status == "PENDING")
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_due_pending(self, current_timestamp: datetime) -> List[AaveDcaOrder]:
        resumable_order_statuses = [
            "PENDING",
            "AWAITING_WITHDRAW",
            "AWAITING_SWAP",
            "AWAITING_SUPPLY",
        ]
        database_query = (
            select(AaveDcaOrder)
            .where(AaveDcaOrder.order_status.in_(resumable_order_statuses))
            .where(AaveDcaOrder.planned_execution_date <= current_timestamp)
            .where(AaveDcaOrder.suspension_reason.is_(None))
            .where(
                or_(
                    AaveDcaOrder.next_attempt_at.is_(None),
                    AaveDcaOrder.next_attempt_at <= current_timestamp,
                )
            )
            .order_by(AaveDcaOrder.id.asc())
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_active_telegram_orders(self) -> List[AaveDcaOrder]:
        active_order_statuses = [
            "WAITING_USER_APPROVAL",
            "AWAITING_WITHDRAW",
            "AWAITING_SWAP",
            "AWAITING_SUPPLY",
        ]
        database_query = (
            select(AaveDcaOrder)
            .where(
                or_(
                    AaveDcaOrder.order_status.in_(active_order_statuses),
                    AaveDcaOrder.suspension_reason.is_not(None),
                )
            )
            .order_by(AaveDcaOrder.id.asc())
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_by_strategy(self, strategy_id: int) -> List[AaveDcaOrder]:
        database_query = (
            select(AaveDcaOrder)
            .where(AaveDcaOrder.strategy_id == strategy_id)
            .order_by(AaveDcaOrder.planned_execution_date.asc())
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_history_by_strategy(self, strategy_id: int) -> List[AaveDcaOrder]:
        database_query = select(AaveDcaOrder).where(AaveDcaOrder.strategy_id == strategy_id).order_by(desc(AaveDcaOrder.planned_execution_date))
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_latest_executed_by_strategy(self, strategy_id: int) -> Optional[AaveDcaOrder]:
        database_query = (
            select(AaveDcaOrder)
            .where(AaveDcaOrder.strategy_id == strategy_id)
            .where(AaveDcaOrder.order_status == "EXECUTED")
            .order_by(desc(AaveDcaOrder.executed_at))
            .limit(1)
        )
        return self.database_session.execute(database_query).scalars().first()

    def retrieve_all_executed(self) -> List[AaveDcaOrder]:
        database_query = (
            select(AaveDcaOrder)
            .where(AaveDcaOrder.order_status == "EXECUTED")
            .order_by(desc(AaveDcaOrder.executed_at))
        )
        return list(self.database_session.execute(database_query).scalars().all())
