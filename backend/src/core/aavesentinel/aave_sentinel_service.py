from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.configuration.config import settings
from src.core.aavesentinel.cache.aave_sentinel_cache import aave_sentinel_state_cache
from src.core.aavesentinel.cache.aave_sentinel_cache_payload_builders import (
    build_aave_sentinel_position_payload,
    resolve_aave_sentinel_state_for_display,
)
from src.core.aavesentinel.cache.aave_sentinel_cache_transaction_fingerprint_service import (
    poll_transaction_fingerprint_and_invalidate_capital_flow_if_changed,
)
from src.core.aavesentinel.notification.aave_sentinel_notification_service import AaveSentinelNotificationService
from src.core.utils.date_utils import get_current_local_datetime
from src.integrations.blockchain.blockchain_rpc_registry import BlockchainRpcRateLimitedError
from src.integrations.telegram.telegram_structures import TelegramMessage
from src.integrations.telegram.telegram_update_registry import telegram_update_registry
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class AaveSentinelService:
    def __init__(self) -> None:
        self.is_running: bool = False
        self._notification_service: Optional[AaveSentinelNotificationService] = None

    @property
    def notification_service(self) -> AaveSentinelNotificationService:
        if self._notification_service is None:
            raise RuntimeError("Aave sentinel notification service is not initialized")
        return self._notification_service

    async def start(self) -> None:
        if self.is_running:
            logger.info("[AAVESENTINEL][LIFECYCLE] Start request ignored because the service is already running")
            return

        if not settings.AAVE_SENTINEL_ENABLED:
            logger.info("[AAVESENTINEL][LIFECYCLE] Start request ignored because the sentinel is disabled")
            return

        self.is_running = True
        self._notification_service = AaveSentinelNotificationService()

        initial_sentinel_state = await resolve_aave_sentinel_state_for_display()
        initial_position_snapshot = initial_sentinel_state.position_snapshot
        if initial_position_snapshot is None:
            raise RuntimeError("Aave sentinel initial position snapshot could not be resolved")

        logger.info("[AAVESENTINEL][LIFECYCLE] Sentinel initialized")

        await self._notification_service.register_bot_commands()
        self._notification_service.bootstrap_state_from_snapshot(position_snapshot=initial_position_snapshot)

        last_monitoring_cycle_timestamp: Optional[datetime] = None

        while self.is_running:
            try:
                current_loop_timestamp = get_current_local_datetime()
                should_run_monitoring_cycle = (
                        last_monitoring_cycle_timestamp is None
                        or (
                                current_loop_timestamp - last_monitoring_cycle_timestamp
                        ).total_seconds() > settings.AAVE_SENTINEL_REPORTING_INTERVAL_SECONDS
                )

                if should_run_monitoring_cycle:
                    await poll_transaction_fingerprint_and_invalidate_capital_flow_if_changed()

                    current_position_snapshot = await build_aave_sentinel_position_payload()
                    aave_sentinel_state_cache.update_position_snapshot(position_snapshot=current_position_snapshot)
                    cache_invalidator.touch(CacheRealm.AAVE_SENTINEL_POSITION)
                    last_monitoring_cycle_timestamp = current_loop_timestamp

                    if current_position_snapshot is not None:
                        logger.debug(
                            "[AAVESENTINEL][LIFECYCLE] Monitoring cycle snapshot resolved with health_factor=%0.4f",
                            current_position_snapshot.health_factor,
                        )
                        await self._notification_service.evaluate_risk_and_notify(
                            position_snapshot=current_position_snapshot,
                        )
            except BlockchainRpcRateLimitedError:
                logger.warning(
                    "[AAVESENTINEL][LIFECYCLE] Monitoring cycle skipped because the RPC endpoint is rate limited",
                )
            except Exception as exception:
                logger.exception("[AAVESENTINEL][LIFECYCLE] Monitoring loop failed: %s", exception)

            await asyncio.sleep(settings.TELEGRAM_POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.is_running = False
        if self._notification_service is not None:
            await self._notification_service.close()
        logger.info("[AAVESENTINEL][LIFECYCLE] Sentinel shutdown sequence completed")


sentinel = AaveSentinelService()


def resolve_running_aave_sentinel_notification_service() -> Optional[AaveSentinelNotificationService]:
    return sentinel._notification_service


async def _handle_sentinel_telegram_message(telegram_message: TelegramMessage) -> None:
    if sentinel._notification_service is None:
        logger.debug("[AAVESENTINEL][TELEGRAM] Message ignored because sentinel is not initialized")
        return

    await sentinel.notification_service.handle_telegram_message(telegram_message)


def register_aave_sentinel_telegram_handlers() -> None:
    telegram_update_registry.register_message_handler(_handle_sentinel_telegram_message)
    logger.info("[AAVESENTINEL][TELEGRAM] Sentinel Telegram handlers registered")
