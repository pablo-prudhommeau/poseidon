from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Optional

from src.api.http.api_schemas import (
    TradingPositionPayload,
    TradingTradePayload,
    TradingPortfolioPayload,
    TradingLiquidityPayload,
    TradingShadowMetaPayload,
)
from src.cache.cache_realm import CacheRealm
from src.core.trading.cache.trading_cache_structures import TradingState
from src.core.trading.shadowing.shadow_trading_structures import ShadowIntelligenceSnapshot
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
        self._cached_trades: list[TradingTradePayload] = []
        self._cached_portfolio: Optional[TradingPortfolioPayload] = None
        self._cached_liquidity: Optional[TradingLiquidityPayload] = None
        self._cached_shadow_meta: Optional[TradingShadowMetaPayload] = None
        self._cached_prices_by_pair_address: Optional[dict[str, float]] = None
        self._cached_available_cash_usd: Optional[float] = None
        self._cached_shadow_intelligence_snapshot: Optional[ShadowIntelligenceSnapshot] = None
        self._last_successful_update_timestamp: datetime = get_current_local_datetime()

    def update_prices_by_pair_address(self, prices_by_pair_address: dict[str, float]) -> None:
        with self._lock:
            self._cached_prices_by_pair_address = prices_by_pair_address
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Prices by pair address updated (%d entries)", len(prices_by_pair_address))
        _touch_realm(CacheRealm.PRICES)

    def get_prices_by_pair_address(self) -> Optional[dict[str, float]]:
        with self._lock:
            return self._cached_prices_by_pair_address

    def update_trading_positions_state(self, positions_payload: list[TradingPositionPayload]) -> None:
        with self._lock:
            self._cached_positions = positions_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Positions updated (%d entries)", len(positions_payload))
        _touch_realm(CacheRealm.POSITIONS)

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

    def update_shadow_intelligence_snapshot(self, snapshot: ShadowIntelligenceSnapshot) -> None:
        with self._lock:
            self._cached_shadow_intelligence_snapshot = snapshot
            logger.debug("[TRADING][CACHE] Shadow intelligence snapshot updated")
        _touch_realm(CacheRealm.SHADOW_INTELLIGENCE_SNAPSHOT)

    def update_trading_shadow_meta_state(self, shadow_meta_payload: TradingShadowMetaPayload) -> None:
        with self._lock:
            self._cached_shadow_meta = shadow_meta_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][CACHE] Shadow meta state updated")
        _touch_realm(CacheRealm.SHADOW_INTELLIGENCE_SNAPSHOT)

    def get_trading_shadow_meta_state(self) -> Optional[TradingShadowMetaPayload]:
        with self._lock:
            return self._cached_shadow_meta

    def get_shadow_intelligence_snapshot(self) -> Optional[ShadowIntelligenceSnapshot]:
        with self._lock:
            return self._cached_shadow_intelligence_snapshot

    def get_trading_state(self) -> TradingState:
        with self._lock:
            return TradingState(
                positions=self._cached_positions,
                trades=self._cached_trades,
                portfolio=self._cached_portfolio,
                liquidity=self._cached_liquidity,
                shadow_meta=self._cached_shadow_meta,
                prices_by_pair_address=self._cached_prices_by_pair_address,
            )

    def get_last_update_timestamp(self) -> Optional[datetime]:
        with self._lock:
            return self._last_successful_update_timestamp


trading_state_cache = TradingCache()
