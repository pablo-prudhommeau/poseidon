from __future__ import annotations

from aave_dca_test_helpers import build_aave_dca_database_session, build_aave_dca_order, build_aave_dca_strategy
from src.core.aavedca.aave_dca_structures import AaveDcaOrderStatus, AaveDcaStrategyStatus
from src.persistence.dao.aave_dca_order_dao import AaveDcaOrderDao
from src.persistence.models import AaveDcaOrder


def test_count_remaining_by_strategy_ignores_finished_orders_and_other_strategies() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = build_aave_dca_strategy(AaveDcaStrategyStatus.ACTIVE, "avalanche")
    other_strategy = build_aave_dca_strategy(AaveDcaStrategyStatus.PAUSED, "avalanche")
    database_session.add_all([dca_strategy, other_strategy])
    database_session.flush()
    for order_status in AaveDcaOrderStatus:
        database_session.add(build_aave_dca_order(dca_strategy.id, order_status, None))
    database_session.add(build_aave_dca_order(other_strategy.id, AaveDcaOrderStatus.PENDING, None))
    database_session.flush()

    assert AaveDcaOrderDao(database_session).count_remaining_by_strategy(dca_strategy.id) == 5


def test_retrieve_in_flight_by_strategy_returns_only_the_orders_being_executed() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = build_aave_dca_strategy(AaveDcaStrategyStatus.ACTIVE, "avalanche")
    database_session.add(dca_strategy)
    database_session.flush()
    for order_status in AaveDcaOrderStatus:
        database_session.add(build_aave_dca_order(dca_strategy.id, order_status, None))
    database_session.flush()

    in_flight_orders: list[AaveDcaOrder] = AaveDcaOrderDao(database_session).retrieve_in_flight_by_strategy(dca_strategy.id)

    assert [in_flight_order.order_status for in_flight_order in in_flight_orders] == [
        AaveDcaOrderStatus.AWAITING_WITHDRAW,
        AaveDcaOrderStatus.AWAITING_SWAP,
        AaveDcaOrderStatus.AWAITING_SUPPLY,
    ]
