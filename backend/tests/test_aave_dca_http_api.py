from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from aave_dca_test_helpers import BTCB_ADDRESS, USDC_ADDRESS, build_aave_dca_database_session, build_aave_dca_strategy
from src.api.app import create_app
from src.api.http.api_schemas import AaveDcaStrategyCreatePayload, AaveDcaStrategyStatusUpdatePayload
from src.api.http.http_helpers import create_aave_dca_strategy_from_payload
from src.core.aavedca.aave_dca_structures import (
    AaveDcaActiveStrategyConflictError,
    AaveDcaInsufficientNativeGasError,
    AaveDcaNativeGasRequirement,
    AaveDcaStrategyStatus,
)
from src.persistence.database_session_manager import get_fastapi_database_session
from src.persistence.models import AaveDcaStrategy


def _build_strategy_create_payload() -> AaveDcaStrategyCreatePayload:
    return AaveDcaStrategyCreatePayload(
        blockchain_network="avalanche",
        source_asset_symbol="USDC",
        source_asset_address=USDC_ADDRESS,
        source_asset_decimals=6,
        target_asset_symbol="BTC.b",
        target_asset_address=BTCB_ADDRESS,
        target_asset_decimals=8,
        binance_trading_pair="BTCUSDT",
        total_allocated_budget=100.0,
        total_planned_executions=28,
        strategy_start_date=datetime(2026, 11, 20).astimezone(),
        strategy_end_date=datetime(2026, 12, 4).astimezone(),
        slippage_tolerance=0.01,
        average_unit_price_elasticity_factor=10.0,
        bear_market_start_date=datetime(2022, 1, 1).astimezone(),
        bear_market_end_date=datetime(2022, 1, 15).astimezone(),
        current_cycle_index=5,
        previous_all_time_high_price=125000.0,
        previous_bull_market_amplitude_percentage=680.0,
        curve_flattening_factor=3.0,
        bear_market_bottom_multiplier=0.3,
        minimum_bull_market_multiplier=1.2,
        aave_estimated_annual_percentage_yield=0.05,
    )


def _send_status_update(database_session: Session, strategy_uid: int, strategy_status: str) -> Response:
    application = create_app()

    def _get_session_override() -> Iterator[Session]:
        yield database_session

    application.dependency_overrides[get_fastapi_database_session] = _get_session_override
    response: Response = TestClient(application).patch(
        f"/api/dca/strategies/{strategy_uid}/status",
        json={"strategy_status": strategy_status},
    )
    application.dependency_overrides.clear()
    return response


def _persist_strategy(database_session: Session, strategy_status: AaveDcaStrategyStatus) -> AaveDcaStrategy:
    dca_strategy = build_aave_dca_strategy(strategy_status, "avalanche")
    database_session.add(dca_strategy)
    database_session.flush()
    return dca_strategy


def test_update_aave_dca_strategy_status_route_returns_the_new_status() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE)

    response: Response = _send_status_update(database_session, dca_strategy.id, "PAUSED")

    assert response.status_code == 200
    assert response.json()["previous_strategy_status"] == "ACTIVE"
    assert response.json()["strategy_status"] == "PAUSED"


def test_update_aave_dca_strategy_status_route_returns_404_for_an_unknown_strategy() -> None:
    response: Response = _send_status_update(build_aave_dca_database_session(), 999, "PAUSED")

    assert response.status_code == 404


def test_update_aave_dca_strategy_status_route_returns_409_for_a_refused_transition() -> None:
    database_session = build_aave_dca_database_session()
    dca_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.COMPLETED)

    response: Response = _send_status_update(database_session, dca_strategy.id, "ACTIVE")

    assert response.status_code == 409


def test_update_aave_dca_strategy_status_route_returns_409_while_another_strategy_is_active() -> None:
    database_session = build_aave_dca_database_session()
    _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE)
    paused_strategy = _persist_strategy(database_session, AaveDcaStrategyStatus.PAUSED)

    response: Response = _send_status_update(database_session, paused_strategy.id, "ACTIVE")

    assert response.status_code == 409


def test_aave_dca_strategy_status_update_payload_rejects_an_unknown_status() -> None:
    with pytest.raises(ValidationError):
        AaveDcaStrategyStatusUpdatePayload.model_validate({"strategy_status": "DELETED"})


def test_create_new_aave_dca_strategy_route_returns_409_with_the_missing_gas() -> None:
    application = create_app()
    native_gas_requirement = AaveDcaNativeGasRequirement(
        order_count=28,
        gas_units_per_order=1_940_000,
        max_fee_per_gas_wei=15_000_000_000,
        estimated_gas_cost_avax=0.8148,
        minimum_reserve_avax=0.05,
        required_balance_avax=0.8648,
        wallet_balance_avax=0.5,
        missing_balance_avax=0.3648,
        is_sufficient=False,
    )

    with patch(
        "src.api.http.http_api.create_aave_dca_strategy_from_payload",
        new=AsyncMock(side_effect=AaveDcaInsufficientNativeGasError(native_gas_requirement)),
    ):
        response: Response = TestClient(application).post(
            "/api/dca/strategies",
            json=_build_strategy_create_payload().model_dump(mode="json"),
        )

    assert response.status_code == 409
    assert "add 0.3648 AVAX" in response.json()["detail"]


def test_create_aave_dca_strategy_from_payload_refuses_a_second_active_strategy() -> None:
    database_session = build_aave_dca_database_session()
    _persist_strategy(database_session, AaveDcaStrategyStatus.ACTIVE)

    with pytest.raises(AaveDcaActiveStrategyConflictError):
        asyncio.run(create_aave_dca_strategy_from_payload(database_session, _build_strategy_create_payload()))


def test_create_aave_dca_strategy_from_payload_checks_the_gas_in_live_mode_only() -> None:
    for is_paper_mode, expected_gas_check_count in ((True, 0), (False, 1)):
        with (
            patch("src.api.http.http_helpers.settings") as mock_settings,
            patch("src.api.http.http_helpers.ensure_aave_dca_native_gas_for_new_strategy", new=AsyncMock()) as mock_gas_check,
            patch("src.api.http.http_helpers.generate_comparative_snapshot", new=AsyncMock(side_effect=RuntimeError("backtest skipped"))),
        ):
            mock_settings.AAVE_DCA_PAPER_MODE = is_paper_mode
            with pytest.raises(RuntimeError, match="backtest skipped"):
                asyncio.run(create_aave_dca_strategy_from_payload(build_aave_dca_database_session(), _build_strategy_create_payload()))

        assert mock_gas_check.await_count == expected_gas_check_count
