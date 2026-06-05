from __future__ import annotations

from fastapi.encoders import jsonable_encoder

from src.api.http.api_schemas import (
    TradingShadowingVerdictChroniclePayload,
)
from src.api.websocket.websocket_manager import websocket_manager
from src.api.websocket.websocket_structures import WebsocketMessageType
from src.cache.cache_invalidator import cache_invalidator
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
        shadowing_regime_payload = build_shadowing_regime_payload(payload)
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.TRADING_SHADOWING_REGIME.value,
            "payload": jsonable_encoder(shadowing_regime_payload),
        })


class _TradingShadowingVerdictChronicleRebuilder:
    realm = CacheRealm.SHADOWING_VERDICT_CHRONICLE
    ttl_seconds = 120.0

    def rebuild(self) -> TradingShadowingVerdictChroniclePayload:
        result = compute_trading_shadowing_verdict_chronicle()
        return build_trading_shadowing_verdict_chronicle_payload(result.chronicle)

    def apply_to_cache(self, payload: TradingShadowingVerdictChroniclePayload) -> None:
        trading_shadowing_cache.update_shadowing_verdict_chronicle(payload)

    async def notify_websocket(self, payload: TradingShadowingVerdictChroniclePayload) -> None:
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.TRADING_SHADOWING_VERDICT_CHRONICLE.value,
            "payload": jsonable_encoder(payload),
        })


def register_trading_shadowing_rebuilders() -> None:
    cache_invalidator.register(_ShadowSnapshotRebuilder())
    cache_invalidator.register(_TradingShadowingVerdictChronicleRebuilder())
    logger.info("[TRADING][SHADOWING][CACHE][REBUILDERS] %d trading rebuilders registered", len(cache_invalidator._rebuilders))
