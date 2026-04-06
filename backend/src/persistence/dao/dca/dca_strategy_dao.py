from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import DcaStrategy

logger = get_application_logger(__name__)


class DcaStrategyDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, dca_strategy: DcaStrategy) -> DcaStrategy:
        logger.debug("[DATABASE][DAO][DCA_STRATEGY][SAVE] Saving DCA strategy record")
        self.database_session.add(dca_strategy)
        self.database_session.flush()
        return dca_strategy

    def retrieve_by_id(self, strategy_id: int) -> Optional[DcaStrategy]:
        return self.database_session.get(DcaStrategy, strategy_id)

    def retrieve_active(self) -> List[DcaStrategy]:
        logger.debug("[DATABASE][DAO][DCA_STRATEGY][RETRIEVE] Fetching active DCA strategies")
        database_query = select(DcaStrategy).where(DcaStrategy.strategy_status == "ACTIVE")
        return list(self.database_session.execute(database_query).scalars().all())

    def update_strategy_execution_metrics(
            self,
            dca_strategy: DcaStrategy,
            last_execution_source_amount: float,
            last_execution_price: float
    ) -> None:
        current_total_amount = dca_strategy.total_deployed_amount or 0.0
        current_total_quantity = 0.0
        if dca_strategy.average_purchase_price > 0:
            current_total_quantity = current_total_amount / dca_strategy.average_purchase_price

        new_total_amount = current_total_amount + last_execution_source_amount
        new_quantity = 0.0
        if last_execution_price > 0:
            new_quantity = last_execution_source_amount / last_execution_price
            
        new_total_quantity = current_total_quantity + new_quantity

        dca_strategy.total_deployed_amount = new_total_amount
        if new_total_quantity > 0:
            dca_strategy.average_purchase_price = new_total_amount / new_total_quantity

        self.save(dca_strategy)

    def retrieve_all(self) -> List[DcaStrategy]:
        database_query = select(DcaStrategy)
        return list(self.database_session.execute(database_query).scalars().all())

    def delete(self, strategy_id: int) -> bool:
        logger.warning("[DATABASE][DAO][DCA_STRATEGY][DELETE] Deleting DCA strategy ID: %d", strategy_id)
        strategy_record = self.retrieve_by_id(strategy_id)
        if strategy_record:
            self.database_session.delete(strategy_record)
            self.database_session.flush()
            return True
        return False
