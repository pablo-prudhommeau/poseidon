from __future__ import annotations

from src.core.structures.structures import BlockchainNetwork
from src.core.trading.walletmaintenance.trading_wallet_maintenance_structures import (
    TradingWalletMaintenanceChainGasResult,
    TradingWalletMaintenanceChainReclaimResult,
    TradingWalletMaintenanceOperationStatus,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

EVM_TRADING_NOT_SUPPORTED_REASON = "evm_trading_not_supported"


class TradingWalletMaintenanceEvmHandler:
    def __init__(self, blockchain_network: BlockchainNetwork) -> None:
        self._blockchain_network = blockchain_network

    def blockchain_network(self) -> BlockchainNetwork:
        return self._blockchain_network

    def run_native_gas_maintenance(self) -> TradingWalletMaintenanceChainGasResult:
        logger.debug(
            "[TRADING][WALLETMAINTENANCE][EVM][GAS][SKIPPED] Native gas maintenance skipped — "
            "blockchain_network=%s reason=%s",
            self._blockchain_network.value,
            EVM_TRADING_NOT_SUPPORTED_REASON,
        )
        return TradingWalletMaintenanceChainGasResult(
            blockchain_network=self._blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.SKIPPED,
            reason=EVM_TRADING_NOT_SUPPORTED_REASON,
        )

    def run_dormant_account_reclaim(self) -> TradingWalletMaintenanceChainReclaimResult:
        logger.debug(
            "[TRADING][WALLETMAINTENANCE][EVM][TOKEN_ACCOUNT][SKIPPED] Dormant account reclaim skipped — "
            "blockchain_network=%s reason=%s",
            self._blockchain_network.value,
            EVM_TRADING_NOT_SUPPORTED_REASON,
        )
        return TradingWalletMaintenanceChainReclaimResult(
            blockchain_network=self._blockchain_network,
            status=TradingWalletMaintenanceOperationStatus.SKIPPED,
            reason=EVM_TRADING_NOT_SUPPORTED_REASON,
        )
