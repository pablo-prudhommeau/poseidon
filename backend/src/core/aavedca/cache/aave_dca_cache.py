from __future__ import annotations

from threading import Lock

from src.api.http.api_schemas import AaveDcaStrategyPayload
from src.core.aavedca.cache.aave_dca_cache_structures import AaveDcaState
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveDcaCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached_strategies: list[AaveDcaStrategyPayload] = []

    def update_aave_dca_strategies_state(self, strategies_payload: list[AaveDcaStrategyPayload]) -> None:
        with self._lock:
            self._cached_strategies = strategies_payload
            logger.debug("[AAVEDCA][CACHE] Aave DCA strategies updated (%d entries)", len(strategies_payload))

    def get_aave_dca_state(self) -> AaveDcaState:
        with self._lock:
            return AaveDcaState(
                aave_dca_strategies=self._cached_strategies
            )


aave_dca_state_cache = AaveDcaCache()
