from __future__ import annotations

from typing import Optional, cast

from fastapi.encoders import jsonable_encoder

from src.api.http.api_schemas import (
    TradingLiquidityPayload,
    TradingPortfolioPayload,
    TradingPositionPayload,
    TradingPositionPricePayload,
    TradingTradePayload,
)
from src.api.websocket.websocket_manager import websocket_manager
from src.cache.cache_invalidator import cache_invalidator
from src.cache.cache_realm import CacheRealm
from src.core.structures.structures import WebsocketMessageType
from src.core.trading.cache.trading_cache import trading_cache
from src.core.trading.cache.trading_cache_payload_builders import (
    build_trading_positions_payloads,
    build_trading_position_prices_payloads,
    build_trading_trades_payloads,
    build_trading_liquidity_payload,
    build_trading_prices_payload,
    build_trading_portfolio_payload_with_snapshot_creation,
)
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


class _PricesRebuilder:
    realm = CacheRealm.PRICES
    ttl_seconds = 30.0

    def rebuild(self) -> dict[str, float]:
        return build_trading_prices_payload()

    def apply_to_cache(self, payload: dict[str, float]) -> None:
        trading_cache.update_prices_by_pair_address(payload)

    async def notify_websocket(self, _payload: object) -> None:
        pass


class _PositionsRebuilder:
    realm = CacheRealm.POSITIONS
    ttl_seconds = 30.0

    def rebuild(self) -> list[TradingPositionPayload]:
        prices_candidate = trading_cache.get_prices_by_pair_address()
        prices_lookup: dict[str, float] = prices_candidate if prices_candidate is not None else {}
        return build_trading_positions_payloads(prices_lookup)

    def apply_to_cache(self, payload: object) -> None:
        trading_cache.update_trading_positions_state(cast(list[TradingPositionPayload], payload))

    async def notify_websocket(self, payload: object) -> None:
        positions_payload = cast(list[TradingPositionPayload], payload)
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.POSITIONS.value,
            "payload": jsonable_encoder(positions_payload),
        })


class _PositionPricesRebuilder:
    realm = CacheRealm.POSITION_PRICES
    ttl_seconds = 30.0

    def rebuild(self) -> list[TradingPositionPricePayload]:
        prices_candidate = trading_cache.get_prices_by_pair_address()
        prices_lookup: dict[str, float] = prices_candidate if prices_candidate is not None else {}
        return build_trading_position_prices_payloads(prices_lookup)

    def apply_to_cache(self, payload: object) -> None:
        trading_cache.update_trading_position_prices_state(cast(list[TradingPositionPricePayload], payload))

    async def notify_websocket(self, payload: object) -> None:
        position_prices_payload = cast(list[TradingPositionPricePayload], payload)
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.POSITION_PRICES.value,
            "payload": jsonable_encoder(position_prices_payload),
        })


class _TradesRebuilder:
    realm = CacheRealm.TRADES
    ttl_seconds = 30.0

    def rebuild(self) -> list[TradingTradePayload]:
        return build_trading_trades_payloads()

    def apply_to_cache(self, payload: list[TradingTradePayload]) -> None:
        trading_cache.update_trading_trades_state(payload)

    async def notify_websocket(self, payload: list[TradingTradePayload]) -> None:
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.TRADES.value,
            "payload": jsonable_encoder(payload),
        })


class _AvailableCashRebuilder:
    realm = CacheRealm.AVAILABLE_CASH
    ttl_seconds = 30.0

    def rebuild(self) -> TradingLiquidityPayload:
        try:
            return build_trading_liquidity_payload()
        except ConnectionError:
            previous_liquidity = trading_cache.get_trading_liquidity_state()
            if previous_liquidity is not None:
                logger.warning(
                    "[TRADING][CACHE][LIQUIDITY] Live balances unavailable; retaining cached liquidity payload"
                )
                return previous_liquidity
            raise

    def apply_to_cache(self, payload: TradingLiquidityPayload) -> None:
        trading_cache.update_trading_liquidity_state(payload)

    async def notify_websocket(self, payload: TradingLiquidityPayload) -> None:
        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.LIQUIDITY.value,
            "payload": jsonable_encoder(payload),
        })


class _PortfolioRebuilder:
    realm = CacheRealm.PORTFOLIO
    ttl_seconds = 30.0

    def rebuild(self) -> Optional[TradingPortfolioPayload]:
        return build_trading_portfolio_payload_with_snapshot_creation()

    def apply_to_cache(self, payload: TradingPortfolioPayload) -> None:
        trading_cache.update_trading_portfolio_state(payload)

    async def notify_websocket(self, payload: TradingPortfolioPayload) -> None:
        if payload is None:
            return

        await websocket_manager.broadcast_json_payload({
            "type": WebsocketMessageType.PORTFOLIO.value,
            "payload": jsonable_encoder(payload),
        })


def register_trading_rebuilders() -> None:
    cache_invalidator.register(_PricesRebuilder())
    cache_invalidator.register(_PositionsRebuilder())
    cache_invalidator.register(_PositionPricesRebuilder())
    cache_invalidator.register(_TradesRebuilder())
    cache_invalidator.register(_AvailableCashRebuilder())
    cache_invalidator.register(_PortfolioRebuilder())
    logger.info("[TRADING][CACHE][REBUILDERS] %d trading rebuilders registered", len(cache_invalidator._rebuilders))
