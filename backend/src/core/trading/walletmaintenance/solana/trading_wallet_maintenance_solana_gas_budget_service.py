from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_helpers import (
    build_solana_gas_reserve_cost_snapshot,
    compute_reserve_lamports,
)
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_structures import (
    TradingWalletMaintenanceSolanaGasBudgetSnapshot,
)
from src.integrations.blockchain.solana.solana_rpc_client import format_lamports_as_sol_text
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def build_solana_gas_budget_snapshot() -> TradingWalletMaintenanceSolanaGasBudgetSnapshot:
    cost_snapshot = build_solana_gas_reserve_cost_snapshot()
    minimum_cycle_number = settings.TRADING_SOLANA_GAS_MINIMUM_CYCLE_NUMBER
    refill_target_cycle_number = settings.TRADING_SOLANA_GAS_REFILL_TARGET_CYCLE_NUMBER
    refill_threshold_lamports = compute_reserve_lamports(
        cycle_cost_lamports=cost_snapshot.cycle_cost_lamports,
        cycle_count=minimum_cycle_number,
    )
    refill_target_lamports = compute_reserve_lamports(
        cycle_cost_lamports=cost_snapshot.cycle_cost_lamports,
        cycle_count=refill_target_cycle_number,
    )

    logger.info(
        "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][BUDGET] Computing native SOL refill thresholds — "
        "blockchain_network=%s max_open_positions=%d minimum_cycle_number=%d refill_target_cycle_number=%d "
        "cycle_cost_lamports=%d cycle_cost=%s refill_threshold_lamports=%d refill_threshold=%s "
        "refill_target_lamports=%d refill_target=%s",
        BlockchainNetwork.SOLANA.value,
        cost_snapshot.max_open_positions,
        minimum_cycle_number,
        refill_target_cycle_number,
        cost_snapshot.cycle_cost_lamports,
        format_lamports_as_sol_text(cost_snapshot.cycle_cost_lamports),
        refill_threshold_lamports,
        format_lamports_as_sol_text(refill_threshold_lamports),
        refill_target_lamports,
        format_lamports_as_sol_text(refill_target_lamports),
    )

    return TradingWalletMaintenanceSolanaGasBudgetSnapshot(
        max_open_positions=cost_snapshot.max_open_positions,
        token_account_rent_lamports=cost_snapshot.token_account_rent_lamports,
        average_swap_fee_lamports=cost_snapshot.average_swap_fee_lamports,
        cycle_cost_lamports=cost_snapshot.cycle_cost_lamports,
        refill_threshold_lamports=refill_threshold_lamports,
        refill_target_lamports=refill_target_lamports,
    )
