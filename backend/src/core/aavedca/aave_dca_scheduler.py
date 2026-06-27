from __future__ import annotations

from datetime import datetime

from src.core.aavedca.aave_dca_structures import AaveDcaOrderStatus
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.models import AaveDcaStrategy, AaveDcaOrder

logger = get_application_logger(__name__)


class AaveDcaScheduler:
    @staticmethod
    def generate_linear_execution_calendar(dca_strategy: AaveDcaStrategy) -> list[AaveDcaOrder]:
        scheduled_orders_collection: list[AaveDcaOrder] = []

        system_local_timezone = get_current_local_datetime().tzinfo

        strategy_start_date_local = dca_strategy.strategy_start_date
        if strategy_start_date_local.tzinfo is None:
            strategy_start_date_local = strategy_start_date_local.replace(tzinfo=system_local_timezone)

        strategy_end_date_local = dca_strategy.strategy_end_date
        if strategy_end_date_local.tzinfo is None:
            strategy_end_date_local = strategy_end_date_local.replace(tzinfo=system_local_timezone)

        total_strategy_duration_in_seconds = (strategy_end_date_local - strategy_start_date_local).total_seconds()

        if total_strategy_duration_in_seconds <= 0 or dca_strategy.total_planned_executions <= 0:
            logger.warning(
                "[AAVEDCA][SCHEDULER][VALIDATION] Aborting calendar generation: invalid duration (%s s) or execution count (%s) for strategy id %s",
                total_strategy_duration_in_seconds,
                dca_strategy.total_planned_executions,
                dca_strategy.id
            )
            return scheduled_orders_collection

        time_interval_between_executions_in_seconds = total_strategy_duration_in_seconds / dca_strategy.total_planned_executions
        current_iterative_timestamp = strategy_start_date_local.timestamp()

        logger.debug(
            "[AAVEDCA][SCHEDULER][COMPUTE] Generating %s orders with an interval of %0.2f seconds",
            dca_strategy.total_planned_executions,
            time_interval_between_executions_in_seconds
        )

        for execution_index in range(dca_strategy.total_planned_executions):
            calculated_scheduled_date = datetime.fromtimestamp(current_iterative_timestamp, tz=system_local_timezone)

            new_dca_order = AaveDcaOrder(
                strategy_id=dca_strategy.id,
                planned_execution_date=calculated_scheduled_date,
                planned_source_asset_amount=dca_strategy.amount_per_execution_order,
                executed_source_asset_amount=None,
                executed_target_asset_amount=None,
                order_status=AaveDcaOrderStatus.PENDING,
                transaction_hash=None,
                actual_execution_price=None,
                executed_at=None
            )
            scheduled_orders_collection.append(new_dca_order)

            current_iterative_timestamp += time_interval_between_executions_in_seconds

        logger.info(
            "[AAVEDCA][SCHEDULER][SUCCESS] Successfully generated %d linear execution orders for strategy id %s",
            len(scheduled_orders_collection),
            dca_strategy.id
        )
        return scheduled_orders_collection
