from __future__ import annotations

import asyncio

from src.configuration.config import settings
from src.core.aavedca.aave_dca_service import AaveDcaService
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.database_session_manager import get_database_session

logger = get_application_logger(__name__)


class AaveDcaJob:

    def __init__(self) -> None:
        self.is_running: bool = False

    async def run_loop(self) -> None:
        self.is_running = True
        logger.info("[AAVEDCA][JOB] Background monitoring initialized.")

        while self.is_running:
            try:
                await self._process_tick()
            except Exception as exception:
                logger.exception("[AAVEDCA][JOB] Critical error during polling cycle: %s", exception)

            await asyncio.sleep(settings.AAVE_DCA_PROCESS_TICKER_INTERVAL_SECONDS)

    def stop(self) -> None:
        self.is_running = False
        logger.info("[AAVEDCA][JOB] Background monitoring stopped.")

    async def _process_tick(self) -> None:
        due_order_ids: list[int] = []

        with get_database_session() as database_session:
            order_dao = AaveDcaOrderDao(database_session)
            current_time = get_current_local_datetime()
            due_orders = order_dao.retrieve_due_pending(current_time)
            if due_orders:
                due_order_ids = [o.id for o in due_orders]

        if due_order_ids:
            logger.info("[AAVEDCA][JOB] Found %d order(s) eligible for execution.", len(due_order_ids))

        for order_id in due_order_ids:
            with get_database_session() as database_session:
                order_dao = AaveDcaOrderDao(database_session)
                strategy_dao = AaveDcaStrategyDao(database_session)
                service = AaveDcaService(database_session)

                order = order_dao.retrieve_by_id(order_id)
                if not order:
                    continue

                strategy = strategy_dao.retrieve_by_id(order.strategy_id)
                if strategy and strategy.strategy_status.value == "ACTIVE":
                    await service.process_scheduled_dca_order(order, strategy)


aave_dca_job = AaveDcaJob()
