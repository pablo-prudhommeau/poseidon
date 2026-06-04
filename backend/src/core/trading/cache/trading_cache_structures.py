from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.api.http.api_schemas import (
    TradingPositionPayload,
    TradingPositionPricePayload,
    TradingTradePayload,
    TradingPortfolioPayload,
    TradingLiquidityPayload,
)
from src.integrations.blockchain.blockchain_price_structures import OnchainPricesByPairAddress


class TradingState(BaseModel):
    positions: Optional[list[TradingPositionPayload]] = None
    position_prices: Optional[list[TradingPositionPricePayload]] = None
    trades: Optional[list[TradingTradePayload]] = None
    portfolio: Optional[TradingPortfolioPayload] = None
    liquidity: Optional[TradingLiquidityPayload] = None
    prices_by_pair_address: Optional[OnchainPricesByPairAddress] = None
    available_cash_usd: Optional[float] = None
