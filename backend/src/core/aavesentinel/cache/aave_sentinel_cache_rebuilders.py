from __future__ import annotations

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelCapitalFlowSummary,
    AaveSentinelPerformanceSummary,
    AaveSentinelPositionSnapshot,
)
from src.core.aavesentinel.cache.aave_sentinel_cache import aave_sentinel_state_cache
from src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders import (
    build_aave_sentinel_capital_flow_payload,
    build_aave_sentinel_performance_payload,
    build_aave_sentinel_position_payload,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class _AaveSentinelPositionRebuilder:
    realm = CacheRealm.AAVE_SENTINEL_POSITION
    ttl_seconds = float(settings.AAVE_SENTINEL_POSITION_CACHE_TTL_SECONDS)

    async def rebuild_async(self) -> AaveSentinelPositionSnapshot | None:
        return await build_aave_sentinel_position_payload()

    def apply_to_cache(self, payload: AaveSentinelPositionSnapshot | None) -> None:
        aave_sentinel_state_cache.update_position_snapshot(position_snapshot=payload)

    async def notify_websocket(self, payload: object) -> None:
        return None


class _AaveSentinelCapitalFlowRebuilder:
    realm = CacheRealm.AAVE_SENTINEL_CAPITAL_FLOW
    ttl_seconds = float(settings.AAVE_SENTINEL_CAPITAL_FLOW_CACHE_TTL_SECONDS)

    async def rebuild_async(self) -> AaveSentinelCapitalFlowSummary:
        return await build_aave_sentinel_capital_flow_payload()

    def apply_to_cache(self, payload: AaveSentinelCapitalFlowSummary) -> None:
        aave_sentinel_state_cache.update_capital_flow_summary(capital_flow_summary=payload)

    async def notify_websocket(self, payload: object) -> None:
        return None


class _AaveSentinelPerformanceRebuilder:
    realm = CacheRealm.AAVE_SENTINEL_PERFORMANCE
    ttl_seconds = float(settings.AAVE_SENTINEL_PERFORMANCE_CACHE_TTL_SECONDS)

    async def rebuild_async(self) -> AaveSentinelPerformanceSummary:
        return await build_aave_sentinel_performance_payload()

    def apply_to_cache(self, payload: AaveSentinelPerformanceSummary) -> None:
        aave_sentinel_state_cache.update_performance_summary(performance_summary=payload)

    async def notify_websocket(self, payload: object) -> None:
        return None


def register_aave_sentinel_rebuilders() -> None:
    cache_invalidator.register(_AaveSentinelPositionRebuilder())
    cache_invalidator.register(_AaveSentinelCapitalFlowRebuilder())
    cache_invalidator.register(_AaveSentinelPerformanceRebuilder())
    logger.info("[AAVESENTINEL][CACHE][REBUILDERS] 3 sentinel rebuilders registered")
