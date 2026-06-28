from __future__ import annotations

import asyncio

from src.configuration.config import settings
from src.integrations.telegram.telegram_client import get_updates
from src.integrations.telegram.telegram_update_registry import telegram_update_registry
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class TelegramPollingJob:

    def __init__(self) -> None:
        self.is_running: bool = False
        self._last_telegram_update_identifier: int = 0

    async def run_loop(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.info("[TELEGRAM][POLLING][JOB] Telegram bot token missing, polling skipped")
            return

        if not telegram_update_registry.has_registered_handlers():
            logger.info("[TELEGRAM][POLLING][JOB] No Telegram handlers registered, polling skipped")
            return

        self.is_running = True
        logger.info(
            "[TELEGRAM][POLLING][JOB] Telegram polling loop starting (interval=%ss)",
            settings.TELEGRAM_POLL_INTERVAL_SECONDS,
        )

        while self.is_running:
            try:
                await self._process_telegram_updates()
            except Exception:
                logger.exception("[TELEGRAM][POLLING][JOB] Telegram update processing failed")

            await asyncio.sleep(settings.TELEGRAM_POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        self.is_running = False
        logger.info("[TELEGRAM][POLLING][JOB] Telegram polling loop stopped")

    async def _process_telegram_updates(self) -> None:
        telegram_updates = await asyncio.to_thread(
            get_updates,
            self._last_telegram_update_identifier + 1,
            ["message", "callback_query"],
            0,
        )

        for telegram_update in telegram_updates:
            self._last_telegram_update_identifier = telegram_update.update_id

            if telegram_update.callback_query is not None:
                await telegram_update_registry.dispatch_callback_query(telegram_update.callback_query)
                continue

            if telegram_update.message is not None:
                await telegram_update_registry.dispatch_message(telegram_update.message)
