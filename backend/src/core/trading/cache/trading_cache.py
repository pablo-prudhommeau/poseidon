from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Optional

from src.api.http.api_schemas import (
    TradingPositionPayload,
    TradingPositionPricePayload,
    TradingTradePayload,
    TradingPortfolioPayload,
    TradingLiquidityPayload,
)
from src.cache.cache_realm import CacheRealm
from src.core.trading.cache.trading_cache_structures import TradingState
from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)


def _touch_realm(realm: CacheRealm) -> None:
    from src.cache.cache_invalidator import cache_invalidator
    cache_invalidator.touch(realm)


class TradingCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached_positions: list[TradingPositionPayload] = []
        self._cached_position_prices: list[TradingPositionPricePayload] = []
        self._cached_trades: list[TradingTradePayload] = []
        self._cached_portfolio: Optional[TradingPortfolioPayload] = None
        self._cached_liquidity: Optional[TradingLiquidityPayload] = None
        self._cached_prices_by_pair_address: Optional[dict[str, float]] = None
        self._cached_available_cash_usd: Optional[float] = None
        self._last_successful_update_timestamp: datetime = get_current_local_datetime()

    def update_prices_by_pair_address(self, prices_by_pair_address: dict[str, float]) -> None:
        with self._lock:
            self._cached_prices_by_pair_address = prices_by_pair_address
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Prices by pair address updated (%d entries)", len(prices_by_pair_address))
        _touch_realm(CacheRealm.PRICES)

    def update_trading_positions_state(self, positions_payload: list[TradingPositionPayload]) -> None:
        with self._lock:
            self._cached_positions = positions_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Positions updated (%d entries)", len(positions_payload))
        _touch_realm(CacheRealm.POSITIONS)

    def update_trading_position_prices_state(self, position_prices_payload: list[TradingPositionPricePayload]) -> None:
        with self._lock:
            self._cached_position_prices = position_prices_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Position prices updated (%d entries)", len(position_prices_payload))
        _touch_realm(CacheRealm.POSITION_PRICES)

    def update_trading_trades_state(self, trades_payload: list[TradingTradePayload]) -> None:
        with self._lock:
            self._cached_trades = trades_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Trades updated (%d entries)", len(trades_payload))
        _touch_realm(CacheRealm.TRADES)

    def update_trading_portfolio_state(self, portfolio_payload: Optional[TradingPortfolioPayload]) -> None:
        with self._lock:
            self._cached_portfolio = portfolio_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Portfolio state updated")
        _touch_realm(CacheRealm.PORTFOLIO)

    def update_trading_liquidity_state(self, liquidity_payload: TradingLiquidityPayload) -> None:
        with self._lock:
            self._cached_liquidity = liquidity_payload
            self._cached_available_cash_usd = liquidity_payload.available_cash_balance
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Liquidity state updated")
        _touch_realm(CacheRealm.AVAILABLE_CASH)

    def get_trading_liquidity_state(self) -> Optional[TradingLiquidityPayload]:
        with self._lock:
            return self._cached_liquidity

    def get_available_cash_usd(self) -> Optional[float]:
        with self._lock:
            return self._cached_available_cash_usd

    def get_prices_by_pair_address(self) -> Optional[dict[str, float]]:
        with self._lock:
            return self._cached_prices_by_pair_address

    def get_trading_state(self) -> TradingState:
        with self._lock:
            return TradingState(
                positions=self._cached_positions,
                position_prices=self._cached_position_prices,
                trades=self._cached_trades,
                portfolio=self._cached_portfolio,
                liquidity=self._cached_liquidity,
                prices_by_pair_address=self._cached_prices_by_pair_address,
                available_cash_usd=self._cached_available_cash_usd
            )

    def get_last_update_timestamp(self) -> Optional[datetime]:
        with self._lock:
            return self._last_successful_update_timestamp


trading_cache = TradingCache()
