from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.core.aavedca.aave_dca_structures import (
    AaveDcaActiveStrategyConflictError,
    AaveDcaStrategyNotFoundError,
    AaveDcaStrategyStatus,
    AaveDcaStrategyStatusChange,
    AaveDcaStrategyStatusTransitionError,
)
from src.core.aavedca.aave_dca_utils import is_aave_dca_strategy_status_transition_allowed
from src.core.structures.structures import BlockchainNetwork
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.models import AaveDcaOrder, AaveDcaStrategy

logger = get_application_logger(__name__)


def ensure_no_other_active_aave_dca_strategy(
        strategy_dao: AaveDcaStrategyDao,
        blockchain_network: BlockchainNetwork,
        excluded_strategy_id: Optional[int],
) -> None:
    for active_strategy in strategy_dao.retrieve_active_by_blockchain_network(blockchain_network):
        if active_strategy.id == excluded_strategy_id:
            continue
        logger.info(
            "[AAVEDCA][STRATEGY][GUARD] Strategy activation refused — strategy_id=%s is already active on blockchain_network=%s",
            active_strategy.id,
            blockchain_network.value,
        )
        raise AaveDcaActiveStrategyConflictError(
            f"DCA strategy {active_strategy.id} is already active on {blockchain_network.value}"
        )
    logger.debug("[AAVEDCA][STRATEGY][GUARD] No other active strategy on blockchain_network=%s", blockchain_network.value)


def update_aave_dca_strategy_status(
        database_session: Session,
        strategy_id: int,
        requested_status: AaveDcaStrategyStatus,
) -> AaveDcaStrategyStatusChange:
    strategy_dao = AaveDcaStrategyDao(database_session)
    order_dao = AaveDcaOrderDao(database_session)

    dca_strategy: Optional[AaveDcaStrategy] = strategy_dao.retrieve_by_id(strategy_id)
    if dca_strategy is None:
        raise AaveDcaStrategyNotFoundError(f"DCA strategy {strategy_id} not found")

    previous_status: AaveDcaStrategyStatus = dca_strategy.strategy_status
    if not is_aave_dca_strategy_status_transition_allowed(previous_status, requested_status):
        raise AaveDcaStrategyStatusTransitionError(
            f"DCA strategy {strategy_id} cannot move from {previous_status.value} to {requested_status.value}"
        )

    in_flight_orders: list[AaveDcaOrder] = order_dao.retrieve_in_flight_by_strategy(strategy_id)
    suspended_in_flight_order_count: int = len(
        [in_flight_order for in_flight_order in in_flight_orders if in_flight_order.suspension_reason is not None]
    )
    if requested_status == AaveDcaStrategyStatus.ACTIVE:
        ensure_no_other_active_aave_dca_strategy(
            strategy_dao=strategy_dao,
            blockchain_network=BlockchainNetwork(dca_strategy.blockchain_network.lower()),
            excluded_strategy_id=strategy_id,
        )
    elif suspended_in_flight_order_count < len(in_flight_orders):
        raise AaveDcaStrategyStatusTransitionError(
            f"DCA strategy {strategy_id} has {len(in_flight_orders) - suspended_in_flight_order_count} order(s) being executed"
        )

    dca_strategy.strategy_status = requested_status
    dca_strategy.updated_at = get_current_local_datetime()
    strategy_dao.save(dca_strategy)

    logger.info(
        "[AAVEDCA][STRATEGY][STATUS] Strategy %s moved from %s to %s with %d suspended in-flight order(s)",
        strategy_id,
        previous_status.value,
        requested_status.value,
        suspended_in_flight_order_count,
    )
    return AaveDcaStrategyStatusChange(
        strategy_id=strategy_id,
        previous_status=previous_status,
        status=requested_status,
        suspended_in_flight_order_count=suspended_in_flight_order_count,
    )
