from __future__ import annotations

import time
from typing import Optional

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_helpers import resolve_token_account_rent_lamports
from src.core.trading.portfolio.trading_portfolio_solana_wallet_auxiliary_service import (
    build_solana_token_account_rent_breakdown_from_wallet_snapshot,
    invalidate_solana_rent_breakdown_cache,
    resolve_solana_locked_token_account_capital_usd,
)
from src.core.trading.portfolio.trading_portfolio_structures import SolanaTokenAccountRentBreakdown
from src.integrations.blockchain.blockchain_exceptions import BlockchainRpcUnavailableError
from src.integrations.blockchain.blockchain_free_cash_service import _get_stablecoin_address_for_blockchain
from src.integrations.blockchain.solana.solana_rpc_client import resolve_sol_usd_price
from src.integrations.blockchain.solana.solana_structures import (
    SolanaOnchainWalletContext,
    SolanaRpcFailureReason,
    SolanaWalletSnapshot,
)
from src.integrations.blockchain.solana.solana_wallet_snapshot_service import (
    invalidate_solana_wallet_snapshot_cache,
    resolve_solana_wallet_snapshot,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

STABLECOIN_DECIMALS = 6

_cached_wallet_context: Optional[SolanaOnchainWalletContext] = None
_cached_wallet_context_expires_at_monotonic: float = 0.0


def invalidate_solana_onchain_wallet_context_cache() -> None:
    global _cached_wallet_context, _cached_wallet_context_expires_at_monotonic

    _cached_wallet_context = None
    _cached_wallet_context_expires_at_monotonic = 0.0
    invalidate_solana_wallet_snapshot_cache()
    invalidate_solana_rent_breakdown_cache()


def resolve_solana_onchain_wallet_context(force_refresh: bool = False) -> SolanaOnchainWalletContext:
    global _cached_wallet_context, _cached_wallet_context_expires_at_monotonic

    now_monotonic = time.monotonic()
    if (
            not force_refresh
            and _cached_wallet_context is not None
            and now_monotonic < _cached_wallet_context_expires_at_monotonic
    ):
        return _cached_wallet_context

    wallet_snapshot = resolve_solana_wallet_snapshot(force_refresh=force_refresh)
    stablecoin_mint_address = _get_stablecoin_address_for_blockchain(BlockchainNetwork.SOLANA)
    stablecoin_balance_raw = _resolve_stablecoin_balance_raw(
        wallet_snapshot=wallet_snapshot,
        stablecoin_mint_address=stablecoin_mint_address,
    )
    native_token_balance_raw = float(wallet_snapshot.native_lamports) / 1_000_000_000.0

    sol_usd_price = resolve_sol_usd_price(wallet_snapshot.rpc_url)
    native_token_balance_usd = 0.0
    if sol_usd_price is not None and sol_usd_price > 0.0:
        native_token_balance_usd = native_token_balance_raw * sol_usd_price

    rent_breakdown = build_solana_token_account_rent_breakdown_from_wallet_snapshot(
        wallet_snapshot=wallet_snapshot,
        sol_usd_price=sol_usd_price,
    )

    wallet_context = SolanaOnchainWalletContext(
        wallet_snapshot=wallet_snapshot,
        rent_breakdown=rent_breakdown,
        stablecoin_balance_raw=stablecoin_balance_raw,
        native_token_balance_raw=native_token_balance_raw,
        native_token_balance_usd=native_token_balance_usd,
    )
    _cached_wallet_context = wallet_context
    _cached_wallet_context_expires_at_monotonic = (
        now_monotonic + settings.TRADING_SOLANA_WALLET_SNAPSHOT_TTL_SECONDS
    )
    logger.debug(
        "[BLOCKCHAIN][SOL][WALLET][CONTEXT] Refreshed on-chain wallet context — "
        "stablecoin_balance=%.6f native_sol=%.6f rent_locked_sol=%.4f",
        stablecoin_balance_raw,
        native_token_balance_raw,
        rent_breakdown.locked_sol,
    )
    return wallet_context


def resolve_solana_onchain_wallet_context_or_cached() -> Optional[SolanaOnchainWalletContext]:
    try:
        return resolve_solana_onchain_wallet_context(force_refresh=False)
    except BlockchainRpcUnavailableError:
        if _cached_wallet_context is not None:
            logger.debug("[BLOCKCHAIN][SOL][WALLET][CONTEXT] RPC unavailable — retaining cached wallet context")
            return _cached_wallet_context
        return None


def is_solana_live_portfolio_chain_enabled() -> bool:
    if settings.PAPER_MODE:
        return False
    for allowed_chain in settings.TRADING_ALLOWED_CHAINS:
        if allowed_chain.strip().lower() == BlockchainNetwork.SOLANA.value:
            return True
    return False


def resolve_required_solana_onchain_wallet_context_for_live_portfolio() -> SolanaOnchainWalletContext:
    wallet_context = resolve_solana_onchain_wallet_context_or_cached()
    if wallet_context is None:
        raise BlockchainRpcUnavailableError(
            "[BLOCKCHAIN][SOL][WALLET][CONTEXT] Live portfolio and liquidity require complete Solana wallet context",
            blockchain_network=BlockchainNetwork.SOLANA,
            rpc_method="wallet_context",
            failure_reason=SolanaRpcFailureReason.ENDPOINTS_EXHAUSTED,
        )
    return wallet_context


def _resolve_stablecoin_balance_raw(
        wallet_snapshot: SolanaWalletSnapshot,
        stablecoin_mint_address: str,
) -> float:
    if not stablecoin_mint_address:
        return 0.0
    for token_account in wallet_snapshot.token_accounts:
        if token_account.token_mint_address != stablecoin_mint_address:
            continue
        return float(token_account.balance_raw) / float(10 ** STABLECOIN_DECIMALS)
    return 0.0


def resolve_wallet_auxiliary_assets_usd_from_context(wallet_context: SolanaOnchainWalletContext) -> float:
    locked_token_account_capital_usd = resolve_solana_locked_token_account_capital_usd(
        wallet_context.rent_breakdown,
    )
    return wallet_context.native_token_balance_usd + locked_token_account_capital_usd
