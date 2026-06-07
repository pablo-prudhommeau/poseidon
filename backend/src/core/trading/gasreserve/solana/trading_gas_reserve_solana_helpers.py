from __future__ import annotations

import threading

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_structures import (
    TradingGasReserveSolanaCostSnapshot,
)
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.integrations.blockchain.solana.solana_rpc_client import (
    format_lamports_as_sol_text,
    rpc_get_minimum_balance_for_rent_exemption,
)
from src.integrations.blockchain.solana.solana_structures import SOLANA_SPL_TOKEN_ACCOUNT_DATA_LENGTH
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

DEFAULT_TOKEN_ACCOUNT_RENT_LAMPORTS = 2_039_280
POSITION_LIFECYCLE_TRADE_COUNT = 3
BUY_GUARD_RESERVE_CYCLE_COUNT = 1

_cached_solana_gas_reserve_cost_snapshot: TradingGasReserveSolanaCostSnapshot | None = None
_cost_snapshot_cache_lock = threading.Lock()


def compute_per_position_cost_lamports(
        token_account_rent_lamports: int,
        average_swap_fee_lamports: int,
) -> int:
    return token_account_rent_lamports + (POSITION_LIFECYCLE_TRADE_COUNT * average_swap_fee_lamports)


def compute_cycle_cost_lamports(
        max_open_positions: int,
        token_account_rent_lamports: int,
        average_swap_fee_lamports: int,
) -> int:
    per_position_cost_lamports = compute_per_position_cost_lamports(
        token_account_rent_lamports=token_account_rent_lamports,
        average_swap_fee_lamports=average_swap_fee_lamports,
    )
    return max_open_positions * per_position_cost_lamports


def compute_reserve_lamports(cycle_cost_lamports: int, cycle_count: int) -> int:
    return cycle_cost_lamports * cycle_count


def resolve_token_account_rent_lamports() -> int:
    rpc_url = resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA)
    token_account_rent_lamports = rpc_get_minimum_balance_for_rent_exemption(
        rpc_url,
        SOLANA_SPL_TOKEN_ACCOUNT_DATA_LENGTH,
    )
    if token_account_rent_lamports is not None:
        return token_account_rent_lamports

    logger.warning(
        "[TRADING][GASRESERVE][SOLANA][BUDGET] Token account rent exemption unavailable — "
        "blockchain_network=%s token_account_rent_lamports=%d token_account_rent=%s reason=rent_exemption_unavailable",
        BlockchainNetwork.SOLANA.value,
        DEFAULT_TOKEN_ACCOUNT_RENT_LAMPORTS,
        format_lamports_as_sol_text(DEFAULT_TOKEN_ACCOUNT_RENT_LAMPORTS),
    )
    return DEFAULT_TOKEN_ACCOUNT_RENT_LAMPORTS


def clear_solana_gas_reserve_cost_snapshot_cache() -> None:
    global _cached_solana_gas_reserve_cost_snapshot
    _cached_solana_gas_reserve_cost_snapshot = None


def build_solana_gas_reserve_cost_snapshot(
        *,
        force_refresh: bool = False,
) -> TradingGasReserveSolanaCostSnapshot:
    global _cached_solana_gas_reserve_cost_snapshot
    if not force_refresh and _cached_solana_gas_reserve_cost_snapshot is not None:
        return _cached_solana_gas_reserve_cost_snapshot

    with _cost_snapshot_cache_lock:
        if not force_refresh and _cached_solana_gas_reserve_cost_snapshot is not None:
            return _cached_solana_gas_reserve_cost_snapshot

        max_open_positions = settings.TRADING_MAX_OPEN_POSITIONS
        average_swap_fee_lamports = settings.TRADING_SOLANA_GAS_AVERAGE_SWAP_FEE_LAMPORTS
        token_account_rent_lamports = resolve_token_account_rent_lamports()
        per_position_cost_lamports = compute_per_position_cost_lamports(
            token_account_rent_lamports=token_account_rent_lamports,
            average_swap_fee_lamports=average_swap_fee_lamports,
        )
        cycle_cost_lamports = compute_cycle_cost_lamports(
            max_open_positions=max_open_positions,
            token_account_rent_lamports=token_account_rent_lamports,
            average_swap_fee_lamports=average_swap_fee_lamports,
        )

        logger.info(
            "[TRADING][GASRESERVE][SOLANA][BUDGET] Computed native SOL cycle cost for %d operations per position "
            "(ATA + entry + TP1 + TP2/SL) — blockchain_network=%s max_open_positions=%d "
            "per_position_cost_lamports=%d per_position_cost=%s cycle_cost_lamports=%d cycle_cost=%s",
            POSITION_LIFECYCLE_TRADE_COUNT + 1,
            BlockchainNetwork.SOLANA.value,
            max_open_positions,
            per_position_cost_lamports,
            format_lamports_as_sol_text(per_position_cost_lamports),
            cycle_cost_lamports,
            format_lamports_as_sol_text(cycle_cost_lamports),
        )

        _cached_solana_gas_reserve_cost_snapshot = TradingGasReserveSolanaCostSnapshot(
            max_open_positions=max_open_positions,
            token_account_rent_lamports=token_account_rent_lamports,
            average_swap_fee_lamports=average_swap_fee_lamports,
            per_position_cost_lamports=per_position_cost_lamports,
            cycle_cost_lamports=cycle_cost_lamports,
        )
        return _cached_solana_gas_reserve_cost_snapshot
