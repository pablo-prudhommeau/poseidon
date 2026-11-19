from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.aavedca.aave_dca_gas_reserve_service import (
    alert_aave_dca_native_gas_shortfall,
    ensure_aave_dca_native_gas_for_new_strategy,
)
from src.core.aavedca.aave_dca_structures import AaveDcaInsufficientNativeGasError
from src.core.structures.structures import BlockchainNetwork


def _build_aave_executor(wallet_balance_avax: float) -> MagicMock:
    aave_executor = MagicMock()
    aave_executor.fetch_max_fee_per_gas_wei = AsyncMock(return_value=15_000_000_000)
    aave_executor.fetch_native_gas_balance_avax = AsyncMock(return_value=wallet_balance_avax)
    return aave_executor


def test_ensure_aave_dca_native_gas_for_new_strategy_refuses_a_wallet_short_of_gas() -> None:
    with pytest.raises(AaveDcaInsufficientNativeGasError) as raised_error:
        asyncio.run(ensure_aave_dca_native_gas_for_new_strategy(_build_aave_executor(0.5), BlockchainNetwork.AVALANCHE, 20))

    assert raised_error.value.native_gas_requirement.missing_balance_avax == pytest.approx(0.132)


def test_ensure_aave_dca_native_gas_for_new_strategy_accepts_a_wallet_covering_the_gas() -> None:
    asyncio.run(ensure_aave_dca_native_gas_for_new_strategy(_build_aave_executor(1.0), BlockchainNetwork.AVALANCHE, 20))


def test_alert_aave_dca_native_gas_shortfall_alerts_once_a_day_per_strategy() -> None:
    dca_strategy = MagicMock(id=5, blockchain_network="avalanche")
    current_local_time: datetime = datetime.now().astimezone()

    with (
        patch.dict("src.core.aavedca.aave_dca_gas_reserve_service._last_gas_shortfall_alert_date_by_strategy_identifier", clear=True),
        patch("src.core.aavedca.aave_dca_gas_reserve_service.dispatch_aave_dca_native_gas_shortfall_alert") as mock_dispatch,
        patch("src.core.aavedca.aave_dca_gas_reserve_service.get_current_local_datetime") as mock_current_local_datetime,
    ):
        mock_current_local_datetime.return_value = current_local_time
        asyncio.run(alert_aave_dca_native_gas_shortfall(_build_aave_executor(0.1), dca_strategy, 20))
        asyncio.run(alert_aave_dca_native_gas_shortfall(_build_aave_executor(0.1), dca_strategy, 20))
        assert mock_dispatch.call_count == 1

        mock_current_local_datetime.return_value = current_local_time + timedelta(days=1)
        asyncio.run(alert_aave_dca_native_gas_shortfall(_build_aave_executor(0.1), dca_strategy, 20))
        assert mock_dispatch.call_count == 2


def test_alert_aave_dca_native_gas_shortfall_stays_silent_when_the_gas_is_sufficient() -> None:
    dca_strategy = MagicMock(id=5, blockchain_network="avalanche")

    with (
        patch.dict("src.core.aavedca.aave_dca_gas_reserve_service._last_gas_shortfall_alert_date_by_strategy_identifier", clear=True),
        patch("src.core.aavedca.aave_dca_gas_reserve_service.dispatch_aave_dca_native_gas_shortfall_alert") as mock_dispatch,
    ):
        asyncio.run(alert_aave_dca_native_gas_shortfall(_build_aave_executor(1.0), dca_strategy, 20))

    mock_dispatch.assert_not_called()
