from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import DcaOrder

logger = get_application_logger(__name__)


class DcaOrderDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, dca_order: DcaOrder) -> DcaOrder:
        logger.debug("[DATABASE][DAO][DCA_ORDER][SAVE] Saving DCA order record")
        self.database_session.add(dca_order)
        self.database_session.flush()
        return dca_order

    def bulk_save(self, dca_orders: List[DcaOrder]) -> List[DcaOrder]:
        logger.debug("[DATABASE][DAO][DCA_ORDER][BULK_SAVE] Saving %d DCA orders", len(dca_orders))
        self.database_session.add_all(dca_orders)
        self.database_session.flush()
        return dca_orders

    def retrieve_by_id(self, order_id: int) -> Optional[DcaOrder]:
        return self.database_session.get(DcaOrder, order_id)

    def retrieve_pending_by_strategy(self, strategy_id: int) -> List[DcaOrder]:
        logger.debug("[DATABASE][DAO][DCA_ORDER][RETRIEVE] Fetching pending orders for strategy %d", strategy_id)
        database_query = (
            select(DcaOrder)
            .where(DcaOrder.strategy_id == strategy_id)
            .where(DcaOrder.order_status == "PENDING")
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_due_pending(self, current_timestamp: datetime) -> List[DcaOrder]:
        database_query = (
            select(DcaOrder)
            .where(DcaOrder.order_status.in_(["PENDING", "APPROVED"]))
            .where(DcaOrder.planned_execution_date <= current_timestamp)
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_by_strategy(self, strategy_id: int) -> List[DcaOrder]:
        database_query = (
            select(DcaOrder)
            .where(DcaOrder.strategy_id == strategy_id)
            .order_by(DcaOrder.planned_execution_date.asc())
        )
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_history_by_strategy(self, strategy_id: int) -> List[DcaOrder]:
        database_query = select(DcaOrder).where(DcaOrder.strategy_id == strategy_id).order_by(desc(DcaOrder.planned_execution_date))
        return list(self.database_session.execute(database_query).scalars().all())

    def retrieve_latest_executed_by_strategy(self, strategy_id: int) -> Optional[DcaOrder]:
        database_query = (
            select(DcaOrder)
            .where(DcaOrder.strategy_id == strategy_id)
            .where(DcaOrder.order_status == "EXECUTED")
            .order_by(desc(DcaOrder.executed_at))
            .limit(1)
        )
        return self.database_session.execute(database_query).scalars().first()

    def retrieve_all_executed(self) -> List[DcaOrder]:
        database_query = (
            select(DcaOrder)
            .where(DcaOrder.order_status == "EXECUTED")
            .order_by(desc(DcaOrder.executed_at))
        )
        return list(self.database_session.execute(database_query).scalars().all())
