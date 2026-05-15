from __future__ import annotations

import asyncio
import base64
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional

from fastapi.encoders import jsonable_encoder
from starlette.websockets import WebSocket

from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class WebsocketManager:
    def __init__(self) -> None:
        self._connected_clients: set[WebSocket] = set()
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_current_event_loop(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        logger.debug("[WEBSOCKET][MANAGER][LOOP] Event loop successfully attached to websocket manager")

    def register_client_connection(self, websocket_client: WebSocket) -> None:
        self._connected_clients.add(websocket_client)
        logger.info("[WEBSOCKET][MANAGER][CONNECT] Client connection registered. Total active connections: %s", len(self._connected_clients))

    def unregister_client_connection(self, websocket_client: WebSocket) -> None:
        self._connected_clients.discard(websocket_client)
        logger.info("[WEBSOCKET][MANAGER][DISCONNECT] Client connection unregistered. Total active connections: %s", len(self._connected_clients))

    async def close_all_connections(self) -> None:
        logger.info("[WEBSOCKET][MANAGER][SHUTDOWN] Closing all active websocket connections (%s clients)", len(self._connected_clients))
        close_tasks = []
        for websocket_client in list(self._connected_clients):
            close_tasks.append(websocket_client.close())
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._connected_clients.clear()

    @staticmethod
    def _convert_to_json_compatible_payload(raw_payload: dict) -> dict:
        return jsonable_encoder(
            raw_payload,
            custom_encoder={
                Enum: lambda enum_element: enum_element.value,
                bytes: lambda byte_data: base64.b64encode(byte_data).decode("ascii"),
                Path: str,
                Decimal: float,
                timedelta: lambda time_delta: time_delta.total_seconds(),
            },
        )

    async def broadcast_json_payload(self, raw_payload: dict) -> None:
        formatted_payload = self._convert_to_json_compatible_payload(raw_payload)
        stale_websocket_clients: list[WebSocket] = []
        for websocket_client in list(self._connected_clients):
            try:
                await websocket_client.send_json(formatted_payload)
            except Exception:
                stale_websocket_clients.append(websocket_client)
                logger.debug("[WEBSOCKET][MANAGER][BROADCAST] Payload transmission to client failed, scheduling for removal")
        for dead_websocket_client in stale_websocket_clients:
            self.unregister_client_connection(dead_websocket_client)

    def broadcast_json_payload_threadsafe(self, raw_payload: dict) -> None:
        if not self._event_loop:
            logger.debug("[WEBSOCKET][MANAGER][THREADSAFE] Threadsafe broadcast aborted: no event loop currently attached")
            return
        try:
            formatted_payload = self._convert_to_json_compatible_payload(raw_payload)
            asyncio.run_coroutine_threadsafe(self.broadcast_json_payload(formatted_payload), self._event_loop)
        except Exception as exception:
            logger.exception("[WEBSOCKET][MANAGER][THREADSAFE] Threadsafe broadcast encountered a critical failure", exception)


websocket_manager = WebsocketManager()
