from __future__ import annotations

import asyncio
from typing import Optional

from src.core.aavesentinel.aave_sentinel_capital_flow_service import AaveSentinelCapitalFlowService
from src.core.aavesentinel.aave_sentinel_helpers import create_empty_capital_flow_summary
from src.core.aavesentinel.aave_sentinel_snapshot_service import AaveSentinelSnapshotService
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelPositionSnapshot,
)
from src.core.aavesentinel.cache.aave_sentinel_cache import aave_sentinel_state_cache
from src.core.aavesentinel.cache.aave_sentinel_cache_structures import AaveSentinelState
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_snapshot_service: Optional[AaveSentinelSnapshotService] = None
_capital_flow_service: Optional[AaveSentinelCapitalFlowService] = None
_snapshot_service_lock = asyncio.Lock()
_capital_flow_service_lock = asyncio.Lock()


async def _ensure_snapshot_service() -> AaveSentinelSnapshotService:
    global _snapshot_service
    if _snapshot_service is not None and _snapshot_service.is_initialized:
        return _snapshot_service

    async with _snapshot_service_lock:
        if _snapshot_service is None:
            _snapshot_service = AaveSentinelSnapshotService()
        await _snapshot_service.initialize()
        return _snapshot_service


async def _ensure_capital_flow_service() -> AaveSentinelCapitalFlowService:
    global _capital_flow_service
    snapshot_service = await _ensure_snapshot_service()
    async with _capital_flow_service_lock:
        if _capital_flow_service is None:
            _capital_flow_service = AaveSentinelCapitalFlowService(
                wallet_address=snapshot_service.wallet_address,
            )
        return _capital_flow_service


async def build_aave_sentinel_position_payload() -> Optional[AaveSentinelPositionSnapshot]:
    snapshot_service = await _ensure_snapshot_service()
    return await snapshot_service.fetch_position_snapshot()


async def build_aave_sentinel_capital_flow_payload() -> AaveSentinelCapitalFlowSummary:
    capital_flow_service = await _ensure_capital_flow_service()
    if not capital_flow_service.wallet_address:
        return create_empty_capital_flow_summary()
    return await capital_flow_service.build_capital_flow_summary()


async def resolve_aave_sentinel_state_for_display() -> AaveSentinelState:
    sentinel_state = aave_sentinel_state_cache.get_aave_sentinel_state()

    if sentinel_state.position_snapshot is None:
        position_snapshot = await build_aave_sentinel_position_payload()
        aave_sentinel_state_cache.update_position_snapshot(position_snapshot=position_snapshot)
        sentinel_state = aave_sentinel_state_cache.get_aave_sentinel_state()

    if sentinel_state.capital_flow_summary is None or not sentinel_state.capital_flow_summary.is_available:
        capital_flow_summary = await build_aave_sentinel_capital_flow_payload()
        aave_sentinel_state_cache.update_capital_flow_summary(capital_flow_summary=capital_flow_summary)
        sentinel_state = aave_sentinel_state_cache.get_aave_sentinel_state()

    return sentinel_state


async def close_aave_sentinel_payload_builder_resources() -> None:
    global _snapshot_service, _capital_flow_service
    if _capital_flow_service is not None:
        await _capital_flow_service.close()
        _capital_flow_service = None
    _snapshot_service = None
