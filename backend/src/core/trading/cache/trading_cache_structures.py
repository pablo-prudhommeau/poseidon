from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.api.http.api_schemas import (
    TradingPositionPayload,
    TradingTradePayload,
    TradingPortfolioPayload,
    TradingLiquidityPayload,
    TradingShadowMetaPayload,
)


class TradingState(BaseModel):
    positions: Optional[list[TradingPositionPayload]] = None
    trades: Optional[list[TradingTradePayload]] = None
    portfolio: Optional[TradingPortfolioPayload] = None
    liquidity: Optional[TradingLiquidityPayload] = None
    shadow_meta: Optional[TradingShadowMetaPayload] = None
    prices_by_pair_address: Optional[dict[str, float]] = None
