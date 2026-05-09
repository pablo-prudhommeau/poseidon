from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from src.api.http.api_schemas import (
    WebsocketInitializationPayload,
    WebsocketStatusPayload,
)
from src.api.websocket.websocket_manager import websocket_manager
from src.configuration.config import settings
from src.core.structures.structures import (
    WebsocketInboundMessage,
    WebsocketMessageType,
)
from src.core.trading.cache.trading_cache import trading_state_cache
from src.logging.logger import get_application_logger

router = APIRouter()
logger = get_application_logger(__name__)


async def _send_cached_state_to_client(websocket_connection: WebSocket) -> None:
    trading_state = trading_state_cache.get_trading_state()
    if trading_state.positions is not None:
        await websocket_connection.send_json({
            "type": WebsocketMessageType.POSITIONS.value,
            "payload": jsonable_encoder(trading_state.positions),
        })
    if trading_state.trades is not None:
        await websocket_connection.send_json({
            "type": WebsocketMessageType.TRADES.value,
            "payload": jsonable_encoder(trading_state.trades),
        })
    if trading_state.portfolio is not None:
        await websocket_connection.send_json({
            "type": WebsocketMessageType.PORTFOLIO.value,
            "payload": jsonable_encoder(trading_state.portfolio),
        })
    if trading_state.liquidity is not None:
        await websocket_connection.send_json({
            "type": WebsocketMessageType.LIQUIDITY.value,
            "payload": jsonable_encoder(trading_state.liquidity),
        })
    if trading_state.shadow_meta is not None:
        await websocket_connection.send_json({
            "type": WebsocketMessageType.SHADOW_META.value,
            "payload": jsonable_encoder(trading_state.shadow_meta),
        })

    from src.core.dca.cache.dca_cache import dca_state_cache
    dca_strategies_payload = dca_state_cache.get_dca_strategies_state()
    await websocket_connection.send_json({
        "type": WebsocketMessageType.DCA_STRATEGIES.value,
        "payload": jsonable_encoder(dca_strategies_payload),
    })


async def send_websocket_handshake(websocket_connection: WebSocket) -> None:
    handshake_payload = WebsocketInitializationPayload(
        status=WebsocketStatusPayload(paper_mode=settings.PAPER_MODE, interval_seconds=settings.TRADING_LOOP_INTERVAL_SECONDS)
    )
    await websocket_connection.send_json({
        "type": WebsocketMessageType.INITIALIZATION.value,
        "payload": jsonable_encoder(handshake_payload),
    })
    logger.info("[WEBSOCKET][HUB][HANDSHAKE] Handshake payload successfully transmitted to client")


def trigger_background_state_sync(websocket_connection: WebSocket) -> None:
    asyncio.create_task(_send_cached_state_to_client(websocket_connection))


@router.websocket("/ws")
async def handle_websocket_connection(websocket_connection: WebSocket) -> None:
    await websocket_connection.accept()
    websocket_manager.register_client_connection(websocket_connection)
    logger.info("[WEBSOCKET][HUB][CONNECTION] New client successfully connected")
    try:
        await send_websocket_handshake(websocket_connection)
        trigger_background_state_sync(websocket_connection)
        while True:
            raw_inbound_message = await websocket_connection.receive_json()
            try:
                validated_inbound_message = WebsocketInboundMessage.model_validate(raw_inbound_message)
            except ValidationError as exception:
                logger.exception("[WEBSOCKET][HUB][RECEIVE] Invalid message schema received from client: %s", exception)
                await websocket_connection.send_json({"type": WebsocketMessageType.ERROR.value, "payload": "Invalid message schema"})
                continue
            if validated_inbound_message.type == WebsocketMessageType.PING.value:
                await websocket_connection.send_json({"type": WebsocketMessageType.PONG.value})
                logger.debug("[WEBSOCKET][HUB][RECEIVE] Ping request received, Pong response transmitted")
            elif validated_inbound_message.type == WebsocketMessageType.REFRESH.value:
                trigger_background_state_sync(websocket_connection)
                logger.info("[WEBSOCKET][HUB][REFRESH] Asynchronous state synchronization triggered upon client request")
            else:
                logger.debug("[WEBSOCKET][HUB][RECEIVE] Unknown message type received: %s", validated_inbound_message.type)
    except WebSocketDisconnect:
        logger.info("[WEBSOCKET][HUB][DISCONNECT] Client gracefully disconnected")
    except Exception as exception:
        logger.exception("[WEBSOCKET][HUB][ERROR] Unexpected WebSocket error encountered: %s", exception)
        try:
            await websocket_connection.send_json({"type": WebsocketMessageType.ERROR.value, "payload": str(exception)})
        except Exception:
            pass
    finally:
        websocket_manager.unregister_client_connection(websocket_connection)
        logger.debug("[WEBSOCKET][HUB][CLEANUP] Socket safely removed from active connections manager")
