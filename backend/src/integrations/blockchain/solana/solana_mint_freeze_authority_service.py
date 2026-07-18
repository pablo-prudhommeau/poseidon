from __future__ import annotations

import time
from typing import Optional

from src.configuration.config import settings
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.solana.solana_mint_freeze_authority_helpers import (
    build_solana_mint_freeze_authority_snapshot,
    is_solana_mint_blocked_by_freeze_authority_snapshot,
    resolve_freeze_authority_address_from_snapshots,
)
from src.integrations.blockchain.solana.solana_rpc_client import (
    get_solana_rpc_url,
    rpc_get_account_info_json_parsed,
    rpc_get_multiple_accounts_json_parsed,
)
from src.integrations.blockchain.solana.solana_structures import SolanaMintFreezeAuthoritySnapshot
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_cached_snapshots_by_mint_address: dict[str, SolanaMintFreezeAuthoritySnapshot] = {}
_cached_snapshot_expires_at_monotonic_by_mint_address: dict[str, float] = {}


def resolve_solana_mint_freeze_authority_snapshot(mint_address: str) -> SolanaMintFreezeAuthoritySnapshot:
    normalized_mint_address = mint_address.strip()
    if not normalized_mint_address:
        return SolanaMintFreezeAuthoritySnapshot(
            mint_address=mint_address,
            freeze_authority_address=None,
        )

    cached_snapshot = _read_cached_snapshot(normalized_mint_address)
    if cached_snapshot is not None:
        logger.debug(
            "[BLOCKCHAIN][SOL][MINT][FREEZE_AUTHORITY] Cache hit — mint_address_prefix=%s",
            normalized_mint_address[:12],
        )
        return cached_snapshot

    rpc_url = get_solana_rpc_url()
    account_info_value = rpc_get_account_info_json_parsed(rpc_url, normalized_mint_address)
    snapshot = build_solana_mint_freeze_authority_snapshot(
        mint_address=normalized_mint_address,
        account_info_value=account_info_value,
    )
    _write_cached_snapshot(snapshot)
    logger.debug(
        "[BLOCKCHAIN][SOL][MINT][FREEZE_AUTHORITY] Resolved mint freeze authority — mint_address_prefix=%s freeze_authority_active=%s",
        normalized_mint_address[:12],
        snapshot.freeze_authority_address is not None,
    )
    return snapshot


def resolve_solana_mint_freeze_authority_snapshots_batch(
        mint_addresses: list[str],
) -> list[SolanaMintFreezeAuthoritySnapshot]:
    normalized_mint_addresses: list[str] = []
    seen_mint_addresses: set[str] = set()
    for mint_address in mint_addresses:
        normalized_mint_address = mint_address.strip()
        if not normalized_mint_address or normalized_mint_address in seen_mint_addresses:
            continue
        seen_mint_addresses.add(normalized_mint_address)
        normalized_mint_addresses.append(normalized_mint_address)

    if not normalized_mint_addresses:
        return []

    snapshots: list[SolanaMintFreezeAuthoritySnapshot] = []
    mint_addresses_to_fetch: list[str] = []

    for normalized_mint_address in normalized_mint_addresses:
        cached_snapshot = _read_cached_snapshot(normalized_mint_address)
        if cached_snapshot is not None:
            snapshots.append(cached_snapshot)
            continue
        mint_addresses_to_fetch.append(normalized_mint_address)

    if mint_addresses_to_fetch:
        rpc_url = get_solana_rpc_url()
        account_info_values = rpc_get_multiple_accounts_json_parsed(rpc_url, mint_addresses_to_fetch)
        for mint_address, account_info_value in zip(mint_addresses_to_fetch, account_info_values, strict=True):
            snapshot = build_solana_mint_freeze_authority_snapshot(
                mint_address=mint_address,
                account_info_value=account_info_value,
            )
            _write_cached_snapshot(snapshot)
            snapshots.append(snapshot)

    logger.info(
        "[BLOCKCHAIN][SOL][MINT][FREEZE_AUTHORITY] Resolved batch freeze authority snapshots — requested=%d resolved=%d cache_hits=%d",
        len(normalized_mint_addresses),
        len(snapshots),
        len(normalized_mint_addresses) - len(mint_addresses_to_fetch),
    )
    return snapshots


def is_solana_mint_blocked_by_active_freeze_authority(mint_address: str) -> bool:
    try:
        snapshot = resolve_solana_mint_freeze_authority_snapshot(mint_address=mint_address)
    except BlockchainRpcUnavailableError:
        logger.debug(
            "[BLOCKCHAIN][SOL][MINT][FREEZE_AUTHORITY] RPC unavailable during buy gate — mint_address_prefix=%s decision=blocked",
            mint_address[:12],
        )
        return True

    return is_solana_mint_blocked_by_freeze_authority_snapshot(snapshot)


def is_solana_mint_blocked_by_active_freeze_authority_from_snapshots(
        snapshots: list[SolanaMintFreezeAuthoritySnapshot],
        mint_address: str,
) -> bool:
    freeze_authority_address = resolve_freeze_authority_address_from_snapshots(
        snapshots=snapshots,
        mint_address=mint_address,
    )
    return freeze_authority_address is not None


def invalidate_solana_mint_freeze_authority_cache() -> None:
    global _cached_snapshots_by_mint_address, _cached_snapshot_expires_at_monotonic_by_mint_address

    _cached_snapshots_by_mint_address = {}
    _cached_snapshot_expires_at_monotonic_by_mint_address = {}


def _read_cached_snapshot(mint_address: str) -> Optional[SolanaMintFreezeAuthoritySnapshot]:
    cached_snapshot = _cached_snapshots_by_mint_address.get(mint_address)
    if cached_snapshot is None:
        return None

    expires_at_monotonic = _cached_snapshot_expires_at_monotonic_by_mint_address.get(mint_address)
    if expires_at_monotonic is None or time.monotonic() >= expires_at_monotonic:
        return None

    return cached_snapshot


def _write_cached_snapshot(snapshot: SolanaMintFreezeAuthoritySnapshot) -> None:
    cache_ttl_seconds = settings.SOLANA_MINT_FREEZE_AUTHORITY_CACHE_TTL_SECONDS
    _cached_snapshots_by_mint_address[snapshot.mint_address] = snapshot
    _cached_snapshot_expires_at_monotonic_by_mint_address[snapshot.mint_address] = (
            time.monotonic() + cache_ttl_seconds
    )
