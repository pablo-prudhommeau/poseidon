from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Optional

from src.api.http.api_schemas import (
    TradingShadowingRegimePayload,
    TradingShadowingVerdictChroniclePayload,
    TradingShadowingVerdictChronicleDeltaPayload,
)
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.trading.shadowing.cache.trading_shadowing_cache_structures import TradingShadowingState
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingSnapshot
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _touch_realm(realm: CacheRealm) -> None:
    from src.cache.cache_invalidator import cache_invalidator
    cache_invalidator.touch(realm)


class TradingShadowingCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached_shadowing_regime: Optional[TradingShadowingRegimePayload] = None
        self._cached_shadowing_snapshot: Optional[TradingShadowingSnapshot] = None
        self._cached_shadowing_verdict_chronicle: Optional[TradingShadowingVerdictChroniclePayload] = None
        self._cached_shadowing_verdict_chronicle_delta: Optional[TradingShadowingVerdictChronicleDeltaPayload] = None
        self._last_successful_update_timestamp: datetime = get_current_local_datetime()

    def update_shadowing_snapshot(self, snapshot: TradingShadowingSnapshot) -> None:
        with self._lock:
            self._cached_shadowing_snapshot = snapshot
            logger.debug("[TRADING][CACHE] Shadowing snapshot updated")
        _touch_realm(CacheRealm.SHADOWING_SNAPSHOT)
        cache_invalidator.mark_dirty(CacheRealm.SHADOWING_REGIME)

    def update_trading_shadowing_regime_state(self, shadowing_regime_payload: TradingShadowingRegimePayload) -> None:
        with self._lock:
            self._cached_shadowing_regime = shadowing_regime_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Shadowing regime state updated")
        _touch_realm(CacheRealm.SHADOWING_REGIME)

    def update_shadowing_verdict_chronicle(self, verdict_chronicle: TradingShadowingVerdictChroniclePayload) -> None:
        with self._lock:
            self._cached_shadowing_verdict_chronicle = verdict_chronicle
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Shadowing verdict chronicle updated")
        _touch_realm(CacheRealm.SHADOWING_VERDICT_CHRONICLE)

    def update_shadowing_verdict_chronicle_delta(self, verdict_chronicle_delta: TradingShadowingVerdictChronicleDeltaPayload) -> None:
        with self._lock:
            self._cached_shadowing_verdict_chronicle_delta = verdict_chronicle_delta
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Shadowing verdict chronicle delta updated")
        _touch_realm(CacheRealm.SHADOWING_VERDICT_CHRONICLE_DELTA)

    def get_trading_shadowing_regime_state(self) -> Optional[TradingShadowingRegimePayload]:
        with self._lock:
            return self._cached_shadowing_regime

    def get_shadowing_snapshot(self) -> Optional[TradingShadowingSnapshot]:
        with self._lock:
            return self._cached_shadowing_snapshot

    def get_shadowing_verdict_chronicle(self) -> Optional[TradingShadowingVerdictChroniclePayload]:
        with self._lock:
            return self._cached_shadowing_verdict_chronicle

    def get_shadowing_verdict_chronicle_delta(self) -> Optional[TradingShadowingVerdictChronicleDeltaPayload]:
        with self._lock:
            return self._cached_shadowing_verdict_chronicle_delta

    def get_shadowing_trading_state(self) -> TradingShadowingState:
        with self._lock:
            return TradingShadowingState(
                shadowing_regime=self._cached_shadowing_regime,
                shadowing_snapshot=self._cached_shadowing_snapshot,
                shadowing_verdict_chronicle=self._cached_shadowing_verdict_chronicle,
                shadowing_verdict_chronicle_delta=self._cached_shadowing_verdict_chronicle_delta
            )

    def get_last_update_timestamp(self) -> Optional[datetime]:
        with self._lock:
            return self._last_successful_update_timestamp


trading_shadowing_cache = TradingShadowingCache()
