from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TelegramInlineKeyboardButton(BaseModel):
    text: str
    callback_data: str


class TelegramInlineKeyboardMarkup(BaseModel):
    inline_keyboard: List[List[TelegramInlineKeyboardButton]]


class TelegramMessagePayload(BaseModel):
    chat_id: str
    text: str
    parse_mode: str = "HTML"
    disable_web_page_preview: bool = True
    reply_markup: Optional[TelegramInlineKeyboardMarkup] = None


class TelegramUser(BaseModel):
    id: int
    is_bot: bool
    first_name: str
    username: Optional[str] = None


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: int
    from_user: Optional[TelegramUser] = Field(default=None, alias="from")
    chat: dict
    date: int
    text: Optional[str] = None


class TelegramCallbackQuery(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_user: TelegramUser = Field(alias="from")
    message: Optional[TelegramMessage] = None
    data: str


class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None
    callback_query: Optional[TelegramCallbackQuery] = None
