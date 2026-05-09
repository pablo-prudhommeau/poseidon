from __future__ import annotations

import asyncio
import threading
import time

from src.cache.cache_protocols import RealmRebuilder
from src.cache.cache_realm import CacheRealm
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class CacheInvalidator:
    def __init__(self) -> None:
        self._dirty: set[CacheRealm] = set()
        self._in_flight: set[CacheRealm] = set()
        self._last_rebuild_at_monotonic: dict[CacheRealm, float] = {}
        self._lock = threading.Lock()
        self._rebuilders: dict[CacheRealm, RealmRebuilder] = {}

    def register(self, rebuilder: RealmRebuilder) -> None:
        self._rebuilders[rebuilder.realm] = rebuilder
        logger.debug("[CACHE][REGISTER] realm=%s ttl=%ss", rebuilder.realm.value, rebuilder.ttl_seconds)

    def mark_dirty(self, *realms_to_mark_as_dirty: CacheRealm) -> None:
        with self._lock:
            self._dirty.update(realms_to_mark_as_dirty)

    def touch(self, realm: CacheRealm) -> None:
        with self._lock:
            self._last_rebuild_at_monotonic[realm] = time.monotonic()

    def start_watcher(self) -> asyncio.Task[None]:
        return asyncio.create_task(self._watch_loop())

    async def _watch_loop(self) -> None:
        from src.configuration.config import settings
        debounce_seconds = settings.CACHE_WATCHER_DEBOUNCE_SECONDS
        logger.info("[CACHE][WATCHER] Starting cache invalidation watcher (debounce=%.2fs)", debounce_seconds)

        while True:
            await asyncio.sleep(debounce_seconds)
            now_monotonic = time.monotonic()

            with self._lock:
                for realm_candidate, rebuilder in self._rebuilders.items():
                    if realm_candidate in self._in_flight:
                        continue
                    previous_rebuild_monotonic = (
                        self._last_rebuild_at_monotonic[realm_candidate]
                        if realm_candidate in self._last_rebuild_at_monotonic
                        else 0.0
                    )
                    if now_monotonic - previous_rebuild_monotonic >= rebuilder.ttl_seconds:
                        cold_rebuild_without_prior_explicit_invalidation = (
                                realm_candidate not in self._dirty
                                and realm_candidate in self._last_rebuild_at_monotonic
                        )
                        if cold_rebuild_without_prior_explicit_invalidation:
                            staleness_seconds = now_monotonic - previous_rebuild_monotonic
                            logger.warning(
                                "[CACHE][TTL_GUARD][STALE_REALM] realm=%s elapsed_since_last_rebuild=%.1fs ttl_seconds=%.1fs "
                                "no explicit mark_dirty this interval; cold rebuild scheduled — verify mutators invalidate this realm",
                                realm_candidate.value,
                                staleness_seconds,
                                rebuilder.ttl_seconds,
                            )
                        self._dirty.add(realm_candidate)

                pending_realms = self._dirty - self._in_flight
                self._dirty -= pending_realms
                self._in_flight.update(pending_realms)

            if not pending_realms:
                continue

            realms_for_parallel_dispatch = sorted(pending_realms, key=lambda realm_item: realm_item.value)
            ordered_realm_identifiers = ",".join(realm_item.value for realm_item in realms_for_parallel_dispatch)
            logger.debug(
                "[CACHE][WATCHER][BATCH] scheduling %d concurrent realm rebuild task(s): %s",
                len(realms_for_parallel_dispatch),
                ordered_realm_identifiers,
            )
            for realm_item in realms_for_parallel_dispatch:
                asyncio.create_task(self._process_realm(realm_item))

    async def _process_realm(self, realm_candidate: CacheRealm) -> None:
        if realm_candidate not in self._rebuilders:
            logger.warning("[CACHE][REBUILD] No rebuilder registered for realm=%s", realm_candidate.value)
            with self._lock:
                self._in_flight.discard(realm_candidate)
            return

        rebuilder = self._rebuilders[realm_candidate]

        try:
            logger.debug("[CACHE][REBUILD] realm=%s starting", realm_candidate.value)
            rebuilt_payload = await asyncio.to_thread(rebuilder.rebuild)
            rebuilder.apply_to_cache(rebuilt_payload)
            await rebuilder.notify_websocket(rebuilt_payload)
            logger.debug("[CACHE][REBUILD] realm=%s done", realm_candidate.value)
        except Exception:
            logger.exception("[CACHE][REBUILD] realm=%s failed", realm_candidate.value)
        finally:
            with self._lock:
                self._in_flight.discard(realm_candidate)
                self._last_rebuild_at_monotonic[realm_candidate] = time.monotonic()


cache_invalidator = CacheInvalidator()
