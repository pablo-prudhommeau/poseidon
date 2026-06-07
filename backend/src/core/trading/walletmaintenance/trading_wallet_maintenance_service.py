from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.trading_chain_capability_service import (
    resolve_trading_allowed_blockchain_networks,
)
from src.core.trading.walletmaintenance.solana.trading_wallet_maintenance_solana_handler import (
    TradingWalletMaintenanceSolanaHandler,
)
from src.core.trading.walletmaintenance.trading_wallet_maintenance_chain_handler import (
    TradingWalletMaintenanceChainHandler,
)
from src.core.trading.walletmaintenance.trading_wallet_maintenance_notification_service import (
    dispatch_wallet_maintenance_alerts,
)
from src.core.trading.walletmaintenance.trading_wallet_maintenance_structures import (
    TradingWalletMaintenanceChainGasResult,
    TradingWalletMaintenanceChainReclaimResult,
    TradingWalletMaintenanceCycleSummary,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def resolve_wallet_maintenance_chain_handlers() -> list[
    TradingWalletMaintenanceChainHandler
]:
    if settings.PAPER_MODE or not settings.TRADING_WALLET_MAINTENANCE_ENABLED:
        return []

    handlers: list[TradingWalletMaintenanceChainHandler] = []
    for blockchain_network in resolve_trading_allowed_blockchain_networks():
        if blockchain_network == BlockchainNetwork.SOLANA:
            handlers.append(TradingWalletMaintenanceSolanaHandler())
    return handlers


def run_wallet_maintenance_cycle() -> TradingWalletMaintenanceCycleSummary:
    handlers = resolve_wallet_maintenance_chain_handlers()
    gas_results: list[TradingWalletMaintenanceChainGasResult] = []
    reclaim_results: list[TradingWalletMaintenanceChainReclaimResult] = []

    if not handlers:
        logger.debug(
            "[TRADING][WALLETMAINTENANCE][SERVICE] No active chain handlers for maintenance cycle — "
            "reason=no_active_chain_handlers"
        )
        return TradingWalletMaintenanceCycleSummary(
            gas_results=gas_results, reclaim_results=reclaim_results
        )

    for handler in handlers:
        blockchain_network = handler.blockchain_network()
        try:
            gas_result = handler.run_native_gas_maintenance()
            gas_results.append(gas_result)
        except Exception:
            logger.exception(
                "[TRADING][WALLETMAINTENANCE][SERVICE] Native gas maintenance failed — "
                "blockchain_network=%s",
                blockchain_network.value,
            )

        try:
            reclaim_result = handler.run_dormant_account_reclaim()
            reclaim_results.append(reclaim_result)
        except Exception:
            logger.exception(
                "[TRADING][WALLETMAINTENANCE][SERVICE] Dormant account reclaim failed — "
                "blockchain_network=%s",
                blockchain_network.value,
            )

    cycle_summary = TradingWalletMaintenanceCycleSummary(
        gas_results=gas_results,
        reclaim_results=reclaim_results,
    )
    dispatch_wallet_maintenance_alerts(cycle_summary)
    return cycle_summary
