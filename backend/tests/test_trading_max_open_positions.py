from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.core.trading.trading_service import (
    POSITION_PHASES_CONSUMING_MAX_OPEN_SLOT,
    count_positions_consuming_max_open_slots,
)
from src.persistence.models import PositionPhase


def test_position_phases_consuming_max_open_slot_include_closing_and_staled() -> None:
    assert PositionPhase.OPEN in POSITION_PHASES_CONSUMING_MAX_OPEN_SLOT
    assert PositionPhase.PARTIAL in POSITION_PHASES_CONSUMING_MAX_OPEN_SLOT
    assert PositionPhase.CLOSING in POSITION_PHASES_CONSUMING_MAX_OPEN_SLOT
    assert PositionPhase.STALED in POSITION_PHASES_CONSUMING_MAX_OPEN_SLOT
    assert PositionPhase.CLOSED not in POSITION_PHASES_CONSUMING_MAX_OPEN_SLOT


def test_count_positions_consuming_max_open_slots_returns_scalar_count() -> None:
    database_session = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = 2
    database_session.execute.return_value = scalar_result

    occupied_slot_count = count_positions_consuming_max_open_slots(database_session)

    assert occupied_slot_count == 2
    database_session.execute.assert_called_once()


def test_count_positions_consuming_max_open_slots_defaults_to_zero_when_scalar_is_none() -> None:
    database_session = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    database_session.execute.return_value = scalar_result

    occupied_slot_count = count_positions_consuming_max_open_slots(database_session)

    assert occupied_slot_count == 0
