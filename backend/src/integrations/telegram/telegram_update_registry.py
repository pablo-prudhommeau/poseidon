from __future__ import annotations

from collections.abc import Awaitable, Callable

from src.integrations.telegram.telegram_structures import TelegramCallbackQuery, TelegramMessage
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

TelegramMessageHandler = Callable[[TelegramMessage], Awaitable[None]]
TelegramCallbackQueryHandler = Callable[[TelegramCallbackQuery], Awaitable[None]]


class TelegramUpdateRegistry:

    def __init__(self) -> None:
        self._message_handlers: list[TelegramMessageHandler] = []
        self._callback_query_handlers: list[TelegramCallbackQueryHandler] = []

    def register_message_handler(self, message_handler: TelegramMessageHandler) -> None:
        self._message_handlers.append(message_handler)
        logger.debug(
            "[TELEGRAM][REGISTRY] Message handler registered — total=%d",
            len(self._message_handlers),
        )

    def register_callback_query_handler(self, callback_query_handler: TelegramCallbackQueryHandler) -> None:
        self._callback_query_handlers.append(callback_query_handler)
        logger.debug(
            "[TELEGRAM][REGISTRY] Callback query handler registered — total=%d",
            len(self._callback_query_handlers),
        )

    def has_registered_handlers(self) -> bool:
        return len(self._message_handlers) > 0 or len(self._callback_query_handlers) > 0

    async def dispatch_message(self, telegram_message: TelegramMessage) -> None:
        for message_handler in self._message_handlers:
            await message_handler(telegram_message)

    async def dispatch_callback_query(self, telegram_callback_query: TelegramCallbackQuery) -> None:
        for callback_query_handler in self._callback_query_handlers:
            await callback_query_handler(telegram_callback_query)


telegram_update_registry = TelegramUpdateRegistry()
