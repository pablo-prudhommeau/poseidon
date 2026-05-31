from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.trading.execution.trading_execution_position_service import (
    PositionCloseConflictError,
    PositionCloseNotFoundError,
    close_position,
)
from src.persistence.models import PositionPhase, TradingPosition


def _build_open_position(position_id: int = 1) -> TradingPosition:
    return TradingPosition(
        id=position_id,
        evaluation_id=10,
        token_symbol="TEST",
        blockchain_network="solana",
        token_address="token-address",
        pair_address="pair-address",
        dex_id="raydium",
        open_quantity=100.0,
        current_quantity=100.0,
        entry_price=1.0,
        take_profit_tier_1_price=1.2,
        take_profit_tier_2_price=1.5,
        stop_loss_price=0.8,
        position_phase=PositionPhase.OPEN,
        opened_at=MagicMock(),
        updated_at=MagicMock(),
    )


def test_close_position_raises_not_found_when_missing() -> None:
    database_session = MagicMock()
    database_session.get.return_value = None

    with pytest.raises(PositionCloseNotFoundError):
        close_position(database_session, 99)


def test_close_position_raises_conflict_when_already_closing() -> None:
    database_session = MagicMock()
    position = _build_open_position()
    position.position_phase = PositionPhase.CLOSING
    database_session.get.return_value = position

    with pytest.raises(PositionCloseConflictError):
        close_position(database_session, position.id)


@patch("src.core.trading.execution.trading_execution_position_service.mark_position_closing")
@patch("src.core.trading.execution.trading_execution_position_service.cache_invalidator")
def test_close_position_marks_manual_closing(
        cache_invalidator_mock: MagicMock,
        mark_closing_mock: MagicMock,
) -> None:
    database_session = MagicMock()
    position = _build_open_position()
    database_session.get.return_value = position

    close_position(database_session, position.id)

    mark_closing_mock.assert_called_once()
    cache_invalidator_mock.mark_dirty.assert_called_once()


def test_close_trading_position_returns_204() -> None:
    application = create_app()
    database_session = MagicMock()
    position = _build_open_position()

    def _get_session_override():
        yield database_session

    database_session.get.return_value = position

    with patch("src.api.http.trading_http_api.get_fastapi_database_session", _get_session_override):
        with patch("src.api.http.trading_http_api.close_position") as close_position_mock:
            with patch("src.api.http.trading_http_api.execute_manual_close_sell"):
                application.dependency_overrides.clear()
                from src.persistence.database_session_manager import get_fastapi_database_session
                application.dependency_overrides[get_fastapi_database_session] = _get_session_override

                client = TestClient(application)
                response = client.post("/api/trading/positions/1/close")

    application.dependency_overrides.clear()
    assert response.status_code == 204
    close_position_mock.assert_called_once()


def test_close_trading_position_returns_409_when_conflict() -> None:
    application = create_app()

    def _get_session_override():
        yield MagicMock()

    with patch("src.api.http.trading_http_api.get_fastapi_database_session", _get_session_override):
        with patch(
            "src.api.http.trading_http_api.close_position",
            side_effect=PositionCloseConflictError("already closing"),
        ):
            application.dependency_overrides.clear()
            from src.persistence.database_session_manager import get_fastapi_database_session
            application.dependency_overrides[get_fastapi_database_session] = _get_session_override

            client = TestClient(application)
            response = client.post("/api/trading/positions/1/close")

    application.dependency_overrides.clear()
    assert response.status_code == 409
