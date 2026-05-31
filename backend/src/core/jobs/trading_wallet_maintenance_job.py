from __future__ import annotations

import asyncio

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.trading.walletmaintenance.trading_wallet_maintenance_service import run_wallet_maintenance_cycle
from src.core.trading.walletmaintenance.trading_wallet_maintenance_structures import (
    TradingWalletMaintenanceOperationStatus,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TradingWalletMaintenanceJob:
    async def run_loop(self) -> None:
        interval_seconds = settings.TRADING_WALLET_MAINTENANCE_INTERVAL_SECONDS
        logger.info(
            "[TRADING][WALLETMAINTENANCE][JOB] Wallet maintenance loop starting — interval_seconds=%s",
            interval_seconds,
        )
        while True:
            try:
                await self._execute_maintenance_cycle()
            except Exception:
                logger.exception(
                    "[TRADING][WALLETMAINTENANCE][JOB] Wallet maintenance cycle failed — reason=cycle_execution_failed"
                )
            await asyncio.sleep(interval_seconds)

    async def _execute_maintenance_cycle(self) -> None:
        cycle_summary = await asyncio.to_thread(run_wallet_maintenance_cycle)
        gas_success_count = len([
            result for result in cycle_summary.gas_results
            if result.status == TradingWalletMaintenanceOperationStatus.SUCCESS
        ])
        gas_failed_count = len([
            result for result in cycle_summary.gas_results
            if result.status == TradingWalletMaintenanceOperationStatus.FAILED
        ])
        gas_skipped_count = len([
            result for result in cycle_summary.gas_results
            if result.status == TradingWalletMaintenanceOperationStatus.SKIPPED
        ])
        gas_not_required_count = len([
            result for result in cycle_summary.gas_results
            if result.status == TradingWalletMaintenanceOperationStatus.NOT_REQUIRED
        ])
        reclaim_success_count = len([
            result for result in cycle_summary.reclaim_results
            if result.status == TradingWalletMaintenanceOperationStatus.SUCCESS
        ])
        reclaim_failed_count = len([
            result for result in cycle_summary.reclaim_results
            if result.status == TradingWalletMaintenanceOperationStatus.FAILED
        ])
        reclaim_skipped_count = len([
            result for result in cycle_summary.reclaim_results
            if result.status == TradingWalletMaintenanceOperationStatus.SKIPPED
        ])
        reclaim_not_required_count = len([
            result for result in cycle_summary.reclaim_results
            if result.status == TradingWalletMaintenanceOperationStatus.NOT_REQUIRED
        ])
        if cycle_summary.gas_results or cycle_summary.reclaim_results:
            cache_invalidator.mark_dirty(CacheRealm.AVAILABLE_CASH, CacheRealm.PORTFOLIO)
        logger.info(
            "[TRADING][WALLETMAINTENANCE][JOB] Wallet maintenance cycle completed with gas and reclaim outcomes — "
            "gas_result_count=%d gas_success_count=%d gas_failed_count=%d gas_skipped_count=%d "
            "gas_not_required_count=%d reclaim_result_count=%d reclaim_success_count=%d "
            "reclaim_failed_count=%d reclaim_skipped_count=%d reclaim_not_required_count=%d",
            len(cycle_summary.gas_results),
            gas_success_count,
            gas_failed_count,
            gas_skipped_count,
            gas_not_required_count,
            len(cycle_summary.reclaim_results),
            reclaim_success_count,
            reclaim_failed_count,
            reclaim_skipped_count,
            reclaim_not_required_count,
        )
