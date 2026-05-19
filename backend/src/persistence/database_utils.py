from __future__ import annotations

from typing import Any

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

from src.core.trading.screener.trading_screener_structures import (
    TRADING_SCREENER_PROVIDER_DEXSCREENER,
    TradingScreenerEnvelope,
)


class PydanticModelJsonType(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, model_class: type):
        super().__init__()
        self._model_class = model_class

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self._model_class):
            return value.model_dump(mode="json", exclude_none=True)
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", exclude_none=True)
        if isinstance(value, dict):
            return value
        raise TypeError(f"Expected {self._model_class.__name__} or dict, got {type(value).__name__}")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self._model_class):
            return value
        return self._model_class.model_validate(value)


class PydanticModelListJsonType(TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, item_model_class: type):
        super().__init__()
        self._item_model_class = item_model_class

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, list):
            raise TypeError(f"Expected list[{self._item_model_class.__name__}], got {type(value).__name__}")
        serialized_items: list[dict] = []
        for item in value:
            if isinstance(item, self._item_model_class):
                serialized_items.append(item.model_dump(mode="json", exclude_none=True))
            elif hasattr(item, "model_dump"):
                serialized_items.append(item.model_dump(mode="json", exclude_none=True))
            elif isinstance(item, dict):
                serialized_items.append(item)
            else:
                raise TypeError(f"Invalid item type for {self._item_model_class.__name__}: {type(item).__name__}")
        return serialized_items

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, list):
            raise TypeError(f"Expected JSON list for {self._item_model_class.__name__}, got {type(value).__name__}")
        return [self._item_model_class.model_validate(item) for item in value]


class ScreenerEnvelopeJsonType(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(JSON(none_as_null=True))

    def process_bind_param(self, value: Any, dialect) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, TradingScreenerEnvelope):
            return {
                "provider_id": value.provider_id,
                "payload": value.payload,
            }
        if isinstance(value, dict):
            if "provider_id" in value and "payload" in value:
                return value
            if "screener_provider" in value and "payload" in value:
                return {
                    "provider_id": str(value["screener_provider"]),
                    "payload": dict(value["payload"]),
                }
            return {
                "provider_id": TRADING_SCREENER_PROVIDER_DEXSCREENER,
                "payload": value,
            }
        raise TypeError(
            f"Expected TradingScreenerEnvelope or screener envelope dict, got {type(value).__name__}"
        )

    def process_result_value(self, value: Any, dialect) -> TradingScreenerEnvelope:
        if value is None:
            raise TypeError("Screener envelope cannot be null")
        if isinstance(value, TradingScreenerEnvelope):
            return value
        if not isinstance(value, dict):
            raise TypeError(f"Expected JSON object for screener envelope, got {type(value).__name__}")
        if "provider_id" in value and "payload" in value:
            return TradingScreenerEnvelope(
                provider_id=str(value["provider_id"]),
                payload=dict(value["payload"]),
            )
        if "screener_provider" in value and "payload" in value:
            return TradingScreenerEnvelope(
                provider_id=str(value["screener_provider"]),
                payload=dict(value["payload"]),
            )
        return TradingScreenerEnvelope(
            provider_id=TRADING_SCREENER_PROVIDER_DEXSCREENER,
            payload=dict(value),
        )
