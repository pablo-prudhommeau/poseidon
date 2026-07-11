from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.logging.logger import get_application_logger
from src.persistence.models import AaveDcaStrategy

logger = get_application_logger(__name__)


class AaveDcaStrategyDao:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session

    def save(self, dca_strategy: AaveDcaStrategy) -> AaveDcaStrategy:
        logger.debug("[DATABASE][DAO][AAVEDCA_STRATEGY][SAVE] Saving DCA strategy record")
        self.database_session.add(dca_strategy)
        self.database_session.flush()
        return dca_strategy

    def retrieve_by_id(self, strategy_id: int) -> Optional[AaveDcaStrategy]:
        return self.database_session.get(AaveDcaStrategy, strategy_id)

    def retrieve_active(self) -> List[AaveDcaStrategy]:
        logger.debug("[DATABASE][DAO][AAVEDCA_STRATEGY][RETRIEVE] Fetching active DCA strategies")
        database_query = select(AaveDcaStrategy).where(AaveDcaStrategy.strategy_status == "ACTIVE")
        return list(self.database_session.execute(database_query).scalars().all())

    def update_strategy_execution_metrics(
            self,
            dca_strategy: AaveDcaStrategy,
            last_execution_source_amount: float,
            last_execution_target_asset_amount: Optional[float] = None,
            last_execution_reference_price: Optional[float] = None,
    ) -> None:
        current_total_amount: float = dca_strategy.total_deployed_amount or 0.0
        current_total_quantity: float = 0.0
        if dca_strategy.average_purchase_price > 0:
            current_total_quantity = current_total_amount / dca_strategy.average_purchase_price

        new_total_amount: float = current_total_amount + last_execution_source_amount
        new_quantity: float = 0.0
        if last_execution_target_asset_amount is not None and last_execution_target_asset_amount > 0:
            new_quantity = last_execution_target_asset_amount
        elif last_execution_reference_price is not None and last_execution_reference_price > 0:
            new_quantity = last_execution_source_amount / last_execution_reference_price

        new_total_quantity: float = current_total_quantity + new_quantity

        dca_strategy.total_deployed_amount = new_total_amount
        if new_total_quantity > 0:
            dca_strategy.average_purchase_price = new_total_amount / new_total_quantity

        self.save(dca_strategy)

    def retrieve_all(self) -> List[AaveDcaStrategy]:
        database_query = select(AaveDcaStrategy)
        return list(self.database_session.execute(database_query).scalars().all())

    def delete(self, strategy_id: int) -> bool:
        logger.warning("[DATABASE][DAO][AAVEDCA_STRATEGY][DELETE] Deleting DCA strategy ID: %d", strategy_id)
        strategy_record = self.retrieve_by_id(strategy_id)
        if strategy_record:
            self.database_session.delete(strategy_record)
            self.database_session.flush()
            return True
        return False
