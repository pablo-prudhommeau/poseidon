from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.wallet_maintenance.evm.trading_wallet_maintenance_evm_handler import (
    TradingWalletMaintenanceEvmHandler,
)
from src.core.trading.wallet_maintenance.solana.trading_wallet_maintenance_solana_handler import (
    TradingWalletMaintenanceSolanaHandler,
)
from src.core.trading.wallet_maintenance.trading_wallet_maintenance_chain_handler import (
    TradingWalletMaintenanceChainHandler,
)
from src.core.trading.wallet_maintenance.trading_wallet_maintenance_notification_service import (
    dispatch_wallet_maintenance_alerts,
)
from src.core.trading.wallet_maintenance.trading_wallet_maintenance_structures import (
    TradingNativeGasThresholdSnapshot,
    TradingWalletMaintenanceCycleSummary,
)
from src.integrations.blockchain.blockchain_free_cash_service import _fetch_evm_native_balance
from src.integrations.blockchain.blockchain_rpc_registry import resolve_rpc_url_for_chain
from src.integrations.blockchain.evm.blockchain_evm_signer import build_default_evm_signer
from src.integrations.blockchain.solana.blockchain_solana_signer import build_default_solana_signer
from src.integrations.blockchain.solana.solana_rpc_client import fetch_solana_native_balance_lamports
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

EVM_BLOCKCHAIN_NETWORKS = {
    BlockchainNetwork.BSC,
    BlockchainNetwork.BASE,
    BlockchainNetwork.AVALANCHE,
}


def resolve_wallet_maintenance_chain_handlers() -> list[TradingWalletMaintenanceChainHandler]:
    if settings.PAPER_MODE or not settings.TRADING_WALLET_MAINTENANCE_ENABLED:
        return []

    handlers: list[TradingWalletMaintenanceChainHandler] = []
    for chain_name in settings.TRADING_ALLOWED_CHAINS:
        normalized_chain_name = chain_name.strip().lower()
        try:
            blockchain_network = BlockchainNetwork(normalized_chain_name)
        except ValueError:
            logger.warning(
                "[TRADING][WALLET_MAINTENANCE][SERVICE] Unknown allowed chain ignored — "
                "configured_chain_name=%s reason=unknown_allowed_chain",
                normalized_chain_name,
            )
            continue

        if blockchain_network == BlockchainNetwork.SOLANA:
            handlers.append(TradingWalletMaintenanceSolanaHandler())
            continue

        if blockchain_network in EVM_BLOCKCHAIN_NETWORKS:
            handlers.append(TradingWalletMaintenanceEvmHandler(blockchain_network=blockchain_network))

    return handlers


def run_wallet_maintenance_cycle() -> TradingWalletMaintenanceCycleSummary:
    handlers = resolve_wallet_maintenance_chain_handlers()
    gas_results = []
    reclaim_results = []

    if not handlers:
        logger.debug(
            "[TRADING][WALLET_MAINTENANCE][SERVICE] No active chain handlers for maintenance cycle — "
            "reason=no_active_chain_handlers"
        )
        return TradingWalletMaintenanceCycleSummary(gas_results=gas_results, reclaim_results=reclaim_results)

    for handler in handlers:
        blockchain_network = handler.blockchain_network()
        try:
            gas_result = handler.run_native_gas_maintenance()
            gas_results.append(gas_result)
        except Exception:
            logger.exception(
                "[TRADING][WALLET_MAINTENANCE][SERVICE] Native gas maintenance failed — "
                "blockchain_network=%s",
                blockchain_network.value,
            )

        try:
            reclaim_result = handler.run_dormant_account_reclaim()
            reclaim_results.append(reclaim_result)
        except Exception:
            logger.exception(
                "[TRADING][WALLET_MAINTENANCE][SERVICE] Dormant account reclaim failed — "
                "blockchain_network=%s",
                blockchain_network.value,
            )

    cycle_summary = TradingWalletMaintenanceCycleSummary(
        gas_results=gas_results,
        reclaim_results=reclaim_results,
    )
    dispatch_wallet_maintenance_alerts(cycle_summary)
    return cycle_summary


def resolve_native_gas_threshold_for_buy_guard(
        blockchain_network: BlockchainNetwork,
) -> TradingNativeGasThresholdSnapshot | None:
    if settings.PAPER_MODE or not settings.TRADING_WALLET_MAINTENANCE_ENABLED:
        return None

    for handler in resolve_wallet_maintenance_chain_handlers():
        if handler.blockchain_network() != blockchain_network:
            continue
        return handler.resolve_native_gas_threshold_for_buy_guard()
    return None


def is_native_gas_sufficient_for_buy(blockchain_network: BlockchainNetwork) -> bool:
    threshold_snapshot = resolve_native_gas_threshold_for_buy_guard(blockchain_network)
    if threshold_snapshot is None:
        return True

    native_balance_raw = _fetch_native_balance_raw(blockchain_network)
    if native_balance_raw is None:
        logger.warning(
            "[TRADING][WALLET_MAINTENANCE][SERVICE] Native balance unavailable for buy guard — "
            "blockchain_network=%s reason=native_balance_unavailable",
            blockchain_network.value,
        )
        return False

    threshold_sol = float(threshold_snapshot.threshold_raw_lamports) / 1_000_000_000.0
    is_sufficient = native_balance_raw >= threshold_sol
    if not is_sufficient:
        logger.info(
            "[TRADING][WALLET_MAINTENANCE][SERVICE] Buy blocked — native balance below maintenance threshold — "
            "blockchain_network=%s native_balance=%.6f %s maintenance_threshold=%.6f %s "
            "reason=native_balance_below_maintenance_threshold",
            blockchain_network.value,
            native_balance_raw,
            threshold_snapshot.native_token_symbol,
            threshold_sol,
            threshold_snapshot.native_token_symbol,
        )
    return is_sufficient


def _fetch_native_balance_raw(blockchain_network: BlockchainNetwork) -> float | None:
    rpc_url = resolve_rpc_url_for_chain(blockchain_network)
    if blockchain_network == BlockchainNetwork.SOLANA:
        try:
            wallet_address = build_default_solana_signer().address
        except Exception:
            logger.exception(
                "[TRADING][WALLET_MAINTENANCE][SERVICE] Solana signer unavailable for buy guard — "
                "blockchain_network=%s reason=signer_unavailable",
                blockchain_network.value,
            )
            return None
        lamports = fetch_solana_native_balance_lamports(rpc_url, wallet_address)
        if lamports is None:
            return None
        return float(lamports) / 1_000_000_000.0

    if blockchain_network in EVM_BLOCKCHAIN_NETWORKS:
        try:
            wallet_address = build_default_evm_signer(chain=blockchain_network).wallet_address
        except Exception:
            logger.exception(
                "[TRADING][WALLET_MAINTENANCE][SERVICE] EVM signer unavailable for buy guard — "
                "blockchain_network=%s reason=signer_unavailable",
                blockchain_network.value,
            )
            return None
        return _fetch_evm_native_balance(rpc_url, wallet_address)

    return None
