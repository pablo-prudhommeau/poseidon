from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.aavesentinel.aave_sentinel_snapshot_service import AaveSentinelSnapshotService
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelPositionSnapshot,
    AaveSentinelTransactionHeadFingerprint,
)
from src.core.aavesentinel.cache.aave_sentinel_cache import aave_sentinel_state_cache
from src.core.aavesentinel.aave_sentinel_transaction_fingerprint_service import (
    poll_transaction_fingerprint_and_invalidate_capital_flow_if_changed,
)
from src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders import resolve_aave_sentinel_state_for_display
from src.core.aavesentinel.cache.aave_sentinel_cache_rebuilders import register_aave_sentinel_rebuilders


@pytest.fixture(autouse=True)
def reset_sentinel_cache_state() -> None:
    aave_sentinel_state_cache.update_position_snapshot(position_snapshot=None)
    aave_sentinel_state_cache.update_capital_flow_summary(
        capital_flow_summary=AaveSentinelCapitalFlowSummary(is_available=False),
    )
    aave_sentinel_state_cache.update_last_seen_transaction_fingerprint(
        transaction_fingerprint=AaveSentinelTransactionHeadFingerprint(
            latest_normal_transaction_hash="",
            latest_internal_transaction_hash="",
            latest_token_transaction_hash="",
        ),
    )


def test_snapshot_service_does_not_store_private_key() -> None:
    snapshot_service = AaveSentinelSnapshotService()

    assert not hasattr(snapshot_service, "_private_key")


def test_register_aave_sentinel_rebuilders_registers_two_realms() -> None:
    register_aave_sentinel_rebuilders()

    assert CacheRealm.AAVE_SENTINEL_POSITION in cache_invalidator._rebuilders
    assert CacheRealm.AAVE_SENTINEL_CAPITAL_FLOW in cache_invalidator._rebuilders


def test_transaction_fingerprint_change_marks_capital_flow_dirty() -> None:
    async def run_test() -> None:
        initial_fingerprint = AaveSentinelTransactionHeadFingerprint(
            latest_normal_transaction_hash="0xoldnormal",
            latest_internal_transaction_hash="0xoldinternal",
            latest_token_transaction_hash="0xoldtoken",
        )
        updated_fingerprint = AaveSentinelTransactionHeadFingerprint(
            latest_normal_transaction_hash="0xnewnormal",
            latest_internal_transaction_hash="0xoldinternal",
            latest_token_transaction_hash="0xoldtoken",
        )
        aave_sentinel_state_cache.update_last_seen_transaction_fingerprint(
            transaction_fingerprint=initial_fingerprint,
        )

        mock_snapshot_service = AsyncMock()
        mock_snapshot_service.wallet_address = "0x1111111111111111111111111111111111111111"

        with patch(
                "src.core.aavesentinel.aave_sentinel_transaction_fingerprint_service._ensure_snapshot_service",
                return_value=mock_snapshot_service,
        ), patch(
                "src.core.aavesentinel.aave_sentinel_transaction_fingerprint_service.fetch_transaction_head_fingerprint",
                return_value=updated_fingerprint,
        ), patch.object(cache_invalidator, "mark_dirty") as mark_dirty_mock:
            capital_flow_refresh_required = await poll_transaction_fingerprint_and_invalidate_capital_flow_if_changed()

        assert capital_flow_refresh_required is True
        mark_dirty_mock.assert_called_once_with(CacheRealm.AAVE_SENTINEL_CAPITAL_FLOW)

    asyncio.run(run_test())


def test_first_transaction_fingerprint_poll_seeds_without_marking_dirty() -> None:
    async def run_test() -> None:
        initial_fingerprint = AaveSentinelTransactionHeadFingerprint(
            latest_normal_transaction_hash="0xinitialnormal",
            latest_internal_transaction_hash="0xinitialinternal",
            latest_token_transaction_hash="0xinitialtoken",
        )
        mock_snapshot_service = AsyncMock()
        mock_snapshot_service.wallet_address = "0x1111111111111111111111111111111111111111"

        with patch(
                "src.core.aavesentinel.aave_sentinel_transaction_fingerprint_service._ensure_snapshot_service",
                return_value=mock_snapshot_service,
        ), patch(
                "src.core.aavesentinel.aave_sentinel_transaction_fingerprint_service.fetch_transaction_head_fingerprint",
                return_value=initial_fingerprint,
        ), patch.object(
                aave_sentinel_state_cache,
                "get_last_seen_transaction_fingerprint",
                return_value=None,
        ), patch.object(cache_invalidator, "mark_dirty") as mark_dirty_mock:
            capital_flow_refresh_required = await poll_transaction_fingerprint_and_invalidate_capital_flow_if_changed()

        assert capital_flow_refresh_required is False
        mark_dirty_mock.assert_not_called()
        assert (
                aave_sentinel_state_cache.get_last_seen_transaction_fingerprint()
                == initial_fingerprint
        )

    asyncio.run(run_test())


def test_five_snapshot_requests_trigger_single_position_rebuild_when_cache_empty() -> None:
    async def run_test() -> None:
        cached_position_snapshot = AaveSentinelPositionSnapshot(
            health_factor=1.5,
            total_collateral_usd=100.0,
            total_debt_usd=50.0,
        )
        cached_capital_flow_summary = AaveSentinelCapitalFlowSummary(
            net_capital_deployed_usd=80.0,
            is_available=True,
        )
        aave_sentinel_state_cache.update_capital_flow_summary(capital_flow_summary=cached_capital_flow_summary)

        build_position_mock = AsyncMock(return_value=cached_position_snapshot)
        build_capital_flow_mock = AsyncMock(return_value=cached_capital_flow_summary)

        with patch(
                "src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders.build_aave_sentinel_position_payload",
                build_position_mock,
        ), patch(
                "src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders.build_aave_sentinel_capital_flow_payload",
                build_capital_flow_mock,
        ):
            for _ in range(5):
                sentinel_state = await resolve_aave_sentinel_state_for_display()
                assert sentinel_state.position_snapshot is cached_position_snapshot

        build_position_mock.assert_called_once()
        build_capital_flow_mock.assert_not_called()

    asyncio.run(run_test())


def test_five_snapshot_requests_reuse_cached_position_when_available() -> None:
    async def run_test() -> None:
        cached_position_snapshot = AaveSentinelPositionSnapshot(
            health_factor=1.5,
            total_collateral_usd=100.0,
            total_debt_usd=50.0,
        )
        cached_capital_flow_summary = AaveSentinelCapitalFlowSummary(
            net_capital_deployed_usd=80.0,
            is_available=True,
        )
        aave_sentinel_state_cache.update_position_snapshot(position_snapshot=cached_position_snapshot)
        aave_sentinel_state_cache.update_capital_flow_summary(capital_flow_summary=cached_capital_flow_summary)

        build_position_mock = AsyncMock(return_value=cached_position_snapshot)
        build_capital_flow_mock = AsyncMock(return_value=cached_capital_flow_summary)

        with patch(
                "src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders.build_aave_sentinel_position_payload",
                build_position_mock,
        ), patch(
                "src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders.build_aave_sentinel_capital_flow_payload",
                build_capital_flow_mock,
        ):
            for _ in range(5):
                sentinel_state = await resolve_aave_sentinel_state_for_display()
                assert sentinel_state.position_snapshot is cached_position_snapshot

        build_position_mock.assert_not_called()
        build_capital_flow_mock.assert_not_called()

    asyncio.run(run_test())
