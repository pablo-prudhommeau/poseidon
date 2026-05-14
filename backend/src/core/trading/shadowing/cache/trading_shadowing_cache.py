from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Optional

from src.api.http.api_schemas import (
    TradingShadowMetaPayload,
    ShadowVerdictChroniclePayload,
    ShadowVerdictChronicleDeltaPayload,
)
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.trading.shadowing.cache.trading_shadowing_cache_structures import TradingShadowingState
from src.core.trading.shadowing.trading_shadowing_structures import TradingShadowingIntelligenceSnapshot
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _touch_realm(realm: CacheRealm) -> None:
    from src.cache.cache_invalidator import cache_invalidator
    cache_invalidator.touch(realm)


class TradingShadowingCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached_shadow_meta: Optional[TradingShadowMetaPayload] = None
        self._cached_shadow_intelligence_snapshot: Optional[TradingShadowingIntelligenceSnapshot] = None
        self._cached_shadow_verdict_chronicle: Optional[ShadowVerdictChroniclePayload] = None
        self._cached_shadow_verdict_chronicle_delta: Optional[ShadowVerdictChronicleDeltaPayload] = None
        self._last_successful_update_timestamp: datetime = get_current_local_datetime()

    def update_shadow_intelligence_snapshot(self, snapshot: TradingShadowingIntelligenceSnapshot) -> None:
        with self._lock:
            self._cached_shadow_intelligence_snapshot = snapshot
            logger.debug("[TRADING][CACHE] Shadow intelligence snapshot updated")
        _touch_realm(CacheRealm.SHADOW_INTELLIGENCE_SNAPSHOT)
        cache_invalidator.mark_dirty(CacheRealm.SHADOW_META)

    def update_trading_shadow_meta_state(self, shadow_meta_payload: TradingShadowMetaPayload) -> None:
        with self._lock:
            self._cached_shadow_meta = shadow_meta_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Shadow meta state updated")
        _touch_realm(CacheRealm.SHADOW_INTELLIGENCE_SNAPSHOT)

    def update_shadow_verdict_chronicle(self, verdict_chronicle: ShadowVerdictChroniclePayload) -> None:
        with self._lock:
            self._cached_shadow_verdict_chronicle = verdict_chronicle
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Shadow verdict chronicle updated")
        _touch_realm(CacheRealm.SHADOW_VERDICT_CHRONICLE)

    def update_shadow_verdict_chronicle_delta(self, verdict_chronicle_delta: ShadowVerdictChronicleDeltaPayload) -> None:
        with self._lock:
            self._cached_shadow_verdict_chronicle_delta = verdict_chronicle_delta
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Shadow verdict chronicle delta updated")
        _touch_realm(CacheRealm.SHADOW_VERDICT_CHRONICLE_DELTA)

    def get_trading_shadow_meta_state(self) -> Optional[TradingShadowMetaPayload]:
        with self._lock:
            return self._cached_shadow_meta

    def get_shadow_intelligence_snapshot(self) -> Optional[TradingShadowingIntelligenceSnapshot]:
        with self._lock:
            return self._cached_shadow_intelligence_snapshot

    def get_shadow_verdict_chronicle(self) -> Optional[ShadowVerdictChroniclePayload]:
        with self._lock:
            return self._cached_shadow_verdict_chronicle

    def get_shadow_verdict_chronicle_delta(self) -> Optional[ShadowVerdictChronicleDeltaPayload]:
        with self._lock:
            return self._cached_shadow_verdict_chronicle_delta

    def get_shadowing_trading_state(self) -> TradingShadowingState:
        with self._lock:
            return TradingShadowingState(
                shadow_meta=self._cached_shadow_meta,
                shadow_intelligence_snapshot=self._cached_shadow_intelligence_snapshot,
                shadow_verdict_chronicle=self._cached_shadow_verdict_chronicle,
                shadow_verdict_chronicle_delta=self._cached_shadow_verdict_chronicle_delta
            )

    def get_last_update_timestamp(self) -> Optional[datetime]:
        with self._lock:
            return self._last_successful_update_timestamp


trading_shadowing_cache = TradingShadowingCache()
