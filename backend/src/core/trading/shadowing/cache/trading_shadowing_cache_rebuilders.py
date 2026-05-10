from __future__ import annotations

from typing import Optional

from fastapi.encoders import jsonable_encoder

from src.api.http.api_schemas import (
    ShadowVerdictChroniclePayload,
    TradingShadowMetaPayload,
)
from src.api.websocket.websocket_manager import websocket_manager
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_protocols import CacheRealmRebuildSkipped
from src.cache.cache_realm import CacheRealm
from src.core.structures.structures import WebsocketMessageType
from src.core.trading.cache.trading_cache_payload_builders import (
    build_shadow_intelligence_snapshot,
)
from src.core.trading.shadowing.cache.trading_shadowing_cache import trading_shadowing_cache
from src.core.trading.shadowing.cache.trading_shadowing_cache_payload_builders import (
    build_trading_shadow_meta_payload,
    build_shadow_verdict_chronicle_payload,
)
from src.core.trading.shadowing.trading_shadowing_service import (
    compute_shadow_verdict_chronicle,
)
from src.core.trading.shadowing.trading_shadowing_structures import ShadowIntelligenceSnapshot
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingVerdictChronicleVerdict, TradingShadowingVerdictChronicle
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class _ShadowSnapshotRebuilder:
    realm = CacheRealm.SHADOW_INTELLIGENCE_SNAPSHOT
    ttl_seconds = 120.0

    def rebuild(self) -> ShadowIntelligenceSnapshot:
        return build_shadow_intelligence_snapshot()

    def apply_to_cache(self, payload: ShadowIntelligenceSnapshot) -> None:
        shadow_snapshot = payload
        trading_shadowing_cache.update_shadow_intelligence_snapshot(shadow_snapshot)

    async def notify_websocket(self, payload: ShadowIntelligenceSnapshot) -> None:
        return


class _ShadowMetaRebuilder:
    realm = CacheRealm.SHADOW_META
    ttl_seconds = 120.0

    def rebuild(self) -> TradingShadowMetaPayload:
        shadow_snapshot = trading_shadowing_cache.get_shadow_intelligence_snapshot()
        if shadow_snapshot is None:
            raise CacheRealmRebuildSkipped("Shadow meta cannot be rebuilt without shadow snapshot")
        return build_trading_shadow_meta_payload(shadow_snapshot)

    def apply_to_cache(self, payload: TradingShadowMetaPayload) -> None:
        shadow_meta_payload = payload
        trading_shadowing_cache.update_trading_shadow_meta_state(shadow_meta_payload)

    async def notify_websocket(self, payload: TradingShadowMetaPayload) -> None:
        shadow_meta_payload = payload
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.SHADOW_META.value,
            "payload": jsonable_encoder(shadow_meta_payload),
        })


class _ShadowVerdictChronicleRebuilder:
    realm = CacheRealm.SHADOW_VERDICT_CHRONICLE
    ttl_seconds = 120.0

    _has_broadcasted_once = False
    _cached_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []
    _previous_as_of_ms: int = 0

    _new_chronicle: Optional[TradingShadowingVerdictChronicle] = None
    _new_verdicts: list[TradingShadowingVerdictChronicleVerdict] = []

    def rebuild(self) -> ShadowVerdictChroniclePayload:
        result = compute_shadow_verdict_chronicle()

        # DELTA does not work with frontend for the moment
        # if not self.__class__._cached_verdicts:
        #    result = compute_shadow_verdict_chronicle()
        # else:
        #    result = compute_shadow_verdict_chronicle_incremental(self.__class__._cached_verdicts)

        max_cached_id = max((verdict.id for verdict in self.__class__._cached_verdicts), default=0)
        self.__class__._new_chronicle = result.chronicle
        self.__class__._new_verdicts = [verdict for verdict in result.verdicts if verdict.id > max_cached_id]
        self.__class__._cached_verdicts = result.verdicts

        return build_shadow_verdict_chronicle_payload(result.chronicle)

    def apply_to_cache(self, payload: ShadowVerdictChroniclePayload) -> None:
        response = payload
        trading_shadowing_cache.update_shadow_verdict_chronicle(response)

    async def notify_websocket(self, payload: ShadowVerdictChroniclePayload) -> None:
        response = payload
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.SHADOW_VERDICT_CHRONICLE.value,
            "payload": jsonable_encoder(response),
        })

        # DELTA does not work with frontend for the moment
        # if not self.__class__._has_broadcasted_once:
        #    await websocket_manager.broadcast_json_payload({
        #        "type": WebsocketMessageType.SHADOW_VERDICT_CHRONICLE.value,
        #        "payload": jsonable_encoder(response),
        #    })
        #    self.__class__._has_broadcasted_once = True
        #    self.__class__._previous_as_of_ms = int(self.__class__._new_chronicle.as_of.timestamp() * 1000)
        # else:
        #    delta_payload = build_shadow_verdict_chronicle_incremental_delta_payload(
        #        new_chronicle=self.__class__._new_chronicle,
        #        new_verdicts=self.__class__._new_verdicts,
        #        previous_as_of_ms=self.__class__._previous_as_of_ms,
        #        generated_at_iso=response.generated_at_iso,
        #        as_of_iso=response.as_of_iso,
        #        from_iso=response.from_iso,
        #        to_iso=response.to_iso,
        #    )
        #
        #    self.__class__._previous_as_of_ms = int(self.__class__._new_chronicle.as_of.timestamp() * 1000)
        #
        #    await websocket_manager.broadcast_json_payload({
        #        "type": WebsocketMessageType.SHADOW_VERDICT_CHRONICLE_DELTA.value,
        #        "payload": jsonable_encoder(delta_payload),
        #    })


def register_trading_shadowing_rebuilders() -> None:
    cache_invalidator.register(_ShadowSnapshotRebuilder())
    cache_invalidator.register(_ShadowMetaRebuilder())
    cache_invalidator.register(_ShadowVerdictChronicleRebuilder())
    logger.info("[TRADING][SHADOWING][CACHE][REBUILDERS] %d trading rebuilders registered", len(cache_invalidator._rebuilders))
