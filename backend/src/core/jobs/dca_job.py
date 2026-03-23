from __future__ import annotations

import asyncio

from src.core.dca.dca_manager import DcaManager
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_logger
from src.persistence.dao.dca_dao import DcaDao
from src.persistence.db import SessionLocal

logger = get_logger(__name__)


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
                logger.error("[DCA][JOB] Critical error during polling cycle: %s", exception)

            await asyncio.sleep(60)

    def stop(self) -> None:
        self.is_running = False
        logger.info("[DCA][JOB] Background monitoring stopped.")

    async def _process_tick(self) -> None:
        db_session = SessionLocal()
        try:
            dao = DcaDao(db_session)
            manager = DcaManager(db_session)

            current_time = get_current_local_datetime()
            due_orders = dao.get_due_pending_orders(current_time)

            if due_orders:
                logger.info("[DCA][JOB] Found %d order(s) eligible for execution.", len(due_orders))

            for order in due_orders:
                if order.strategy.status.value == "ACTIVE":
                    await manager.process_due_order(order, order.strategy)

        finally:
            db_session.close()


dca_job = DcaJob()
