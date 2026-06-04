from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
from src.integrations.blockchain.solana.solana_rpc_client import (
    fetch_solana_native_balance_lamports,
    fetch_token_account_last_activity_datetime,
    list_wallet_spl_token_accounts,
)
from src.integrations.blockchain.solana.solana_structures import (
    SolanaWalletSnapshot,
    SolanaWalletTokenAccountSnapshot,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_token_account_activity_cache: dict[str, datetime] = {}
_token_account_activity_cache_expires_at_monotonic: dict[str, float] = {}

_cached_wallet_snapshot: Optional[SolanaWalletSnapshot] = None
_cached_wallet_snapshot_expires_at_monotonic: float = 0.0


def invalidate_solana_wallet_snapshot_cache() -> None:
    global _cached_wallet_snapshot, _cached_wallet_snapshot_expires_at_monotonic
    _cached_wallet_snapshot = None
    _cached_wallet_snapshot_expires_at_monotonic = 0.0


def resolve_solana_wallet_snapshot(force_refresh: bool = False) -> SolanaWalletSnapshot:
    global _cached_wallet_snapshot, _cached_wallet_snapshot_expires_at_monotonic

    now_monotonic = time.monotonic()
    if (not force_refresh and _cached_wallet_snapshot is not None  and now_monotonic < _cached_wallet_snapshot_expires_at_monotonic):
        return _cached_wallet_snapshot

    signer = build_default_solana_signer()
    wallet_address = str(signer.keypair.pubkey())
    rpc_url = resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA)
    token_accounts = list_wallet_spl_token_accounts(rpc_url, wallet_address)
    native_lamports = fetch_solana_native_balance_lamports(rpc_url, wallet_address)

    snapshot = SolanaWalletSnapshot(
        wallet_address=wallet_address,
        rpc_url=rpc_url,
        token_accounts=token_accounts,
        native_lamports=native_lamports,
        fetched_at_monotonic=now_monotonic,
    )
    _cached_wallet_snapshot = snapshot
    _cached_wallet_snapshot_expires_at_monotonic = (
        now_monotonic + settings.TRADING_SOLANA_WALLET_SNAPSHOT_TTL_SECONDS
    )
    logger.debug(
        "[BLOCKCHAIN][SOL][WALLET][SNAPSHOT] Refreshed wallet snapshot — token_account_count=%d native_lamports=%d",
        len(token_accounts),
        native_lamports,
    )
    return snapshot


def resolve_cached_token_account_last_activity_datetime(
        rpc_url: str,
        token_account_address: str,
) -> Optional[datetime]:
    now_monotonic = time.monotonic()
    cache_expires_at = _token_account_activity_cache_expires_at_monotonic.get(token_account_address)
    if cache_expires_at is not None and now_monotonic < cache_expires_at:
        return _token_account_activity_cache.get(token_account_address)

    try:
        last_activity_datetime = fetch_token_account_last_activity_datetime(rpc_url, token_account_address)
    except BlockchainRpcUnavailableError:
        cached_activity = _token_account_activity_cache.get(token_account_address)
        if cached_activity is not None:
            logger.debug(
                "[BLOCKCHAIN][SOL][WALLET][ACTIVITY] RPC unavailable — using cached activity for account_prefix=%s",
                token_account_address[:12],
            )
            return cached_activity
        raise

    if last_activity_datetime is not None:
        _token_account_activity_cache[token_account_address] = last_activity_datetime
        _token_account_activity_cache_expires_at_monotonic[token_account_address] = (
            now_monotonic + settings.TRADING_SOLANA_TOKEN_ACCOUNT_ACTIVITY_CACHE_SECONDS
        )
    return last_activity_datetime
