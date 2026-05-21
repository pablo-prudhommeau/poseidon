from __future__ import annotations

from fastapi.encoders import jsonable_encoder

from src.api.http.api_schemas import (
    TradingShadowingVerdictChroniclePayload,
    TradingShadowingRegimePayload,
)
from src.api.websocket.websocket_manager import websocket_manager
from src.api.websocket.websocket_structures import WebsocketMessageType
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_protocols import CacheRealmRebuildSkipped
from src.cache.cache_realm import CacheRealm
from src.core.trading.cache.trading_cache_payload_builders import (
    build_shadowing_snapshot,
)
from src.core.trading.shadowing.cache.trading_shadowing_cache import trading_shadowing_cache
from src.core.trading.shadowing.cache.trading_shadowing_cache_payload_builders import (
    build_shadowing_regime_payload,
    build_trading_shadowing_verdict_chronicle_payload,
)
from src.core.trading.shadowing.trading_shadowing_service import (
    compute_trading_shadowing_verdict_chronicle,
)
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingSnapshot
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class _ShadowSnapshotRebuilder:
    realm = CacheRealm.SHADOWING_SNAPSHOT
    ttl_seconds = 120.0

    def rebuild(self) -> TradingShadowingSnapshot:
        return build_shadowing_snapshot()

    def apply_to_cache(self, payload: TradingShadowingSnapshot) -> None:
        shadowing_regime_payload = build_shadowing_regime_payload(payload)
        trading_shadowing_cache.update_shadowing_snapshot(payload, shadowing_regime_payload)

    async def notify_websocket(self, payload: TradingShadowingSnapshot) -> None:
        return


class _ShadowingRegimeRebuilder:
    realm = CacheRealm.SHADOWING_REGIME
    ttl_seconds = 120.0

    def rebuild(self) -> TradingShadowingRegimePayload:
        shadow_snapshot = trading_shadowing_cache.get_shadowing_snapshot()
        if shadow_snapshot is None:
            raise CacheRealmRebuildSkipped("Shadowing regime cannot be rebuilt without shadow snapshot")
        return build_shadowing_regime_payload(shadow_snapshot)

    def apply_to_cache(self, payload: TradingShadowingRegimePayload) -> None:
        shadowing_regime_payload = payload
        trading_shadowing_cache.update_trading_shadowing_regime_state(shadowing_regime_payload)

    async def notify_websocket(self, payload: TradingShadowingRegimePayload) -> None:
        shadowing_regime_payload = payload
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.TRADING_SHADOWING_REGIME.value,
            "payload": jsonable_encoder(shadowing_regime_payload),
        })


class _TradingShadowingVerdictChronicleRebuilder:
    realm = CacheRealm.SHADOWING_VERDICT_CHRONICLE
    ttl_seconds = 120.0

    def rebuild(self) -> TradingShadowingVerdictChroniclePayload:
        result = compute_trading_shadowing_verdict_chronicle()

        # DELTA does not work with frontend for the moment
        # if not self.__class__._cached_verdicts:
        #    result = compute_trading_shadowing_verdict_chronicle()
        # else:
        #    result = compute_trading_shadowing_verdict_chronicle_incremental(self.__class__._cached_verdicts)

        # Full recomputation is used, and we intentionally avoid retaining previous
        # verdict lists in memory at class level while delta mode is disabled.

        return build_trading_shadowing_verdict_chronicle_payload(result.chronicle)

    def apply_to_cache(self, payload: TradingShadowingVerdictChroniclePayload) -> None:
        response = payload
        trading_shadowing_cache.update_shadowing_verdict_chronicle(response)

    async def notify_websocket(self, payload: TradingShadowingVerdictChroniclePayload) -> None:
        response = payload
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.TRADING_SHADOWING_VERDICT_CHRONICLE.value,
            "payload": jsonable_encoder(response),
        })

        # DELTA does not work with frontend for the moment
        # if not self.__class__._has_broadcasted_once:
        #    await websocket_manager.broadcast_json_payload({
        #        "type": WebsocketMessageType.TRADING_SHADOWING_VERDICT_CHRONICLE.value,
        #        "payload": jsonable_encoder(response),
        #    })
        #    self.__class__._has_broadcasted_once = True
        #    self.__class__._previous_as_of_ms = int(self.__class__._new_chronicle.as_of.timestamp() * 1000)
        # else:
        #    delta_payload = build_trading_shadowing_verdict_chronicle_incremental_delta_payload(
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
        #        "type": WebsocketMessageType.TRADING_SHADOWING_VERDICT_CHRONICLE_DELTA.value,
        #        "payload": jsonable_encoder(delta_payload),
        #    })


def register_trading_shadowing_rebuilders() -> None:
    cache_invalidator.register(_ShadowSnapshotRebuilder())
    cache_invalidator.register(_ShadowingRegimeRebuilder())
    cache_invalidator.register(_TradingShadowingVerdictChronicleRebuilder())
    logger.info("[TRADING][SHADOWING][CACHE][REBUILDERS] %d trading rebuilders registered", len(cache_invalidator._rebuilders))
