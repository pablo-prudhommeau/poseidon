from __future__ import annotations

import base64

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.execution.trading_executor import SWAP_EXECUTION_LOCK
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_gas_budget_service import (
    build_solana_gas_budget_snapshot,
)
from src.core.trading.walletmaintenance.trading_wallet_maintenance_structures import (
    TradingWalletMaintenanceChainGasResult,
    TradingWalletMaintenanceOperationStatus,
)
from src.integrations.blockchain.blockchain_free_cash_service import (
    _fetch_solana_stablecoin_balance,
    _get_stablecoin_address_for_blockchain,
)
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
from src.integrations.blockchain.solana.solana_rpc_client import (
    fetch_solana_native_balance_lamports,
    format_lamports_as_sol_text,
    poll_solana_native_balance_after_increase,
    resolve_sol_usd_price,
)
from src.integrations.blockchain.solana.solana_structures import SOLANA_WRAPPED_SOL_MINT
from src.integrations.jupiter.jupiter_client import generate_jupiter_swap_transaction
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

SOLANA_STABLECOIN_DECIMALS = 6


def _format_stablecoin_raw_as_usd_text(stablecoin_raw: int) -> str:
    stablecoin_amount = float(stablecoin_raw) / float(10 ** SOLANA_STABLECOIN_DECIMALS)
    return f"{stablecoin_amount:.4f} {settings.TRADING_STABLECOIN_SYMBOL}"


def _format_stablecoin_usd_text(stablecoin_amount_usd: float) -> str:
    return f"{stablecoin_amount_usd:.4f} {settings.TRADING_STABLECOIN_SYMBOL}"


def run_solana_native_gas_refill() -> TradingWalletMaintenanceChainGasResult:
    blockchain_network = BlockchainNetwork.SOLANA
    budget_snapshot = build_solana_gas_budget_snapshot()
    rpc_url = resolve_rpc_url_for_chain(blockchain_network)

    try:
        signer = build_default_solana_signer()
        wallet_address = signer.address
    except Exception:
        logger.exception(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Signer unavailable — "
            "blockchain_network=%s reason=signer_unavailable",
            blockchain_network.value,
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="signer_unavailable",
        )

    native_balance_before_lamports = fetch_solana_native_balance_lamports(rpc_url, wallet_address)
    if native_balance_before_lamports is None:
        logger.warning(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Failed to read native balance — "
            "blockchain_network=%s wallet_address=%s reason=native_balance_unavailable",
            blockchain_network.value,
            wallet_address,
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="native_balance_unavailable",
        )

    if native_balance_before_lamports >= budget_snapshot.refill_threshold_lamports:
        logger.debug(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Refill not required — "
            "blockchain_network=%s wallet_address=%s native_balance_before=%s refill_threshold=%s "
            "reason=native_balance_above_threshold",
            blockchain_network.value,
            wallet_address,
            format_lamports_as_sol_text(native_balance_before_lamports),
            format_lamports_as_sol_text(budget_snapshot.refill_threshold_lamports),
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.NOT_REQUIRED,
            reason="native_balance_above_threshold",
            native_balance_before_lamports=native_balance_before_lamports,
            native_balance_after_lamports=native_balance_before_lamports,
        )

    refill_delta_lamports = budget_snapshot.refill_target_lamports - native_balance_before_lamports
    if refill_delta_lamports <= 0:
        logger.debug(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Refill not required — "
            "blockchain_network=%s wallet_address=%s native_balance_before=%s refill_target=%s "
            "reason=native_balance_above_target",
            blockchain_network.value,
            wallet_address,
            format_lamports_as_sol_text(native_balance_before_lamports),
            format_lamports_as_sol_text(budget_snapshot.refill_target_lamports),
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.NOT_REQUIRED,
            reason="native_balance_above_target",
            native_balance_before_lamports=native_balance_before_lamports,
            native_balance_after_lamports=native_balance_before_lamports,
        )

    sol_usd_price = resolve_sol_usd_price(rpc_url)
    if sol_usd_price is None or sol_usd_price <= 0.0:
        logger.warning(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] SOL/USD price unavailable — "
            "blockchain_network=%s wallet_address=%s reason=sol_usd_price_unavailable",
            blockchain_network.value,
            wallet_address,
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="sol_usd_price_unavailable",
            native_balance_before_lamports=native_balance_before_lamports,
        )

    stablecoin_address = _get_stablecoin_address_for_blockchain(blockchain_network)
    stablecoin_balance = _fetch_solana_stablecoin_balance(rpc_url, wallet_address, stablecoin_address)
    available_stablecoin_usd = max(0.0, stablecoin_balance - settings.TRADING_MIN_FREE_CASH_USD)
    if available_stablecoin_usd <= 0.0:
        logger.warning(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Refill blocked — "
            "blockchain_network=%s wallet_address=%s stablecoin_balance_usd=%s "
            "min_free_cash_buffer_usd=%s available_stablecoin_usd=%s reason=insufficient_stablecoin_for_refill",
            blockchain_network.value,
            wallet_address,
            _format_stablecoin_usd_text(stablecoin_balance),
            _format_stablecoin_usd_text(settings.TRADING_MIN_FREE_CASH_USD),
            _format_stablecoin_usd_text(available_stablecoin_usd),
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="insufficient_stablecoin_for_refill",
            native_balance_before_lamports=native_balance_before_lamports,
        )

    required_stablecoin_usd = (float(refill_delta_lamports) / 1_000_000_000.0) * sol_usd_price
    stablecoin_spend_usd = min(required_stablecoin_usd, available_stablecoin_usd)
    stablecoin_spend_raw = int(stablecoin_spend_usd * (10 ** SOLANA_STABLECOIN_DECIMALS))
    if stablecoin_spend_raw <= 0:
        logger.warning(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Refill blocked — "
            "blockchain_network=%s wallet_address=%s stablecoin_spend_usd=%s reason=stablecoin_spend_amount_zero",
            blockchain_network.value,
            wallet_address,
            _format_stablecoin_usd_text(stablecoin_spend_usd),
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="stablecoin_spend_amount_zero",
            native_balance_before_lamports=native_balance_before_lamports,
        )

    logger.info(
        "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Starting native SOL refill via stablecoin swap for %d cycles "
        "of 4 operations per position (ATA + entry + TP1 + TP2/SL) — blockchain_network=%s wallet_address=%s max_open_positions=%d "
        "native_balance_before=%s refill_target=%s stablecoin_spend_usd=%s "
        "min_free_cash_buffer_usd=%s",
        settings.TRADING_SOLANA_GAS_MINIMUM_CYCLE_NUMBER,
        blockchain_network.value,
        wallet_address,
        budget_snapshot.max_open_positions,
        format_lamports_as_sol_text(native_balance_before_lamports),
        format_lamports_as_sol_text(budget_snapshot.refill_target_lamports),
        _format_stablecoin_raw_as_usd_text(stablecoin_spend_raw),
        _format_stablecoin_usd_text(settings.TRADING_MIN_FREE_CASH_USD),
    )

    slippage_basis_points = int(settings.TRADING_SLIPPAGE_TOLERANCE * 10000)
    try:
        with SWAP_EXECUTION_LOCK:
            base64_transaction = generate_jupiter_swap_transaction(
                source_address=wallet_address,
                input_mint=stablecoin_address,
                output_mint=SOLANA_WRAPPED_SOL_MINT,
                amount_in_lamports=stablecoin_spend_raw,
                slippage_basis_points=slippage_basis_points,
            )
            serialized_transaction = base64.b64decode(base64_transaction)
            transaction_signature = signer.send_raw_transaction(serialized_transaction)
            is_confirmed = signer.confirm_transaction(transaction_signature, 45)
            if not is_confirmed:
                raise RuntimeError(f"Refill transaction {transaction_signature} failed confirmation")
    except Exception:
        logger.exception(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Refill execution failed — "
            "blockchain_network=%s wallet_address=%s stablecoin_spend_usd=%s reason=refill_execution_failed",
            blockchain_network.value,
            wallet_address,
            _format_stablecoin_raw_as_usd_text(stablecoin_spend_raw),
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="refill_execution_failed",
            native_balance_before_lamports=native_balance_before_lamports,
            stablecoin_spent_raw=stablecoin_spend_raw,
        )

    native_balance_after_lamports = poll_solana_native_balance_after_increase(
        rpc_url=rpc_url,
        wallet_address=wallet_address,
        balance_before_lamports=native_balance_before_lamports,
    )
    if native_balance_after_lamports is None:
        native_balance_after_lamports = native_balance_before_lamports

    native_balance_delta_lamports = native_balance_after_lamports - native_balance_before_lamports
    if native_balance_delta_lamports <= 0:
        logger.warning(
            "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Refill confirmed on-chain but native balance unchanged after polling — "
            "blockchain_network=%s wallet_address=%s transaction_signature=%s "
            "native_balance_before=%s native_balance_after=%s stablecoin_spend_usd=%s "
            "reason=native_balance_unchanged_after_refill",
            blockchain_network.value,
            wallet_address,
            transaction_signature,
            format_lamports_as_sol_text(native_balance_before_lamports),
            format_lamports_as_sol_text(native_balance_after_lamports),
            _format_stablecoin_raw_as_usd_text(stablecoin_spend_raw),
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.FAILED,
            reason="native_balance_unchanged_after_refill",
            native_balance_before_lamports=native_balance_before_lamports,
            native_balance_after_lamports=native_balance_after_lamports,
            refill_transaction_signature=transaction_signature,
            stablecoin_spent_raw=stablecoin_spend_raw,
        )

    logger.info(
        "[TRADING][WALLETMAINTENANCE][SOLANA][GAS][REFILL] Native SOL refill completed successfully — "
        "blockchain_network=%s wallet_address=%s transaction_signature=%s native_balance_before=%s "
        "native_balance_after=%s native_balance_delta_lamports=%d stablecoin_spend_usd=%s reason=refill_executed",
        blockchain_network.value,
        wallet_address,
        transaction_signature,
        format_lamports_as_sol_text(native_balance_before_lamports),
        format_lamports_as_sol_text(native_balance_after_lamports),
        native_balance_delta_lamports,
        _format_stablecoin_raw_as_usd_text(stablecoin_spend_raw),
    )

    return TradingWalletMaintenanceChainGasResult(
        blockchain_network=blockchain_network,
        status=TradingWalletMaintenanceOperationStatus.SUCCESS,
        reason="refill_executed",
        native_balance_before_lamports=native_balance_before_lamports,
        native_balance_after_lamports=native_balance_after_lamports,
        refill_transaction_signature=transaction_signature,
        stablecoin_spent_raw=stablecoin_spend_raw,
    )
