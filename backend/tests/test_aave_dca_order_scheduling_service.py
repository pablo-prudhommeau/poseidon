from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from aave_dca_test_helpers import build_aave_dca_order, build_aave_dca_strategy
from src.core.aavedca.aave_dca_order_scheduling_service import AaveDcaOrderSchedulingService
from src.core.aavedca.aave_dca_structures import AaveDcaOrderStatus, AaveDcaStrategyStatus


def _build_scheduling_service(aave_executor: MagicMock, dca_order_dao: MagicMock) -> AaveDcaOrderSchedulingService:
    return AaveDcaOrderSchedulingService(
        database_session=MagicMock(),
        dca_order_dao=dca_order_dao,
        dca_strategy_dao=MagicMock(),
        aave_executor=aave_executor,
        pipeline_service=MagicMock(),
    )


def _build_aave_executor() -> MagicMock:
    aave_executor = MagicMock()
    aave_executor.fetch_supply_apy = AsyncMock(return_value=0.03)
    aave_executor.verify_active_debt = AsyncMock(return_value=True)
    return aave_executor


def _run_scheduled_order(scheduling_service: AaveDcaOrderSchedulingService, is_paper_mode: bool, gas_alert: AsyncMock) -> None:
    dca_strategy = build_aave_dca_strategy(AaveDcaStrategyStatus.ACTIVE, "avalanche")
    dca_strategy.id = 5
    dca_order = build_aave_dca_order(5, AaveDcaOrderStatus.PENDING, None)
    with (
        patch("src.core.aavedca.aave_dca_order_scheduling_service.settings") as mock_settings,
        patch("src.core.aavedca.aave_dca_order_scheduling_service.alert_aave_dca_native_gas_shortfall", new=gas_alert),
        patch("src.core.aavedca.aave_dca_order_scheduling_service.send_alert"),
    ):
        mock_settings.AAVE_DCA_PAPER_MODE = is_paper_mode
        asyncio.run(scheduling_service.process_scheduled_dca_order(dca_order, dca_strategy))


def test_process_scheduled_dca_order_checks_the_gas_of_the_remaining_orders() -> None:
    aave_executor = _build_aave_executor()
    dca_order_dao = MagicMock()
    dca_order_dao.count_remaining_by_strategy.return_value = 12
    gas_alert = AsyncMock()

    _run_scheduled_order(_build_scheduling_service(aave_executor, dca_order_dao), is_paper_mode=False, gas_alert=gas_alert)

    dca_order_dao.count_remaining_by_strategy.assert_called_once_with(5)
    assert gas_alert.await_args.kwargs["remaining_order_count"] == 12


def test_process_scheduled_dca_order_never_checks_the_gas_in_paper_mode() -> None:
    gas_alert = AsyncMock()

    _run_scheduled_order(_build_scheduling_service(_build_aave_executor(), MagicMock()), is_paper_mode=True, gas_alert=gas_alert)

    gas_alert.assert_not_called()


def test_process_scheduled_dca_order_continues_when_the_gas_check_fails() -> None:
    aave_executor = _build_aave_executor()
    gas_alert = AsyncMock(side_effect=RuntimeError("rpc unavailable"))

    _run_scheduled_order(_build_scheduling_service(aave_executor, MagicMock()), is_paper_mode=False, gas_alert=gas_alert)

    aave_executor.verify_active_debt.assert_awaited_once()
