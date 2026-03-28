from datetime import datetime
from typing import List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.core.structures.structures import DcaStrategyStatus, DcaOrderStatus
from src.persistence.models import DcaStrategy, DcaOrder


class DcaDao:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_strategy(self, strategy: DcaStrategy) -> DcaStrategy:
        self.session.add(strategy)
        self.session.commit()
        self.session.refresh(strategy)
        return strategy

    def get_strategy_by_id(self, strategy_id: int) -> Optional[DcaStrategy]:
        return self.session.query(DcaStrategy).filter(DcaStrategy.id == strategy_id).first()

    def get_all_strategies(self) -> List[DcaStrategy]:
        return self.session.query(DcaStrategy).order_by(desc(DcaStrategy.created_at)).all()

    def bulk_create_orders(self, orders: List[DcaOrder]) -> None:
        self.session.bulk_save_objects(orders)
        self.session.commit()

    def get_due_pending_orders(self, reference_time: datetime) -> List[DcaOrder]:
        return self.session.query(DcaOrder).filter(
            DcaOrder.order_status.in_([DcaOrderStatus.PENDING, DcaOrderStatus.APPROVED]),
            DcaOrder.planned_execution_date <= reference_time
        ).order_by(DcaOrder.planned_execution_date).all()

    def get_pending_orders_count(self, strategy_id: int) -> int:
        return self.session.query(DcaOrder).filter(
            DcaOrder.strategy_id == strategy_id,
            DcaOrder.order_status == DcaOrderStatus.PENDING
        ).count()

    def get_orders_for_strategy(self, strategy_id: int) -> List[DcaOrder]:
        return self.session.query(DcaOrder).filter(
            DcaOrder.strategy_id == strategy_id
        ).order_by(DcaOrder.planned_execution_date).all()

    def update_order(self, order: DcaOrder) -> DcaOrder:
        self.session.add(order)
        self.session.commit()
        self.session.refresh(order)
        return order

    def update_strategy_execution_metrics(
            self,
            strategy: DcaStrategy,
            executed_amount_usd: float,
            execution_price: float
    ) -> DcaStrategy:
        current_quantity = (strategy.total_deployed_amount / strategy.average_purchase_price) if strategy.average_purchase_price > 0 else 0.0
        new_quantity = executed_amount_usd / execution_price if execution_price > 0 else 0.0

        strategy.total_deployed_amount += executed_amount_usd

        total_quantity = current_quantity + new_quantity
        if total_quantity > 0:
            strategy.average_purchase_price = strategy.total_deployed_amount / total_quantity

        completion_threshold = strategy.total_allocated_budget * 0.99
        if strategy.total_deployed_amount >= completion_threshold:
            strategy.strategy_status = DcaStrategyStatus.COMPLETED

        self.session.add(strategy)
        self.session.commit()
        self.session.refresh(strategy)

        return strategy
