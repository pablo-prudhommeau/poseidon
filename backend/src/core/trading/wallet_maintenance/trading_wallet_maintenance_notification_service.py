from __future__ import annotations

from src.core.trading.wallet_maintenance.trading_wallet_maintenance_structures import (
    TradingWalletMaintenanceCycleSummary,
    TradingWalletMaintenanceOperationStatus,
)
from src.integrations.telegram.telegram_client import send_alert
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def dispatch_wallet_maintenance_alerts(cycle_summary: TradingWalletMaintenanceCycleSummary) -> None:
    for gas_result in cycle_summary.gas_results:
        if gas_result.status != TradingWalletMaintenanceOperationStatus.FAILED:
            continue
        if gas_result.reason == "insufficient_stablecoin_for_refill":
            native_balance_text = "unknown"
            if gas_result.native_balance_before_lamports is not None:
                native_balance_text = f"{gas_result.native_balance_before_lamports / 1_000_000_000.0:.6f}"
            send_alert(
                title=f"Wallet maintenance — {gas_result.blockchain_network.value} gas refill blocked",
                body=(
                    f"Native balance: {native_balance_text}\n"
                    "Stablecoin buffer prevents automatic gas refill.\n"
                    f"Reason: {gas_result.reason}"
                ),
                emoji_indicator="⚠️",
            )
            continue

        send_alert(
            title=f"Wallet maintenance — {gas_result.blockchain_network.value} gas maintenance failed",
            body=f"Reason: {gas_result.reason or 'unknown'}",
            emoji_indicator="🚨",
        )

    for reclaim_result in cycle_summary.reclaim_results:
        if reclaim_result.status != TradingWalletMaintenanceOperationStatus.FAILED:
            continue
        send_alert(
            title=f"Wallet maintenance — {reclaim_result.blockchain_network.value} reclaim failed",
            body=f"Reason: {reclaim_result.reason or 'unknown'}",
            emoji_indicator="🚨",
        )

    logger.debug("[TRADING][WALLET_MAINTENANCE][SERVICE] Alert dispatch completed")
