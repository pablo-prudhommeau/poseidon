from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from src.configuration.config import settings
from src.core.aavesentinel.aave_sentinel_notification_service import AaveSentinelNotificationService
from src.core.aavesentinel.aave_sentinel_snapshot_service import AaveSentinelSnapshotService
from src.core.aavesentinel.aave_sentinel_structures import (
    AaveSentinelAlertSeverity,
    AaveSentinelRescueExecutionStatus,
)
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.telegram.telegram_update_registry import telegram_update_registry
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelService:
    def __init__(self) -> None:
        self.is_running: bool = False
        self._snapshot_service = AaveSentinelSnapshotService()
        self._notification_service = AaveSentinelNotificationService(
            fetch_position_snapshot=self._snapshot_service.fetch_position_snapshot,
        )

    @property
    def notification_service(self) -> AaveSentinelNotificationService:
        return self._notification_service

    async def start(self) -> None:
        if self.is_running:
            logger.info("[AAVESENTINEL][LIFECYCLE] Start request ignored because the service is already running")
            return

        if not settings.AAVE_SENTINEL_ENABLED:
            logger.info("[AAVESENTINEL][LIFECYCLE] Start request ignored because the sentinel is disabled")
            return

        self.is_running = True
        await self._snapshot_service.initialize()

        operating_mode_label = "PAPER MODE" if settings.AAVE_SENTINEL_PAPER_MODE else "LIVE TRADING"
        logger.info(
            "[AAVESENTINEL][LIFECYCLE] Sentinel initialized in %s for wallet %s",
            operating_mode_label,
            self._snapshot_service.wallet_address,
        )

        await self._notification_service.register_bot_commands()

        initial_position_snapshot = await self._snapshot_service.fetch_position_snapshot()
        if initial_position_snapshot is not None:
            detailed_initial_snapshot = await self._notification_service.format_notification_message(initial_position_snapshot)
            await self._notification_service.send_alert(
                "Sentinel démarré",
                f"Mode : {operating_mode_label}\n\n{detailed_initial_snapshot}",
                AaveSentinelAlertSeverity.INFO,
            )
            self._notification_service.bootstrap_state_from_snapshot(initial_position_snapshot)
        else:
            await self._notification_service.send_alert(
                "Sentinel démarré",
                f"Mode : {operating_mode_label}\n\n⚠️ Impossible de récupérer le snapshot initial.",
                AaveSentinelAlertSeverity.WARNING,
            )

        last_monitoring_cycle_timestamp: Optional[datetime] = None

        while self.is_running:
            try:
                current_loop_timestamp = get_current_local_datetime()
                should_run_monitoring_cycle = (
                        last_monitoring_cycle_timestamp is None
                        or (current_loop_timestamp - last_monitoring_cycle_timestamp).total_seconds() > settings.AAVE_SENTINEL_REPORTING_INTERVAL_SECONDS
                )

                if should_run_monitoring_cycle:
                    current_position_snapshot = await self._snapshot_service.fetch_position_snapshot()
                    last_monitoring_cycle_timestamp = current_loop_timestamp

                    if current_position_snapshot is not None:
                        logger.debug(
                            "[AAVESENTINEL][LIFECYCLE] Monitoring cycle snapshot resolved with health_factor=%0.4f",
                            current_position_snapshot.health_factor,
                        )
                        await self._notification_service.evaluate_risk_and_notify(current_position_snapshot)

                        if current_position_snapshot.health_factor < settings.AAVE_SENTINEL_HEALTH_FACTOR_EMERGENCY_THRESHOLD:
                            rescue_result = await self._snapshot_service.trigger_emergency_rescue()
                            if rescue_result.status == AaveSentinelRescueExecutionStatus.SIMULATED:
                                await self._notification_service.send_alert(
                                    "Simulation de sauvetage",
                                    rescue_result.message,
                                    AaveSentinelAlertSeverity.CRITICAL,
                                )
                            elif rescue_result.status == AaveSentinelRescueExecutionStatus.EXECUTED:
                                await self._notification_service.send_alert(
                                    "Sauvetage réussi",
                                    rescue_result.message,
                                    AaveSentinelAlertSeverity.SUCCESS,
                                )
                            elif rescue_result.status == AaveSentinelRescueExecutionStatus.FAILED:
                                await self._notification_service.send_alert(
                                    "Echec critique",
                                    rescue_result.message,
                                    AaveSentinelAlertSeverity.CRITICAL,
                                )
                            await asyncio.sleep(600)
            except Exception as exception:
                logger.exception("[AAVESENTINEL][LIFECYCLE] Monitoring loop failed: %s", exception)

            await asyncio.sleep(settings.TELEGRAM_POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.is_running = False
        await self._notification_service.close()
        logger.info("[AAVESENTINEL][LIFECYCLE] Sentinel shutdown sequence completed")


sentinel = AaveSentinelService()


def register_aave_sentinel_telegram_handlers() -> None:
    telegram_update_registry.register_message_handler(
        sentinel.notification_service.handle_telegram_message,
    )
    logger.info("[AAVESENTINEL][TELEGRAM] Sentinel Telegram handlers registered")
