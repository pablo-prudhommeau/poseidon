from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from aave_dca_test_helpers import USDC_ADDRESS
from src.core.aavedca.aave_dca_pipeline_preflight_service import AaveDcaPipelinePreflightService
from src.core.aavedca.aave_dca_structures import (
    AaveDcaOrderStatus,
    AaveDcaPipelinePreflightFailureReason,
    AaveDcaPipelinePreflightResult,
)
from src.core.structures.structures import BlockchainNetwork


def _build_aave_executor(aave_supply_balance: float) -> MagicMock:
    aave_executor = MagicMock()
    aave_executor.fetch_native_gas_balance_avax = AsyncMock(return_value=1.0)
    aave_executor.fetch_token_balance = AsyncMock(return_value=aave_supply_balance)
    return aave_executor


def test_run_live_pipeline_preflight_checks_refuses_a_withdrawal_above_the_aave_balance() -> None:
    aave_executor = _build_aave_executor(aave_supply_balance=10.0)
    preflight_service = AaveDcaPipelinePreflightService(aave_executor)

    preflight_result: AaveDcaPipelinePreflightResult = asyncio.run(
        preflight_service.run_live_pipeline_preflight_checks(
            blockchain=BlockchainNetwork.AVALANCHE,
            order_status=AaveDcaOrderStatus.AWAITING_WITHDRAW,
            source_asset_address=USDC_ADDRESS,
            source_asset_decimals=6,
            required_execution_amount_base_units=50_000_000,
            minimum_native_gas_reserve_avax=0.05,
            has_pending_broadcast=False,
        )
    )

    assert preflight_result.failure_reason == AaveDcaPipelinePreflightFailureReason.INSUFFICIENT_AAVE_SUPPLY_BALANCE


def test_run_live_pipeline_preflight_checks_skips_balances_while_a_broadcast_is_pending() -> None:
    aave_executor = _build_aave_executor(aave_supply_balance=10.0)
    preflight_service = AaveDcaPipelinePreflightService(aave_executor)

    preflight_result: AaveDcaPipelinePreflightResult = asyncio.run(
        preflight_service.run_live_pipeline_preflight_checks(
            blockchain=BlockchainNetwork.AVALANCHE,
            order_status=AaveDcaOrderStatus.AWAITING_WITHDRAW,
            source_asset_address=USDC_ADDRESS,
            source_asset_decimals=6,
            required_execution_amount_base_units=50_000_000,
            minimum_native_gas_reserve_avax=0.05,
            has_pending_broadcast=True,
        )
    )

    assert preflight_result.is_successful
    aave_executor.fetch_token_balance.assert_not_called()
