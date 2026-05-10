from __future__ import annotations

from typing import Protocol

from src.cache.cache_realm import CacheRealm


class CacheRealmRebuildSkipped(Exception):
    pass


class RealmRebuilder(Protocol):
    realm: CacheRealm
    ttl_seconds: float

    def rebuild(self) -> object:
        ...

    def apply_to_cache(self, payload: object) -> None:
        ...

    async def notify_websocket(self, payload: object) -> None:
        ...
