from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from aave_dca_test_helpers import build_aave_dca_database_session, build_aave_dca_order, build_aave_dca_strategy
from src.core.aavedca.aave_dca_strategy_status_service import (
    ensure_no_other_active_aave_dca_strategy,
    update_aave_dca_strategy_status,
)
from src.core.aavedca.aave_dca_structures import (
    AaveDcaActiveStrategyConflictError,
    AaveDcaOrderStatus,
    AaveDcaStrategyNotFoundError,
    AaveDcaStrategyStatus,
    AaveDcaStrategyStatusChange,
    AaveDcaStrategyStatusTransitionError,
)
from src.core.structures.structures import BlockchainNetwork
from src.persistence.dao.aave_dca_strategy_dao import AaveDcaStrategyDao
from src.persistence.models import AaveDcaStrategy


def _persist_strategy(database_session: Session, strategy_status: AaveDcaStrategyStatus, blockchain_network: str) -> AaveDcaStrategy:
    dca_strategy = build_aave_dca_strategy(strategy_status, blockchain_network)
    database_session.add(dca_strategy)
    database_session.flush()
    return dca_strategy


def test_update_aave_dca_strategy_status_pauses_an_active_strategy() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE, "avalanche")
    database_session.add(build_aave_dca_order(dca_strategy.id, AaveDcaOrderStatus.PENDING, None))
    database_session.add(build_aave_dca_order(dca_strategy.id, AaveDcaOrderStatus.EXECUTED, None))
    database_session.flush()

    strategy_status_change: AaveDcaStrategyStatusChange = update_aave_dca_strategy_status(
        database_session,
        dca_strategy.id,
        AaveDcaStrategyStatus.PAUSED,
    )

    assert strategy_status_change == AaveDcaStrategyStatusChange(
        strategy_id=dca_strategy.id,
        previous_status=AaveDcaStrategyStatus.ACTIVE,
        status=AaveDcaStrategyStatus.PAUSED,
        suspended_in_flight_order_count=0,
    )
    assert dca_strategy.strategy_status == AaveDcaStrategyStatus.PAUSED


def test_update_aave_dca_strategy_status_never_leaves_a_cancelled_strategy() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.CANCELLED, "avalanche")

    with pytest.raises(AaveDcaStrategyStatusTransitionError):
        update_aave_dca_strategy_status(database_session, dca_strategy.id, AaveDcaStrategyStatus.ACTIVE)


def test_update_aave_dca_strategy_status_reports_an_unknown_strategy() -> None:
    with pytest.raises(AaveDcaStrategyNotFoundError):
        update_aave_dca_strategy_status(build_aave_dca_database_session(), 999, AaveDcaStrategyStatus.PAUSED)


def test_update_aave_dca_strategy_status_refuses_to_stop_an_order_being_executed() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE, "avalanche")
    database_session.add(build_aave_dca_order(dca_strategy.id, AaveDcaOrderStatus.AWAITING_SWAP, None))
    database_session.flush()

    with pytest.raises(AaveDcaStrategyStatusTransitionError, match="being executed"):
        update_aave_dca_strategy_status(database_session, dca_strategy.id, AaveDcaStrategyStatus.CANCELLED)

    assert dca_strategy.strategy_status == AaveDcaStrategyStatus.ACTIVE


def test_update_aave_dca_strategy_status_reports_suspended_orders_stopped_mid_execution() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE, "avalanche")
    database_session.add(build_aave_dca_order(dca_strategy.id, AaveDcaOrderStatus.AWAITING_SUPPLY, "ONCHAIN_EXECUTION_FAILED"))
    database_session.flush()

    strategy_status_change: AaveDcaStrategyStatusChange = update_aave_dca_strategy_status(
        database_session,
        dca_strategy.id,
        AaveDcaStrategyStatus.CANCELLED,
    )

    assert strategy_status_change.suspended_in_flight_order_count == 1
    assert dca_strategy.strategy_status == AaveDcaStrategyStatus.CANCELLED


def test_update_aave_dca_strategy_status_refuses_to_resume_while_another_strategy_is_active_on_the_blockchain() -> None:
    database_session = build_aave_dca_database_session()
    _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE, "avalanche")
    paused_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.PAUSED, "avalanche")

    with pytest.raises(AaveDcaActiveStrategyConflictError):
        update_aave_dca_strategy_status(database_session, paused_strategy.id, AaveDcaStrategyStatus.ACTIVE)


def test_update_aave_dca_strategy_status_resumes_when_the_active_strategy_is_on_another_blockchain() -> None:
    database_session = build_aave_dca_database_session()
    _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE, "base")
    paused_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.PAUSED, "avalanche")

    update_aave_dca_strategy_status(database_session, paused_strategy.id, AaveDcaStrategyStatus.ACTIVE)

    assert paused_strategy.strategy_status == AaveDcaStrategyStatus.ACTIVE


def test_ensure_no_other_active_aave_dca_strategy_refuses_a_second_active_strategy() -> None:
    database_session = build_aave_dca_database_session()
    _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE, "avalanche")

    with pytest.raises(AaveDcaActiveStrategyConflictError):
        ensure_no_other_active_aave_dca_strategy(AaveDcaStrategyDao(database_session), BlockchainNetwork.AVALANCHE, None)


def test_ensure_no_other_active_aave_dca_strategy_accepts_when_the_previous_strategy_is_cancelled() -> None:
    database_session = build_aave_dca_database_session()
    _persist_strategy(database_session, AaveDcaStrategyStatus.CANCELLED, "avalanche")

    ensure_no_other_active_aave_dca_strategy(AaveDcaStrategyDao(database_session), BlockchainNetwork.AVALANCHE, None)
