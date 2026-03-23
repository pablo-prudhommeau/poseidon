from datetime import datetime, timezone
from typing import List

from src.core.structures.structures import DcaOrderStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_logger
from src.persistence.models import DcaStrategy, DcaOrder

logger = get_logger(__name__)


class DcaScheduler:
    """
    Mathematical engine responsible for generating the strict execution calendar.
    Distributes executions purely linearly across the target timeframe.
    """

    @staticmethod
    def generate_calendar(strategy: DcaStrategy) -> List[DcaOrder]:
        """
        Calculates and returns a list of DcaOrder entities based on the strategy parameters.
        Explicitly initializes all execution-related fields to None to respect database integrity constraints.
        """
        generated_orders: List[DcaOrder] = []

        reference_tz = get_current_local_datetime().tzinfo or timezone.utc

        def ensure_aware(dt: datetime) -> datetime:
            return dt.replace(tzinfo=reference_tz) if dt.tzinfo is None else dt

        start_date_aware = ensure_aware(strategy.start_date)
        end_date_aware = ensure_aware(strategy.end_date)

        strategy_duration_seconds = (end_date_aware - start_date_aware).total_seconds()

        if strategy_duration_seconds <= 0 or strategy.total_executions <= 0:
            logger.warning("[DCA][SCHEDULER] Invalid duration or execution count for strategy %s", strategy.id)
            return generated_orders

        interval_duration_seconds = strategy_duration_seconds / strategy.total_executions
        current_theoretical_timestamp = start_date_aware.timestamp()

        for _ in range(strategy.total_executions):
            scheduled_date = datetime.fromtimestamp(current_theoretical_timestamp, tz=reference_tz)

            order = DcaOrder(
                strategy_id=strategy.id,
                planned_date=scheduled_date,
                planned_amount=strategy.amount_per_order,
                executed_amount_in=None,
                executed_amount_out=None,
                status=DcaOrderStatus.PENDING,
                transaction_hash=None,
                execution_price=None,
                executed_at=None
            )
            generated_orders.append(order)

            current_theoretical_timestamp += interval_duration_seconds

        logger.info("[DCA][SCHEDULER] Generated %d linear orders for strategy %s", len(generated_orders), strategy.id)
        return generated_orders
