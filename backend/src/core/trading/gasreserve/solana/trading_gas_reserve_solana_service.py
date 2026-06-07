from __future__ import annotations

from typing import Optional

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.gasreserve.solana.trading_gas_reserve_solana_helpers import (
    BUY_GUARD_RESERVE_CYCLE_COUNT,
    build_solana_gas_reserve_cost_snapshot,
    compute_per_position_cost_lamports,
    compute_reserve_lamports,
)
from src.core.trading.gasreserve.trading_gas_reserve_structures import (
    GasRefillLockedBreakdownSnapshot,
    GasRefillLockedStablecoinSnapshot,
    WalletAuxiliaryAssetsSnapshot,
)
from src.core.trading.portfolio.trading_portfolio_solana_wallet_auxiliary_service import (
    resolve_solana_locked_token_account_capital_usd,
)
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_gas_budget_service import (
    build_solana_gas_budget_snapshot,
)
from src.core.utils.math_utils import decimal_from_primitive, quantize_2dp
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
from src.integrations.jupiter.jupiter_client import resolve_sol_usd_price
from src.integrations.blockchain.solana.solana_rpc_client import (
    fetch_solana_native_balance_lamports,
    format_lamports_as_sol_text,
)
from src.integrations.blockchain.solana.solana_structures import SolanaOnchainWalletContext
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def is_solana_gas_reserve_sufficient_for_buy() -> bool:
    cost_snapshot = build_solana_gas_reserve_cost_snapshot()
    required_native_reserve_raw = compute_reserve_lamports(
        cycle_cost_lamports=cost_snapshot.cycle_cost_lamports,
        cycle_count=BUY_GUARD_RESERVE_CYCLE_COUNT,
    )

    native_balance_raw = _fetch_solana_native_balance_raw()
    if native_balance_raw is None:
        logger.warning(
            "[TRADING][GASRESERVE][SOLANA][GUARD] Buy blocked — native balance unavailable — "
            "blockchain_network=%s reason=native_balance_unavailable",
            BlockchainNetwork.SOLANA.value,
        )
        return False

    is_sufficient = native_balance_raw >= required_native_reserve_raw
    if not is_sufficient:
        logger.info(
            "[TRADING][GASRESERVE][SOLANA][GUARD] Buy blocked — native balance below gas reserve — "
            "blockchain_network=%s native_balance=%s required_reserve=%s cycle_cost=%s "
            "reason=INSUFFICIENT_GAS_RESERVE",
            BlockchainNetwork.SOLANA.value,
            format_lamports_as_sol_text(native_balance_raw),
            format_lamports_as_sol_text(required_native_reserve_raw),
            format_lamports_as_sol_text(cost_snapshot.cycle_cost_lamports),
        )
    return is_sufficient


def _fetch_solana_native_balance_raw() -> int | None:
    blockchain_network = BlockchainNetwork.SOLANA
    rpc_url = resolve_rpc_url_for_chain(blockchain_network)
    try:
        wallet_address = build_default_solana_signer().address
    except Exception:
        logger.exception(
            "[TRADING][GASRESERVE][SOLANA][GUARD] Signer unavailable — "
            "blockchain_network=%s reason=signer_unavailable",
            blockchain_network.value,
        )
        return None

    return fetch_solana_native_balance_lamports(rpc_url, wallet_address)


def compute_solana_gas_refill_locked_stablecoin_snapshot(
        wallet_context: SolanaOnchainWalletContext,
) -> GasRefillLockedStablecoinSnapshot:
    locked_stablecoin_usd = compute_gas_refill_locked_stablecoin_usd_from_wallet_context(
        wallet_context=wallet_context,
    )
    logger.debug(
        "[TRADING][GASRESERVE][SOLANA][LOCKED] Computed gas refill locked stablecoin snapshot — "
        "blockchain_network=%s locked_stablecoin_usd=%.2f native_sol=%.6f",
        BlockchainNetwork.SOLANA.value,
        locked_stablecoin_usd,
        wallet_context.native_token_balance_raw,
    )
    return GasRefillLockedStablecoinSnapshot(
        blockchain_network=BlockchainNetwork.SOLANA,
        gas_refill_locked_stablecoin_usd=locked_stablecoin_usd,
    )


def compute_solana_wallet_auxiliary_assets_snapshot(
        wallet_context: SolanaOnchainWalletContext,
) -> WalletAuxiliaryAssetsSnapshot:
    locked_stablecoin_usd = compute_gas_refill_locked_stablecoin_usd_from_wallet_context(
        wallet_context=wallet_context,
    )
    recoverable_wallet_capital_usd = resolve_solana_locked_token_account_capital_usd(
        wallet_context.rent_breakdown,
    )
    return WalletAuxiliaryAssetsSnapshot(
        blockchain_network=BlockchainNetwork.SOLANA,
        native_token_balance_usd=wallet_context.native_token_balance_usd,
        gas_refill_locked_stablecoin_usd=locked_stablecoin_usd,
        recoverable_wallet_capital_usd=recoverable_wallet_capital_usd,
    )


def compute_gas_refill_locked_stablecoin_usd_from_wallet_context(
        wallet_context: SolanaOnchainWalletContext,
) -> float:
    budget_snapshot = build_solana_gas_budget_snapshot()
    refill_target_lamports = budget_snapshot.refill_target_lamports
    if refill_target_lamports <= 0:
        return 0.0

    native_token_usd_price = _resolve_native_token_usd_price(wallet_context=wallet_context)
    if native_token_usd_price is None or native_token_usd_price <= 0.0:
        logger.debug(
            "[TRADING][GASRESERVE][SOLANA][LOCKED] Native token USD price unavailable — "
            "blockchain_network=%s reason=native_token_usd_price_unavailable",
            BlockchainNetwork.SOLANA.value,
        )
        return 0.0

    locked_stablecoin_usd = _convert_lamports_to_usd(
        lamports=refill_target_lamports,
        native_token_usd_price=native_token_usd_price,
    )
    return float(quantize_2dp(decimal_from_primitive(locked_stablecoin_usd)))


def build_solana_gas_refill_locked_breakdown(
        wallet_context: SolanaOnchainWalletContext,
) -> GasRefillLockedBreakdownSnapshot:
    budget_snapshot = build_solana_gas_budget_snapshot()
    per_position_cost_lamports = compute_per_position_cost_lamports(
        token_account_rent_lamports=budget_snapshot.token_account_rent_lamports,
        average_swap_fee_lamports=budget_snapshot.average_swap_fee_lamports,
    )
    native_token_usd_price = _resolve_native_token_usd_price(wallet_context=wallet_context)
    if native_token_usd_price is None or native_token_usd_price <= 0.0:
        native_token_usd_price = 0.0

    per_position_cycle_cost_native_raw = _convert_lamports_to_native_raw(
        per_position_cost_lamports,
    )
    portfolio_cycle_cost_native_raw = _convert_lamports_to_native_raw(
        budget_snapshot.cycle_cost_lamports,
    )
    refill_target_budget_native_raw = _convert_lamports_to_native_raw(
        budget_snapshot.refill_target_lamports,
    )
    refill_trigger_threshold_native_raw = _convert_lamports_to_native_raw(
        budget_snapshot.refill_threshold_lamports,
    )
    locked_stablecoin_usd = compute_gas_refill_locked_stablecoin_usd_from_wallet_context(
        wallet_context=wallet_context,
    )

    return GasRefillLockedBreakdownSnapshot(
        per_position_cycle_cost_usd=_quantize_usd_from_lamports(
            per_position_cost_lamports,
            native_token_usd_price,
        ),
        per_position_cycle_cost_native_raw=per_position_cycle_cost_native_raw,
        max_open_positions=budget_snapshot.max_open_positions,
        portfolio_cycle_cost_usd=_quantize_usd_from_lamports(
            budget_snapshot.cycle_cost_lamports,
            native_token_usd_price,
        ),
        portfolio_cycle_cost_native_raw=portfolio_cycle_cost_native_raw,
        refill_target_cycle_count=settings.TRADING_GAS_REFILL_TARGET_CYCLE_NUMBER,
        refill_target_budget_usd=_quantize_usd_from_lamports(
            budget_snapshot.refill_target_lamports,
            native_token_usd_price,
        ),
        refill_target_budget_native_raw=refill_target_budget_native_raw,
        native_gas_balance_usd=float(
            quantize_2dp(decimal_from_primitive(wallet_context.native_token_balance_usd)),
        ),
        native_gas_balance_raw=wallet_context.native_token_balance_raw,
        refill_trigger_cycle_count=settings.TRADING_GAS_MINIMUM_CYCLE_NUMBER,
        refill_trigger_threshold_usd=_quantize_usd_from_lamports(
            budget_snapshot.refill_threshold_lamports,
            native_token_usd_price,
        ),
        refill_trigger_threshold_native_raw=refill_trigger_threshold_native_raw,
        locked_stablecoin_usd=locked_stablecoin_usd,
    )


def _convert_lamports_to_native_raw(lamports: int) -> float:
    return float(lamports) / 1_000_000_000.0


def _convert_lamports_to_usd(lamports: int, native_token_usd_price: float) -> float:
    return _convert_lamports_to_native_raw(lamports) * native_token_usd_price


def _quantize_usd_from_lamports(lamports: int, native_token_usd_price: float) -> float:
    return float(
        quantize_2dp(decimal_from_primitive(_convert_lamports_to_usd(lamports, native_token_usd_price))),
    )


def _resolve_native_token_usd_price(wallet_context: SolanaOnchainWalletContext) -> Optional[float]:
    if wallet_context.native_token_balance_raw > 0.0:
        return wallet_context.native_token_balance_usd / wallet_context.native_token_balance_raw
    return resolve_sol_usd_price()
