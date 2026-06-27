from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from src.cache.cache_protocols import CacheRealmRebuildSkipped
from src.core.trading.cache.trading_cache_payload_builders import (
    build_trading_liquidity_payload,
    build_trading_portfolio_payload_with_snapshot_creation,
)
from src.persistence.database_session_manager import get_database_session


@contextmanager
def mock_database_session() -> Iterator[MagicMock]:
    database_session = MagicMock(spec=Session)
    database_session.expire_on_commit = False
    yield database_session


@patch("src.core.trading.cache.trading_cache_payload_builders.TradingPositionDao")
@patch("src.core.trading.cache.trading_cache_payload_builders.get_database_session")
@patch("src.core.trading.cache.trading_cache_payload_builders.has_any_closing_positions", return_value=True)
@patch("src.core.trading.cache.trading_cache_payload_builders.trading_cache")
def test_closing_position_skip_does_not_log_db_rollback(
        trading_cache_mock: MagicMock,
        has_any_closing_positions_mock: MagicMock,
        get_database_session_mock: MagicMock,
        trading_position_dao_class_mock: MagicMock,
        caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)

    trading_cache_mock.get_onchain_prices_by_pair_address.return_value = None
    trading_cache_mock.get_trading_state.return_value.portfolio = MagicMock()
    get_database_session_mock.side_effect = mock_database_session

    position_dao_instance = MagicMock()
    position_dao_instance.retrieve_open_positions.return_value = []
    trading_position_dao_class_mock.return_value = position_dao_instance

    with pytest.raises(CacheRealmRebuildSkipped):
        build_trading_portfolio_payload_with_snapshot_creation()

    database_rollback_log_records = [
        log_record
        for log_record in caplog.records
        if "[DATABASE][TRANSACTION][ROLLBACK]" in log_record.getMessage()
    ]
    assert database_rollback_log_records == []
    has_any_closing_positions_mock.assert_called()


@patch("src.core.trading.cache.trading_cache_payload_builders.settings")
@patch("src.core.trading.cache.trading_cache_payload_builders.fetch_stablecoin_balances_for_allowed_chains", return_value=[])
@patch("src.core.trading.cache.trading_cache_payload_builders.get_database_session")
@patch("src.core.trading.cache.trading_cache_payload_builders.has_any_closing_positions", return_value=True)
@patch("src.core.trading.cache.trading_cache_payload_builders.trading_cache")
def test_closing_position_liquidity_skip_does_not_log_db_rollback(
        trading_cache_mock: MagicMock,
        has_any_closing_positions_mock: MagicMock,
        get_database_session_mock: MagicMock,
        fetch_balances_mock: MagicMock,
        settings_mock: MagicMock,
        caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    settings_mock.TRADING_PAPER_MODE = False
    trading_cache_mock.get_trading_liquidity_state.return_value = MagicMock()
    get_database_session_mock.side_effect = mock_database_session

    with pytest.raises(CacheRealmRebuildSkipped):
        build_trading_liquidity_payload()

    database_rollback_log_records = [
        log_record
        for log_record in caplog.records
        if "[DATABASE][TRANSACTION][ROLLBACK]" in log_record.getMessage()
    ]
    assert database_rollback_log_records == []
    has_any_closing_positions_mock.assert_called()


@patch("src.core.trading.cache.trading_cache_payload_builders.settings")
@patch("src.core.trading.cache.trading_cache_payload_builders.fetch_stablecoin_balances_for_allowed_chains", return_value=[])
@patch("src.core.trading.cache.trading_cache_payload_builders.get_database_session")
@patch("src.core.trading.cache.trading_cache_payload_builders.has_any_closing_positions", return_value=True)
@patch("src.core.trading.cache.trading_cache_payload_builders.trading_cache")
def test_closing_position_liquidity_skip_on_cold_cache_raises_rebuild_skipped(
        trading_cache_mock: MagicMock,
        has_any_closing_positions_mock: MagicMock,
        get_database_session_mock: MagicMock,
        fetch_balances_mock: MagicMock,
        settings_mock: MagicMock,
) -> None:
    settings_mock.TRADING_PAPER_MODE = False
    trading_cache_mock.get_trading_liquidity_state.return_value = None
    get_database_session_mock.side_effect = mock_database_session

    with pytest.raises(CacheRealmRebuildSkipped, match="deferring liquidity rebuild"):
        build_trading_liquidity_payload()


@patch("src.persistence.database_session_manager.DatabaseSessionLocal")
def test_get_database_session_does_not_log_error_on_cache_rebuild_skipped(
        database_session_local_mock: MagicMock,
        caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    database_session = MagicMock()
    database_session_local_mock.return_value = database_session

    with pytest.raises(CacheRealmRebuildSkipped):
        with get_database_session():
            raise CacheRealmRebuildSkipped("test skip")

    database_session.rollback.assert_called_once()
    database_session.commit.assert_not_called()
    database_rollback_error_records = [
        log_record
        for log_record in caplog.records
        if "[DATABASE][TRANSACTION][ROLLBACK]" in log_record.getMessage()
    ]
    assert database_rollback_error_records == []
