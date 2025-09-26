from __future__ import annotations
import asyncio
from typing import Set
from starlette.websockets import WebSocket

class WsManager:
    def __init__(self):
        self._clients: Set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_current_loop(self):
        self._loop = asyncio.get_running_loop()

    def connect(self, ws: WebSocket):
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)

    async def broadcast_json(self, data):
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for d in dead:
            self.disconnect(d)

    def broadcast_json_threadsafe(self, data):
        if not self._loop:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast_json(data), self._loop)

ws_manager = WsManager()
