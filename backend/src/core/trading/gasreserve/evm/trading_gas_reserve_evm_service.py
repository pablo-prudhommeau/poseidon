from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.evm.trading_gas_reserve_evm_structures import EvmOnchainWalletContext
from src.core.trading.gasreserve.trading_gas_reserve_structures import (
    BlockchainCashBalanceGasReserveEnrichment,
    GasRefillLockedBreakdownSnapshot,
    GasRefillLockedStablecoinSnapshot,
    WalletAuxiliaryAssetsSnapshot,
)
from src.integrations.blockchain.blockchain_free_cash_service import fetch_stablecoin_balance_for_blockchain
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

POSITION_LIFECYCLE_TRADE_COUNT = 3


def resolve_evm_onchain_wallet_context(blockchain_network: BlockchainNetwork) -> EvmOnchainWalletContext:
    cash_balance = fetch_stablecoin_balance_for_blockchain(blockchain_network, force_refresh=True)
    native_token_balance_wei = int(cash_balance.native_token_balance_raw * (10**18))
    logger.debug(
        "[TRADING][GASRESERVE][EVM][WALLET] Resolved wallet context — blockchain_network=%s "
        "native_wei=%d stablecoin=%.4f native_usd=%.4f",
        blockchain_network.value,
        native_token_balance_wei,
        cash_balance.balance_raw,
        cash_balance.native_token_balance_usd,
    )
    return EvmOnchainWalletContext(
        blockchain_network=blockchain_network,
        wallet_address=cash_balance.wallet_address,
        native_token_balance_wei=native_token_balance_wei,
        native_token_balance_usd=cash_balance.native_token_balance_usd,
        stablecoin_balance_raw=cash_balance.balance_raw,
    )


def _compute_per_position_cost_wei() -> int:
    return settings.TRADING_EVM_GAS_AVERAGE_SWAP_FEE_WEI * POSITION_LIFECYCLE_TRADE_COUNT


def _compute_cycle_cost_wei() -> int:
    return _compute_per_position_cost_wei() * settings.TRADING_MAX_OPEN_POSITIONS


def is_evm_gas_reserve_sufficient_for_buy(wallet_context: EvmOnchainWalletContext) -> bool:
    required_native_reserve_wei = _compute_cycle_cost_wei() * settings.TRADING_GAS_MINIMUM_CYCLE_NUMBER
    is_sufficient = wallet_context.native_token_balance_wei >= required_native_reserve_wei
    if not is_sufficient:
        logger.info(
            "[TRADING][GASRESERVE][EVM][GUARD] Buy blocked — native balance below gas reserve — "
            "blockchain_network=%s native_wei=%d required_wei=%d reason=INSUFFICIENT_GAS_RESERVE",
            wallet_context.blockchain_network.value,
            wallet_context.native_token_balance_wei,
            required_native_reserve_wei,
        )
    return is_sufficient


def compute_evm_gas_refill_locked_stablecoin_snapshot(
        wallet_context: EvmOnchainWalletContext,
) -> GasRefillLockedStablecoinSnapshot:
    return GasRefillLockedStablecoinSnapshot(
        blockchain_network=wallet_context.blockchain_network,
        gas_refill_locked_stablecoin_usd=0.0,
    )


def compute_evm_wallet_auxiliary_assets_snapshot(
        wallet_context: EvmOnchainWalletContext,
) -> WalletAuxiliaryAssetsSnapshot:
    return WalletAuxiliaryAssetsSnapshot(
        blockchain_network=wallet_context.blockchain_network,
        native_token_balance_usd=wallet_context.native_token_balance_usd,
        gas_refill_locked_stablecoin_usd=0.0,
        recoverable_wallet_capital_usd=0.0,
    )


def build_evm_blockchain_cash_balance_gas_reserve_enrichment(
        wallet_context: EvmOnchainWalletContext,
) -> BlockchainCashBalanceGasReserveEnrichment:
    cycle_cost_wei = _compute_cycle_cost_wei()
    per_position_cost_wei = _compute_per_position_cost_wei()
    refill_target_cycle_count = settings.TRADING_GAS_REFILL_TARGET_CYCLE_NUMBER
    refill_trigger_cycle_count = settings.TRADING_GAS_MINIMUM_CYCLE_NUMBER
    native_balance_ether = wallet_context.native_token_balance_wei / float(10**18)
    cycle_cost_ether = cycle_cost_wei / float(10**18)
    per_position_cost_ether = per_position_cost_wei / float(10**18)
    native_price_usd = (
        wallet_context.native_token_balance_usd / native_balance_ether
        if native_balance_ether > 0.0
        else 0.0
    )

    breakdown = GasRefillLockedBreakdownSnapshot(
        per_position_cycle_cost_usd=per_position_cost_ether * native_price_usd,
        per_position_cycle_cost_native_raw=per_position_cost_ether,
        max_open_positions=settings.TRADING_MAX_OPEN_POSITIONS,
        portfolio_cycle_cost_usd=cycle_cost_ether * native_price_usd,
        portfolio_cycle_cost_native_raw=cycle_cost_ether,
        refill_target_cycle_count=refill_target_cycle_count,
        refill_target_budget_usd=cycle_cost_ether * refill_target_cycle_count * native_price_usd,
        refill_target_budget_native_raw=cycle_cost_ether * refill_target_cycle_count,
        native_gas_balance_usd=wallet_context.native_token_balance_usd,
        native_gas_balance_raw=native_balance_ether,
        refill_trigger_cycle_count=refill_trigger_cycle_count,
        refill_trigger_threshold_usd=cycle_cost_ether * refill_trigger_cycle_count * native_price_usd,
        refill_trigger_threshold_native_raw=cycle_cost_ether * refill_trigger_cycle_count,
        locked_stablecoin_usd=0.0,
    )
    return BlockchainCashBalanceGasReserveEnrichment(
        gas_refill_locked_stablecoin_usd=0.0,
        gas_refill_locked_breakdown=breakdown,
        solana_token_account_rent=None,
    )


def is_evm_gas_reserve_sufficient_for_buy_on_blockchain(blockchain_network: BlockchainNetwork) -> bool:
    wallet_context = resolve_evm_onchain_wallet_context(blockchain_network)
    return is_evm_gas_reserve_sufficient_for_buy(wallet_context)
