from __future__ import annotations

import asyncio

from src.configuration.config import settings
from src.core.dca.dca_manager import DcaManager
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.dca.dca_order_dao import DcaOrderDao
from src.persistence.dao.dca.dca_strategy_dao import DcaStrategyDao
from src.persistence.db import DatabaseSessionLocal

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
        db_session = DatabaseSessionLocal()
        try:
            order_dao = DcaOrderDao(db_session)
            strategy_dao = DcaStrategyDao(db_session)
            manager = DcaManager(db_session)

            current_time = get_current_local_datetime()
            due_orders = order_dao.retrieve_due_pending(current_time)

            if due_orders:
                logger.info("[DCA][JOB] Found %d order(s) eligible for execution.", len(due_orders))

            for order in due_orders:
                strategy = strategy_dao.retrieve_by_id(order.strategy_id)
                if strategy and strategy.strategy_status == "ACTIVE":
                    await manager.process_scheduled_dca_order(order, strategy)

        finally:
            db_session.close()


dca_job = DcaJob()
