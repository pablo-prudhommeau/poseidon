from __future__ import annotations

from typing import cast

from fastapi.encoders import jsonable_encoder

from src.api.http.api_schemas import AaveDcaStrategyPayload
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.aavedca.cache.aave_dca_cache import aave_dca_state_cache
from src.core.aavedca.cache.aave_dca_cache_payload_builders import build_aave_dca_strategies_payload
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class _DcaStrategiesRebuilder:
    realm = CacheRealm.AAVE_DCA_STRATEGIES
    ttl_seconds = 30.0

    def rebuild(self) -> list[AaveDcaStrategyPayload]:
        return build_aave_dca_strategies_payload()

    def apply_to_cache(self, payload: list[AaveDcaStrategyPayload]) -> None:
        aave_dca_state_cache.update_aave_dca_strategies_state(payload)

    async def notify_websocket(self, payload: object) -> None:
        from src.api.websocket.websocket_manager import websocket_manager
        from src.api.websocket.websocket_structures import WebsocketMessageType

        strategies_payload = cast(list[AaveDcaStrategyPayload], payload)
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.AAVE_DCA_STRATEGIES.value,
            "payload": jsonable_encoder(strategies_payload),
        })


def register_aave_dca_rebuilders() -> None:
    cache_invalidator.register(_DcaStrategiesRebuilder())
    logger.info("[AAVEDCA][CACHE][REBUILDERS] 1 DCA rebuilder registered")
