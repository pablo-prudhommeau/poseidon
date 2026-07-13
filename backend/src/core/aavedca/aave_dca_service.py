from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.aavedca.aave_dca_order_scheduling_service import AaveDcaOrderSchedulingService
from src.core.aavedca.aave_dca_pipeline_preflight_service import AaveDcaPipelinePreflightService
from src.core.aavedca.aave_dca_pipeline_recovery_service import AaveDcaPipelineRecoveryService
from src.core.aavedca.aave_dca_pipeline_service import AaveDcaPipelineService
from src.integrations.aave.aave_executor import AaveExecutor
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy


class AaveDcaService:
    def __init__(self, database_session: Session) -> None:
        self.database_session = database_session
        self.dca_strategy_dao = AaveDcaStrategyDao(database_session)
        self.dca_order_dao = AaveDcaOrderDao(database_session)
        self.aave_executor = AaveExecutor()

        self.preflight_service = AaveDcaPipelinePreflightService(self.aave_executor)
        self.recovery_service = AaveDcaPipelineRecoveryService(database_session, self.dca_order_dao)
        self.pipeline_service = AaveDcaPipelineService(
            database_session=database_session,
            dca_order_dao=self.dca_order_dao,
            dca_strategy_dao=self.dca_strategy_dao,
            aave_executor=self.aave_executor,
            preflight_service=self.preflight_service,
            recovery_service=self.recovery_service,
        )
        self.scheduling_service = AaveDcaOrderSchedulingService(
            database_session=database_session,
            dca_order_dao=self.dca_order_dao,
            dca_strategy_dao=self.dca_strategy_dao,
            aave_executor=self.aave_executor,
            pipeline_service=self.pipeline_service,
        )

    async def process_scheduled_dca_order(self, dca_order: AaveDcaOrder, dca_strategy: AaveDcaStrategy) -> None:
        await self.scheduling_service.process_scheduled_dca_order(dca_order, dca_strategy)
