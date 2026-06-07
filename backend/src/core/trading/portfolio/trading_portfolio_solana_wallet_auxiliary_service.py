from __future__ import annotations

import time
from datetime import timedelta

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_helpers import resolve_token_account_rent_lamports
from src.core.trading.portfolio.trading_portfolio_structures import LiveLiquiditySnapshotUnavailableError
from src.core.utils.date_utils import get_current_local_datetime
from src.core.trading.trading_configuration_service import resolve_stablecoin_address_for_blockchain
from src.integrations.blockchain.solana.solana_structures import (
    SOLANA_SUPPORTED_TOKEN_ACCOUNT_OWNER_PROGRAM_IDS,
    SolanaTokenAccountRentBreakdown,
    SolanaWalletSnapshot,
    SolanaWalletTokenAccountSnapshot,
)
from src.integrations.blockchain.solana.solana_wallet_snapshot_service import (
    resolve_cached_token_account_last_activity_datetime,
    resolve_solana_wallet_snapshot,
)
from src.integrations.jupiter.jupiter_client import resolve_sol_usd_price
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

_cached_rent_breakdown: SolanaTokenAccountRentBreakdown | None = None
_cached_rent_breakdown_expires_at_monotonic: float = 0.0


def invalidate_solana_rent_breakdown_cache() -> None:
    global _cached_rent_breakdown, _cached_rent_breakdown_expires_at_monotonic
    _cached_rent_breakdown = None
    _cached_rent_breakdown_expires_at_monotonic = 0.0


def resolve_solana_token_account_rent_breakdown() -> SolanaTokenAccountRentBreakdown:
    global _cached_rent_breakdown, _cached_rent_breakdown_expires_at_monotonic

    now_monotonic = time.monotonic()
    if (_cached_rent_breakdown is not None and now_monotonic < _cached_rent_breakdown_expires_at_monotonic):
        return _cached_rent_breakdown

    wallet_snapshot = resolve_solana_wallet_snapshot(force_refresh=False)
    sol_usd_price = resolve_sol_usd_price()
    rent_breakdown = build_solana_token_account_rent_breakdown_from_wallet_snapshot(
        wallet_snapshot=wallet_snapshot,
        sol_usd_price=sol_usd_price,
    )

    _cached_rent_breakdown = rent_breakdown
    _cached_rent_breakdown_expires_at_monotonic = (
        now_monotonic + settings.TRADING_SOLANA_RENT_BREAKDOWN_CACHE_TTL_SECONDS
    )
    return rent_breakdown


def build_solana_token_account_rent_breakdown_from_wallet_snapshot(
        wallet_snapshot: SolanaWalletSnapshot,
        sol_usd_price: float | None,
) -> SolanaTokenAccountRentBreakdown:
    global _cached_rent_breakdown

    if sol_usd_price is None or sol_usd_price <= 0.0:
        if _cached_rent_breakdown is not None:
            logger.debug(
                "[TRADING][PORTFOLIO][SOLANA][RENT] SOL/USD unavailable — retaining cached rent breakdown"
            )
            return _cached_rent_breakdown
        logger.debug(
            "[TRADING][PORTFOLIO][SOLANA][RENT] SOL/USD unavailable — returning zero rent breakdown"
        )
        return SolanaTokenAccountRentBreakdown(
            active_usd=0.0,
            closable_usd=0.0,
            pending_reclaim_usd=0.0,
            locked_sol=0.0,
            active_account_count=0,
            closable_account_count=0,
            pending_reclaim_account_count=0,
        )

    stablecoin_mint_address = resolve_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    token_account_rent_lamports = resolve_token_account_rent_lamports()
    rent_usd_per_account = (token_account_rent_lamports / 1_000_000_000.0) * sol_usd_price
    inactive_cutoff = get_current_local_datetime() - timedelta(
        hours=settings.TRADING_SOLANA_TOKEN_ACCOUNT_RECLAIM_INACTIVE_HOURS,
    )
    mint_addresses_with_non_zero_balance = _resolve_mint_addresses_with_non_zero_balance(
        wallet_snapshot.token_accounts,
    )

    active_account_count = 0
    closable_account_count = 0
    pending_reclaim_account_count = 0
    for token_account in wallet_snapshot.token_accounts:
        if not _is_wallet_token_account_eligible_for_rent_tracking(
            token_account=token_account,
            stablecoin_mint_address=stablecoin_mint_address,
        ):
            continue
        if token_account.balance_raw != 0:
            active_account_count += 1
            continue
        if token_account.token_mint_address in mint_addresses_with_non_zero_balance:
            active_account_count += 1
            continue
        last_activity_timestamp = resolve_cached_token_account_last_activity_datetime(
            rpc_url=wallet_snapshot.rpc_url,
            token_account_address=token_account.token_account_address,
        )
        if last_activity_timestamp is None:
            active_account_count += 1
            continue
        closable_account_count += 1
        if last_activity_timestamp < inactive_cutoff:
            pending_reclaim_account_count += 1

    active_usd = float(active_account_count * rent_usd_per_account)
    closable_usd = float(closable_account_count * rent_usd_per_account)
    pending_reclaim_usd = float(pending_reclaim_account_count * rent_usd_per_account)
    locked_account_count = active_account_count + closable_account_count
    locked_sol = float((locked_account_count * token_account_rent_lamports) / 1_000_000_000.0)
    logger.debug(
        "[TRADING][PORTFOLIO][SOLANA][RENT] Rent breakdown — active_accounts=%d closable_accounts=%d "
        "pending_reclaim_accounts=%d active_usd=%.2f closable_usd=%.2f pending_reclaim_usd=%.2f locked_sol=%.4f",
        active_account_count,
        closable_account_count,
        pending_reclaim_account_count,
        active_usd,
        closable_usd,
        pending_reclaim_usd,
        locked_sol,
    )
    return SolanaTokenAccountRentBreakdown(
        active_usd=active_usd,
        closable_usd=closable_usd,
        pending_reclaim_usd=pending_reclaim_usd,
        locked_sol=locked_sol,
        active_account_count=active_account_count,
        closable_account_count=closable_account_count,
        pending_reclaim_account_count=pending_reclaim_account_count,
    )


def resolve_solana_locked_token_account_capital_usd(rent_breakdown: SolanaTokenAccountRentBreakdown) -> float:
    return rent_breakdown.active_usd + rent_breakdown.closable_usd


def _is_wallet_token_account_eligible_for_rent_tracking(
        token_account: SolanaWalletTokenAccountSnapshot,
        stablecoin_mint_address: str,
) -> bool:
    if token_account.token_mint_address == stablecoin_mint_address:
        return False
    if token_account.owner_program_id not in SOLANA_SUPPORTED_TOKEN_ACCOUNT_OWNER_PROGRAM_IDS:
        return False
    return True


def _resolve_mint_addresses_with_non_zero_balance(
        token_accounts: list[SolanaWalletTokenAccountSnapshot],
) -> set[str]:
    mint_addresses_with_non_zero_balance: set[str] = set()
    for token_account in token_accounts:
        if token_account.balance_raw != 0:
            mint_addresses_with_non_zero_balance.add(token_account.token_mint_address)
    return mint_addresses_with_non_zero_balance
