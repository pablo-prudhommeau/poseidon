from __future__ import annotations

import asyncio
from typing import Optional

from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelCapitalFlowValuationMemo,
    AaveSentinelPerformanceSummary,
    AaveSentinelPositionSnapshot,
    AaveSentinelUniversalLedger,
)
from src.core.aavesentinel.cache.aave_sentinel_cache import aave_sentinel_state_cache
from src.core.aavesentinel.cache.aave_sentinel_cache_structures import AaveSentinelState
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_helpers import create_empty_capital_flow_summary
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_ledger_helpers import (
    build_universal_ledger,
)
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_service import AaveSentinelCapitalFlowService
from src.core.aavesentinel.capitalflow.aave_sentinel_capital_flow_valuation_memo_helpers import (
    create_empty_capital_flow_valuation_memo,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_checkpoint_helpers import (
    create_empty_performance_summary,
)
from src.core.aavesentinel.performance.aave_sentinel_performance_service import AaveSentinelPerformanceService
from src.core.aavesentinel.position.aave_sentinel_position_snapshot_service import AaveSentinelSnapshotService
from src.integrations.aave.aave_protocol_reader import AaveProtocolReader
from src.integrations.routescan.routescan_client import RoutescanClient
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_snapshot_service: Optional[AaveSentinelSnapshotService] = None
_capital_flow_service: Optional[AaveSentinelCapitalFlowService] = None
_performance_service: Optional[AaveSentinelPerformanceService] = None
_shared_valuation_memo: Optional[AaveSentinelCapitalFlowValuationMemo] = None
_shared_aave_protocol_reader: Optional[AaveProtocolReader] = None
_shared_universal_ledger: Optional[AaveSentinelUniversalLedger] = None
_shared_universal_ledger_wallet_address: Optional[str] = None
_snapshot_service_lock = asyncio.Lock()
_capital_flow_service_lock = asyncio.Lock()
_performance_service_lock = asyncio.Lock()
_shared_resources_lock = asyncio.Lock()


def _ensure_shared_valuation_memo() -> AaveSentinelCapitalFlowValuationMemo:
    global _shared_valuation_memo
    if _shared_valuation_memo is None:
        _shared_valuation_memo = create_empty_capital_flow_valuation_memo()
    return _shared_valuation_memo


def _ensure_shared_aave_protocol_reader() -> AaveProtocolReader:
    global _shared_aave_protocol_reader
    if _shared_aave_protocol_reader is None:
        _shared_aave_protocol_reader = AaveProtocolReader()
    return _shared_aave_protocol_reader


def clear_shared_universal_ledger_cache() -> None:
    global _shared_universal_ledger, _shared_universal_ledger_wallet_address
    _shared_universal_ledger = None
    _shared_universal_ledger_wallet_address = None


async def _resolve_shared_universal_ledger(wallet_address: str) -> AaveSentinelUniversalLedger:
    global _shared_universal_ledger, _shared_universal_ledger_wallet_address
    normalized_wallet_address = wallet_address.lower()
    async with _shared_resources_lock:
        if (
                _shared_universal_ledger is not None
                and _shared_universal_ledger_wallet_address == normalized_wallet_address
        ):
            return _shared_universal_ledger

        routescan_client = RoutescanClient(wallet_address=normalized_wallet_address)
        try:
            normal_transactions = await routescan_client.fetch_all_normal_transactions()
            internal_transactions = await routescan_client.fetch_all_internal_transactions()
            token_transactions = await routescan_client.fetch_all_token_transactions()
            universal_ledger = build_universal_ledger(
                wallet_address=normalized_wallet_address,
                normal_transactions=normal_transactions,
                internal_transactions=internal_transactions,
                token_transactions=token_transactions,
            )
        finally:
            await routescan_client.close()

        _shared_universal_ledger = universal_ledger
        _shared_universal_ledger_wallet_address = normalized_wallet_address
        logger.debug(
            "[AAVESENTINEL][CACHE] Shared universal ledger resolved wallet=%s entry_count=%d",
            normalized_wallet_address,
            len(universal_ledger.entries),
        )
        return universal_ledger


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
                valuation_memo=_ensure_shared_valuation_memo(),
                aave_protocol_reader=_ensure_shared_aave_protocol_reader(),
            )
        return _capital_flow_service


async def _ensure_performance_service() -> AaveSentinelPerformanceService:
    global _performance_service
    snapshot_service = await _ensure_snapshot_service()
    async with _performance_service_lock:
        if _performance_service is None:
            _performance_service = AaveSentinelPerformanceService(
                wallet_address=snapshot_service.wallet_address,
                valuation_memo=_ensure_shared_valuation_memo(),
                aave_protocol_reader=_ensure_shared_aave_protocol_reader(),
            )
        return _performance_service


async def build_aave_sentinel_position_payload() -> Optional[AaveSentinelPositionSnapshot]:
    snapshot_service = await _ensure_snapshot_service()
    return await snapshot_service.fetch_position_snapshot()


async def build_aave_sentinel_capital_flow_payload() -> AaveSentinelCapitalFlowSummary:
    capital_flow_service = await _ensure_capital_flow_service()
    if not capital_flow_service.wallet_address:
        return create_empty_capital_flow_summary()
    universal_ledger = await _resolve_shared_universal_ledger(
        wallet_address=capital_flow_service.wallet_address,
    )
    return await capital_flow_service.build_capital_flow_summary(
        universal_ledger=universal_ledger,
    )


async def build_aave_sentinel_performance_payload() -> AaveSentinelPerformanceSummary:
    performance_service = await _ensure_performance_service()
    if not performance_service.wallet_address:
        return create_empty_performance_summary()

    sentinel_state = aave_sentinel_state_cache.get_aave_sentinel_state()
    capital_flow_summary = sentinel_state.capital_flow_summary
    if capital_flow_summary is None or not capital_flow_summary.is_available:
        capital_flow_summary = await build_aave_sentinel_capital_flow_payload()
        aave_sentinel_state_cache.update_capital_flow_summary(capital_flow_summary=capital_flow_summary)

    position_snapshot = sentinel_state.position_snapshot
    if position_snapshot is None:
        position_snapshot = await build_aave_sentinel_position_payload()
        aave_sentinel_state_cache.update_position_snapshot(position_snapshot=position_snapshot)

    universal_ledger = await _resolve_shared_universal_ledger(
        wallet_address=performance_service.wallet_address,
    )
    return await performance_service.build_performance_summary(
        capital_flow_summary=capital_flow_summary,
        position_snapshot=position_snapshot,
        universal_ledger=universal_ledger,
    )


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

    if sentinel_state.performance_summary is None or not sentinel_state.performance_summary.is_available:
        performance_summary = await build_aave_sentinel_performance_payload()
        aave_sentinel_state_cache.update_performance_summary(performance_summary=performance_summary)
        sentinel_state = aave_sentinel_state_cache.get_aave_sentinel_state()

    return sentinel_state


async def close_aave_sentinel_payload_builder_resources() -> None:
    global _snapshot_service, _capital_flow_service, _performance_service
    global _shared_valuation_memo, _shared_aave_protocol_reader
    if _performance_service is not None:
        await _performance_service.close()
        _performance_service = None
    if _capital_flow_service is not None:
        await _capital_flow_service.close()
        _capital_flow_service = None
    if _shared_aave_protocol_reader is not None:
        await _shared_aave_protocol_reader.close()
        _shared_aave_protocol_reader = None
    _shared_valuation_memo = None
    clear_shared_universal_ledger_cache()
    _snapshot_service = None
