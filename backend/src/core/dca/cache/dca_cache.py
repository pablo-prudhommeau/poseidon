from __future__ import annotations

from threading import Lock

from src.api.http.api_schemas import DcaStrategyPayload
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class DcaCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached_strategies: list[DcaStrategyPayload] = []

    def update_dca_strategies_state(self, strategies_payload: list[DcaStrategyPayload]) -> None:
        with self._lock:
            self._cached_strategies = strategies_payload
            logger.debug("[DCA][CACHE] DCA strategies updated (%d entries)", len(strategies_payload))

    def get_dca_strategies_state(self) -> list[DcaStrategyPayload]:
        with self._lock:
            return list(self._cached_strategies)


dca_state_cache = DcaCache()
