from __future__ import annotations

from src.configuration.config import settings
from src.core.structures.structures import BlockchainNetwork
from src.core.trading.walletmaintenance.evm.trading_wallet_maintenance_evm_handler import (
    TradingWalletMaintenanceEvmHandler,
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
                "[TRADING][WALLETMAINTENANCE][SERVICE] Unknown allowed chain ignored — "
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
    gas_results: list[TradingWalletMaintenanceChainGasResult] = []
    reclaim_results: list[TradingWalletMaintenanceChainReclaimResult] = []

    if not handlers:
        logger.debug(
            "[TRADING][WALLETMAINTENANCE][SERVICE] No active chain handlers for maintenance cycle — "
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
