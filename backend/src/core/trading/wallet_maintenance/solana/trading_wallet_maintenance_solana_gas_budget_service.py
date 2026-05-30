from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.wallet_maintenance.solana.trading_wallet_maintenance_solana_structures import (
    TradingWalletMaintenanceSolanaGasBudgetSnapshot,
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

def build_solana_gas_budget_snapshot() -> TradingWalletMaintenanceSolanaGasBudgetSnapshot:
    max_open_positions = settings.TRADING_MAX_OPEN_POSITIONS
    average_swap_fee_lamports = settings.TRADING_SOLANA_GAS_AVERAGE_SWAP_FEE_LAMPORTS
    rpc_url = resolve_rpc_url_for_chain(BlockchainNetwork.SOLANA)
    token_account_rent_lamports = rpc_get_minimum_balance_for_rent_exemption(
        rpc_url,
        SOLANA_SPL_TOKEN_ACCOUNT_DATA_LENGTH,
    )
    if token_account_rent_lamports is None:
        token_account_rent_lamports = DEFAULT_TOKEN_ACCOUNT_RENT_LAMPORTS
        logger.warning(
            "[TRADING][WALLET_MAINTENANCE][SOLANA][GAS][BUDGET] Token account rent exemption unavailable — "
            "blockchain_network=%s token_account_rent_lamports=%d token_account_rent=%s",
            BlockchainNetwork.SOLANA.value,
            DEFAULT_TOKEN_ACCOUNT_RENT_LAMPORTS,
            format_lamports_as_sol_text(DEFAULT_TOKEN_ACCOUNT_RENT_LAMPORTS),
        )

    per_position_cost_lamports = token_account_rent_lamports + (POSITION_LIFECYCLE_TRADE_COUNT * average_swap_fee_lamports)
    cycle_cost_lamports = max_open_positions * per_position_cost_lamports
    refill_threshold_lamports = int(cycle_cost_lamports * settings.TRADING_SOLANA_GAS_REFILL_THRESHOLD_MULTIPLIER)
    refill_target_lamports = int(cycle_cost_lamports * settings.TRADING_SOLANA_GAS_REFILL_TARGET_MULTIPLIER)

    logger.info(
        "[TRADING][WALLET_MAINTENANCE][SOLANA][GAS][BUDGET] Computing native SOL reserve requirements for %d cycles "
        "of 4 operations per position (ATA + entry + TP1 + TP2/SL) — blockchain_network=%s max_open_positions=%d "
        "cycle_cost_lamports=%d cycle_cost=%s refill_threshold_lamports=%d refill_threshold=%s "
        "refill_target_lamports=%d refill_target=%s",
        settings.TRADING_SOLANA_GAS_REFILL_THRESHOLD_MULTIPLIER,
        BlockchainNetwork.SOLANA.value,
        max_open_positions,
        cycle_cost_lamports,
        format_lamports_as_sol_text(cycle_cost_lamports),
        refill_threshold_lamports,
        format_lamports_as_sol_text(refill_threshold_lamports),
        refill_target_lamports,
        format_lamports_as_sol_text(refill_target_lamports),
    )

    return TradingWalletMaintenanceSolanaGasBudgetSnapshot(
        max_open_positions=max_open_positions,
        token_account_rent_lamports=token_account_rent_lamports,
        average_swap_fee_lamports=average_swap_fee_lamports,
        cycle_cost_lamports=cycle_cost_lamports,
        refill_threshold_lamports=refill_threshold_lamports,
        refill_target_lamports=refill_target_lamports,
    )
