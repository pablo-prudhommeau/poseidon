from __future__ import annotations

import asyncio
import base64
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional, Set
from enum import Enum
from datetime import timedelta

from starlette.websockets import WebSocket
from fastapi.encoders import jsonable_encoder

from src.logging.logger import get_logger

log = get_logger(__name__)


class WsManager:
    """Tracks active WebSocket clients and provides broadcast utilities.

    Notes:
        - `attach_current_loop()` must be called from the running event loop
          (e.g., at app startup) to enable thread-safe broadcasts.
        - All payloads are serialized to JSON-compatible primitives before sending.
    """

    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_current_loop(self) -> None:
        """Attach the currently running event loop for thread-safe scheduling."""
        self._loop = asyncio.get_running_loop()
        log.debug("WebSocket manager attached to loop %s", self._loop)

    def connect(self, ws: WebSocket) -> None:
        """Register a newly accepted WebSocket connection."""
        self._clients.add(ws)
        log.debug("WebSocket connected (total=%d)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        """Unregister a WebSocket connection."""
        self._clients.discard(ws)
        log.debug("WebSocket disconnected (total=%d)", len(self._clients))

    @staticmethod
    def _to_json_compatible(data: Any) -> Any:
        """Convert any payload to JSON-compatible primitives.

        Uses FastAPI's jsonable_encoder and custom encoders for a few extra types.
        - Enum -> .value
        - bytes -> base64 string
        - pathlib.Path -> str
        - Decimal -> float
        - timedelta -> total seconds (float)
        """
        return jsonable_encoder(
            data,
            custom_encoder={
                Enum: lambda e: e.value,
                bytes: lambda b: base64.b64encode(b).decode("ascii"),
                Path: str,
                Decimal: float,
                timedelta: lambda td: td.total_seconds(),
            },
        )

    async def broadcast_json(self, data: Any) -> None:
        """Broadcast a JSON-serializable payload to all connected clients."""
        payload = self._to_json_compatible(data)
        stale: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception as exc:
                # Mark as stale; cleanup after loop to avoid set mutation mid-iteration
                stale.append(ws)
                log.debug("Broadcast to a client failed; scheduling removal: %r", exc)
        for dead in stale:
            self.disconnect(dead)

    def broadcast_json_threadsafe(self, data: Any) -> None:
        """Schedule `broadcast_json` from a non-async context.

        Requires that `attach_current_loop()` has been called earlier from the target loop.
        If no loop is attached, this is a no-op by design.
        """
        if not self._loop:
            log.debug("broadcast_json_threadsafe skipped: no loop attached")
            return
        try:
            payload = self._to_json_compatible(data)
            asyncio.run_coroutine_threadsafe(self.broadcast_json(payload), self._loop)
        except Exception as exc:
            # Do not raise; broadcasting should never crash the caller.
            log.debug("broadcast_json_threadsafe failed: %r", exc)


ws_manager = WsManager()
