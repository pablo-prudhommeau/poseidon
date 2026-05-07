from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from src.api.cache.trading_display_state_cache import trading_display_state_cache
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
from src.logging.logger import get_application_logger

router = APIRouter()
logger = get_application_logger(__name__)


async def _send_cached_state_to_client(websocket_connection: WebSocket) -> None:
    trading_state = trading_display_state_cache.get_trading_state()

    if trading_state.positions is not None:
        await websocket_connection.send_json({"type": WebsocketMessageType.POSITIONS.value, "payload": jsonable_encoder(trading_state.positions)})

    if trading_state.trades is not None:
        await websocket_connection.send_json({"type": WebsocketMessageType.TRADES.value, "payload": jsonable_encoder(trading_state.trades)})

    if trading_state.portfolio is not None:
        await websocket_connection.send_json({"type": WebsocketMessageType.PORTFOLIO.value, "payload": jsonable_encoder(trading_state.portfolio)})

    dca_state = trading_display_state_cache.get_dca_strategies_state()
    if dca_state is not None:
        await websocket_connection.send_json({"type": WebsocketMessageType.DCA_STRATEGIES.value, "payload": jsonable_encoder(dca_state)})


async def send_websocket_handshake(websocket_connection: WebSocket) -> None:
    handshake_payload = WebsocketInitializationPayload(
        status=WebsocketStatusPayload(paper_mode=settings.PAPER_MODE, interval_seconds=settings.TRADING_LOOP_INTERVAL_SECONDS)
    )

    await websocket_connection.send_json({"type": WebsocketMessageType.INITIALIZATION.value, "payload": jsonable_encoder(handshake_payload)})
    logger.info("[WEBSOCKET][HUB][HANDSHAKE] Handshake payload successfully transmitted to client")


def trigger_background_state_sync(websocket_connection: WebSocket) -> None:
    asyncio.create_task(_send_cached_state_to_client(websocket_connection))


def notify_trading_state_changed() -> None:
    from src.core.jobs.trading_display_broadcast_job import broadcast_trading_display_state
    event_loop = websocket_manager._event_loop

    if not event_loop or not event_loop.is_running() or event_loop.is_closed():
        logger.debug("[WEBSOCKET][HUB][NOTIFY] Event loop is either closed or not running, display state will refresh on next broadcast tick")
        return

    asyncio.run_coroutine_threadsafe(broadcast_trading_display_state(), event_loop)


def notify_dca_state_changed() -> None:
    from src.core.jobs.trading_display_broadcast_job import broadcast_dca_strategies_state
    event_loop = websocket_manager._event_loop

    if not event_loop or not event_loop.is_running() or event_loop.is_closed():
        logger.debug("[WEBSOCKET][HUB][NOTIFY] Event loop is either closed or not running, DCA state will refresh on next broadcast tick")
        return

    asyncio.run_coroutine_threadsafe(broadcast_dca_strategies_state(), event_loop)


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
