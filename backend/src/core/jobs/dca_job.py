from __future__ import annotations

import asyncio

from src.configuration.config import settings
from src.core.dca.dca_manager import DcaManager
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.dca.dca_order_dao import DcaOrderDao
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao

logger = get_application_logger(__name__)


class DcaJob:

    def __init__(self) -> None:
        self.is_running: bool = False

    async def start(self) -> None:
        self.is_running = True
        logger.info("[DCA][JOB] Background monitoring initialized.")

        while self.is_running:
            try:
                await self._process_tick()
            except Exception as exception:
                logger.exception("[DCA][JOB] Critical error during polling cycle: %s", exception)

            await asyncio.sleep(settings.AAVE_DCA_PROCESS_TICKER_INTERVAL_SECONDS)

    def stop(self) -> None:
        self.is_running = False
        logger.info("[DCA][JOB] Background monitoring stopped.")

    async def _process_tick(self) -> None:
        from src.persistence.db import get_database_session

        due_order_ids: list[int] = []

        with get_database_session() as database_session:
            order_dao = DcaOrderDao(database_session)
            current_time = get_current_local_datetime()
            due_orders = order_dao.retrieve_due_pending(current_time)
            if due_orders:
                due_order_ids = [o.id for o in due_orders]

        if due_order_ids:
            logger.info("[DCA][JOB] Found %d order(s) eligible for execution.", len(due_order_ids))

        for order_id in due_order_ids:
            with get_database_session() as database_session:
                order_dao = DcaOrderDao(database_session)
                strategy_dao = DcaStrategyDao(database_session)
                manager = DcaManager(database_session)

                order = order_dao.retrieve_by_id(order_id)
                if not order:
                    continue

                strategy = strategy_dao.retrieve_by_id(order.strategy_id)
                if strategy and strategy.strategy_status.value == "ACTIVE":
                    await manager.process_scheduled_dca_order(order, strategy)


dca_job = DcaJob()
