from datetime import datetime
from threading import Lock
from typing import Optional

from src.api.cache.trading_display_state_cache_structures import TradingDisplayState
from src.api.http.api_schemas import (
    TradingPositionPayload,
    TradingTradePayload,
    TradingPortfolioPayload,
    DcaStrategyPayload,
)
from src.logging.logger import get_application_logger
from src.core.utils.date_utils import get_current_local_datetime

logger = get_application_logger(__name__)


class TradingDisplayStateCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cached_positions: Optional[list[TradingPositionPayload]] = None
        self._cached_trades: Optional[list[TradingTradePayload]] = None
        self._cached_portfolio: Optional[TradingPortfolioPayload] = None
        self._cached_dca_strategies: Optional[list[DcaStrategyPayload]] = None
        self._last_successful_update_timestamp: Optional[datetime] = None

    def update_trading_state(
            self,
            positions_payload: list[TradingPositionPayload],
            trades_payload: list[TradingTradePayload],
            portfolio_payload: Optional[TradingPortfolioPayload],
    ) -> None:
        with self._lock:
            self._cached_positions = positions_payload
            self._cached_trades = trades_payload

            if portfolio_payload is not None:
                self._cached_portfolio = portfolio_payload

            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][DISPLAY][CACHE] Trading state successfully updated in memory")

    def update_dca_strategies_state(self, dca_strategies_payload: list[DcaStrategyPayload]) -> None:
        with self._lock:
            self._cached_dca_strategies = dca_strategies_payload
            self._last_successful_update_timestamp = get_current_local_datetime()
            logger.debug("[TRADING][DISPLAY][CACHE] DCA strategies state successfully updated in memory")

    def get_trading_state(self) -> TradingDisplayState:
        with self._lock:
            return TradingDisplayState(
                positions=self._cached_positions,
                trades=self._cached_trades,
                portfolio=self._cached_portfolio,
            )

    def get_dca_strategies_state(self) -> Optional[list[DcaStrategyPayload]]:
        with self._lock:
            return self._cached_dca_strategies

    def get_last_update_timestamp(self) -> Optional[datetime]:
        with self._lock:
            return self._last_successful_update_timestamp


trading_display_state_cache = TradingDisplayStateCache()
