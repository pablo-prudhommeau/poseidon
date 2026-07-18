from __future__ import annotations

from typing import Optional

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.aavesentinel.aave_sentinel_structures import AaveSentinelTransactionHeadFingerprint
from src.core.aavesentinel.cache.aave_sentinel_cache import aave_sentinel_state_cache
from src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders import clear_shared_universal_ledger_cache
from src.core.aavesentinel.position.aave_sentinel_position_snapshot_service import AaveSentinelSnapshotService
from src.integrations.routescan.routescan_client import RoutescanClient
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_snapshot_service: Optional[AaveSentinelSnapshotService] = None


async def _ensure_snapshot_service() -> AaveSentinelSnapshotService:
    global _snapshot_service
    if _snapshot_service is None:
        _snapshot_service = AaveSentinelSnapshotService()
        await _snapshot_service.initialize()
    return _snapshot_service


async def fetch_transaction_head_fingerprint(wallet_address: str) -> AaveSentinelTransactionHeadFingerprint:
    routescan_client = RoutescanClient(wallet_address=wallet_address)
    try:
        latest_normal_transaction_hash = await routescan_client.fetch_latest_normal_transaction_hash()
        latest_internal_transaction_hash = await routescan_client.fetch_latest_internal_transaction_hash()
        latest_token_transaction_hash = await routescan_client.fetch_latest_token_transaction_hash()
        return AaveSentinelTransactionHeadFingerprint(
            latest_normal_transaction_hash=latest_normal_transaction_hash,
            latest_internal_transaction_hash=latest_internal_transaction_hash,
            latest_token_transaction_hash=latest_token_transaction_hash,
        )
    finally:
        await routescan_client.close()


async def poll_transaction_fingerprint_and_invalidate_capital_flow_if_changed() -> bool:
    snapshot_service = await _ensure_snapshot_service()
    wallet_address = snapshot_service.wallet_address
    if not wallet_address:
        return False

    current_transaction_fingerprint = await fetch_transaction_head_fingerprint(wallet_address=wallet_address)
    cached_transaction_fingerprint = aave_sentinel_state_cache.get_last_seen_transaction_fingerprint()

    if cached_transaction_fingerprint is None:
        aave_sentinel_state_cache.update_last_seen_transaction_fingerprint(
            transaction_fingerprint=current_transaction_fingerprint,
        )
        return False

    if cached_transaction_fingerprint == current_transaction_fingerprint:
        return False

    aave_sentinel_state_cache.update_last_seen_transaction_fingerprint(
        transaction_fingerprint=current_transaction_fingerprint,
    )
    clear_shared_universal_ledger_cache()
    cache_invalidator.mark_dirty(CacheRealm.AAVE_SENTINEL_CAPITAL_FLOW)
    cache_invalidator.mark_dirty(CacheRealm.AAVE_SENTINEL_PERFORMANCE)
    logger.debug(
        "[AAVESENTINEL][CACHE] Capital flow and performance realms marked dirty "
        "after transaction fingerprint change",
    )
    return True
